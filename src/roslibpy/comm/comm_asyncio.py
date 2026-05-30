"""Asyncio-based transport for roslibpy.

Opt-in alternative to the default twisted/autobahn transport. Selected via:

* env var ``ROSLIBPY_TRANSPORT=asyncio``
* module-level ``roslibpy.set_default_transport("asyncio")``
* per-instance ``Ros(host, port, transport="asyncio")``

Why a separate transport
------------------------

Twisted's reactor is a process-wide singleton that cannot be restarted after
``reactor.stop()``. Long-running test sessions that create many ``Ros``
instances accumulate state on it. asyncio loops, by contrast, are first-class
objects that can be started, stopped, and discarded independently; that
gives us clean per-process (or per-test, when needed) isolation.

The public ``Ros`` / ``Topic`` / ``Service`` / ``ActionClient`` / ``Param`` API
is unaffected — only the transport layer changes.

Dependencies
------------

This module imports the ``websockets`` library lazily; it is declared as an
optional extra (``roslibpy[asyncio]``). The transport raises a clear error if
selected without the dependency available.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..core import RosTimeoutError
from ..event_emitter import EventEmitterMixin
from . import RosBridgeProtocol

LOGGER = logging.getLogger("roslibpy")

# Defaults matched to ReconnectingClientFactory's behaviour so users moving
# between transports see the same retry cadence.
DEFAULT_INITIAL_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RECONNECT_DELAY = 3600.0
DEFAULT_RECONNECT_FACTOR = 2.7
DEFAULT_RECONNECT_JITTER = 0.119
DEFAULT_MAX_RECONNECT_RETRIES = None  # None = unbounded, matching twisted

# Single shared event loop manager, owned by the module so all factories in
# this process share one background thread + loop — same singleton semantics
# as the twisted reactor, but with proper teardown via terminate().
_MANAGER_SINGLETON: "Optional[AsyncioEventLoopManager]" = None
_MANAGER_SINGLETON_LOCK = threading.Lock()


def _get_shared_manager() -> "AsyncioEventLoopManager":
    global _MANAGER_SINGLETON
    if _MANAGER_SINGLETON is not None:
        return _MANAGER_SINGLETON
    with _MANAGER_SINGLETON_LOCK:
        if _MANAGER_SINGLETON is not None:
            return _MANAGER_SINGLETON
        _MANAGER_SINGLETON = AsyncioEventLoopManager()
        return _MANAGER_SINGLETON


def _import_websockets():
    """Import the optional ``websockets`` dependency lazily, with a clear error."""
    try:
        import websockets  # noqa: F401
        from websockets.asyncio.client import connect as ws_connect  # noqa: F401
        from websockets.exceptions import ConnectionClosed, InvalidStatus  # noqa: F401
    except ImportError as exc:  # pragma: no cover — exercised by missing-extra test
        raise ImportError(
            "The asyncio transport requires the 'websockets' package. " "Install with: pip install 'roslibpy[asyncio]'"
        ) from exc
    return ws_connect, ConnectionClosed, InvalidStatus


class AsyncioRosBridgeProtocol(RosBridgeProtocol):
    """ROS Bridge protocol implementation over an asyncio websockets connection.

    Instances are owned by :class:`AsyncioRosBridgeClientFactory`; user code
    interacts with the factory, not the protocol directly. ``send_message``
    and ``send_close`` are thread-safe — they schedule the IO onto the
    background loop via ``call_soon_threadsafe``.
    """

    def __init__(self, factory: "AsyncioRosBridgeClientFactory", ws_connection: Any) -> None:
        super(AsyncioRosBridgeProtocol, self).__init__()
        self.factory = factory
        self.ws = ws_connection
        self._manual_disconnect = False
        self._closed = False

    def send_message(self, payload: bytes) -> None:
        """Send an already-encoded ROS bridge message frame.

        Safe to call from any thread; the actual send is scheduled onto the
        background loop.
        """
        if self._closed:
            return
        loop = self.factory.manager.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._schedule_send, payload)

    def _schedule_send(self, payload: bytes) -> None:
        # Runs on the loop thread.
        asyncio.create_task(self._send_async(payload))

    async def _send_async(self, payload: bytes) -> None:
        try:
            await self.ws.send(payload)
        except Exception:
            LOGGER.exception("Failed to send ROS bridge frame; connection likely dropped.")

    def send_close(self) -> None:
        """Initiate a clean WebSocket close.

        Sets the manual-disconnect flag so the factory's reconnect supervisor
        knows to stand down, then asks the loop to close the socket.
        """
        self._manual_disconnect = True
        if self._closed:
            return
        loop = self.factory.manager.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._schedule_close)

    def _schedule_close(self) -> None:
        asyncio.create_task(self._close_async())

    async def _close_async(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            LOGGER.debug("Error during WebSocket close (often harmless if already closed).", exc_info=True)


class AsyncioRosBridgeClientFactory(EventEmitterMixin):
    """ROS Bridge client factory backed by the ``websockets`` library on asyncio.

    Mirrors the public surface of :class:`AutobahnRosBridgeClientFactory` so
    that callers (``Ros`` and friends) don't care which transport is selected.
    """

    # Class-level reconnect tuning, kept as class attributes so the
    # `set_initial_delay` / `set_max_delay` / `set_max_retries` classmethods
    # behave like their autobahn counterparts.
    initialDelay = DEFAULT_INITIAL_RECONNECT_DELAY
    maxDelay = DEFAULT_MAX_RECONNECT_DELAY
    factor = DEFAULT_RECONNECT_FACTOR
    jitter = DEFAULT_RECONNECT_JITTER
    maxRetries = DEFAULT_MAX_RECONNECT_RETRIES

    def __init__(self, url: str, headers: Optional[dict] = None) -> None:
        super(AsyncioRosBridgeClientFactory, self).__init__()
        self._validate_url(url)
        self._url = url
        self._headers = headers
        self._proto: Optional[AsyncioRosBridgeProtocol] = None
        self._manager: Optional[AsyncioEventLoopManager] = None
        # Lock guarding `_proto` reads/writes in on_ready / ready. Closes the
        # TOCTOU race between checking ``_proto`` and registering a one-shot
        # "ready" listener that exists in the autobahn factory.
        self._proto_lock = threading.Lock()
        # Background reconnect supervisor task, owned by the loop thread.
        self._supervisor_task: Optional[asyncio.Task] = None
        self._stop_supervisor = False
        self._retry_count = 0

    # ------------------------------------------------------------------
    # Public surface mirroring AutobahnRosBridgeClientFactory
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss") or not parsed.netloc:
            raise ValueError("WebSocket URL must use the ws:// or wss:// schema")

    def connect(self) -> None:
        """Schedule the initial WebSocket connection on the background loop."""
        manager = self.manager
        manager.run()  # ensure background loop is up
        loop = manager.loop
        assert loop is not None
        # Schedule the supervisor task; it owns the connect / reconnect loop.
        loop.call_soon_threadsafe(self._launch_supervisor)

    def _launch_supervisor(self) -> None:
        if self._supervisor_task is not None and not self._supervisor_task.done():
            return
        self._stop_supervisor = False
        self._supervisor_task = asyncio.create_task(self._supervise_connection())

    @property
    def is_connected(self) -> bool:
        proto = self._proto
        return proto is not None and not proto._closed

    def on_ready(self, callback: Callable[[AsyncioRosBridgeProtocol], None]) -> None:
        """Register a callback to fire as soon as the connection is established.

        If the connection is already established, fires synchronously. Otherwise
        registers a one-shot listener for the next "ready" event. Protected by a
        lock so the TOCTOU race between checking ``_proto`` and registering the
        listener can't drop callbacks the way the autobahn variant occasionally
        did under reactor contention.
        """
        proto_to_fire: Optional[AsyncioRosBridgeProtocol] = None
        with self._proto_lock:
            if self._proto is not None:
                proto_to_fire = self._proto
            else:
                self.once("ready", callback)
        if proto_to_fire is not None:
            callback(proto_to_fire)

    def ready(self, proto: AsyncioRosBridgeProtocol) -> None:
        """Mark the connection as ready and notify any pending listeners."""
        with self._proto_lock:
            self._proto = proto
            self._retry_count = 0  # reset backoff on every successful connect
        self.emit("ready", proto)

    @classmethod
    def create_url(cls, host: str, port: Optional[int] = None, is_secure: bool = False) -> str:
        if port is None:
            return host
        scheme = "wss" if is_secure else "ws"
        return "{}://{}:{}/".format(scheme, host, port)

    @classmethod
    def set_max_delay(cls, max_delay: float) -> None:
        """Set the maximum reconnect backoff delay in seconds (3600 by default)."""
        cls.maxDelay = max_delay

    @classmethod
    def set_initial_delay(cls, initial_delay: float) -> None:
        """Set the initial reconnect backoff delay in seconds (1 by default)."""
        cls.initialDelay = initial_delay

    @classmethod
    def set_max_retries(cls, max_retries: Optional[int]) -> None:
        """Set the max reconnect attempts when the connection is lost (unbounded by default)."""
        cls.maxRetries = max_retries

    # ------------------------------------------------------------------
    # Supervisor coroutine: owns connect / reconnect with backoff
    # ------------------------------------------------------------------

    @property
    def manager(self) -> "AsyncioEventLoopManager":
        if self._manager is None:
            self._manager = _get_shared_manager()
        return self._manager

    async def _supervise_connection(self) -> None:
        """Maintain an open connection, reconnecting with exponential backoff
        if it drops unexpectedly.

        Stops when a manual disconnect is observed (``proto._manual_disconnect``
        set by ``send_close()``) or when ``maxRetries`` is exhausted.
        """
        import random

        ws_connect, ConnectionClosed, InvalidStatus = _import_websockets()
        delay = self.initialDelay

        while not self._stop_supervisor:
            try:
                LOGGER.debug("Connecting to %s...", self._url)
                async with ws_connect(
                    self._url,
                    additional_headers=self._headers,
                    open_timeout=None,  # we don't impose our own connect timeout here
                    close_timeout=5,
                ) as ws:
                    LOGGER.info("Connection to ROS ready.")
                    proto = AsyncioRosBridgeProtocol(self, ws)
                    self.ready(proto)
                    # Reset backoff on every successful connection.
                    delay = self.initialDelay
                    self._retry_count = 0
                    try:
                        await self._receive_loop(proto)
                    finally:
                        self._on_connection_closed(proto)
                        if proto._manual_disconnect:
                            LOGGER.debug("Manual disconnect — supervisor exiting.")
                            self._stop_supervisor = True
                            break
            except (ConnectionClosed, OSError, InvalidStatus) as exc:
                LOGGER.debug("Connection attempt failed: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error in connection supervisor.")

            if self._stop_supervisor:
                break

            self._retry_count += 1
            if self.maxRetries is not None and self._retry_count > self.maxRetries:
                LOGGER.warning("Exceeded max reconnect retries (%s); supervisor exiting.", self.maxRetries)
                break

            # Apply jittered exponential backoff, capped at maxDelay.
            jittered = delay + (random.random() * 2 - 1) * delay * self.jitter
            sleep_for = max(0.0, min(jittered, self.maxDelay))
            LOGGER.debug("Will retry connection in %.2fs (attempt %d).", sleep_for, self._retry_count)
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                raise
            delay = min(delay * self.factor, self.maxDelay)

    async def _receive_loop(self, proto: AsyncioRosBridgeProtocol) -> None:
        """Pump incoming WebSocket frames into the protocol's ``on_message``."""
        ws_connect, ConnectionClosed, InvalidStatus = _import_websockets()
        try:
            async for payload in proto.ws:
                if isinstance(payload, str):
                    payload = payload.encode("utf-8")
                try:
                    proto.on_message(payload)
                except Exception:
                    LOGGER.exception("Exception in user message handler; skipping frame.")
        except ConnectionClosed:
            LOGGER.info("WebSocket connection closed.")

    def _on_connection_closed(self, proto: AsyncioRosBridgeProtocol) -> None:
        proto._closed = True
        with self._proto_lock:
            self._proto = None
        # Notify listeners that the connection is gone. Matches the autobahn
        # factory's "close" emit out of clientConnectionLost; downstream code
        # (e.g. ``Ros.close()`` post-2.1 lifecycle work) uses this to know
        # the socket is actually torn down.
        try:
            self.emit("close", proto)
        except Exception:
            LOGGER.exception("Error in user 'close' listener.")


class AsyncioEventLoopManager(object):
    """Manage the asyncio event loop on a background thread.

    Mirrors :class:`TwistedEventLoopManager`'s surface so ``Ros`` doesn't need
    transport-specific branches. There is only ever one of these per process
    (held by ``_MANAGER_SINGLETON``), and the same loop is shared by every
    ``Ros`` instance using the asyncio transport.
    """

    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Spin up the background loop thread if it isn't running yet."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True, name="roslibpy-asyncio")
        self._thread.start()
        # Wait until the loop is actually running before returning so callers
        # can safely use call_soon_threadsafe immediately after.
        self._started.wait(timeout=5)

    def _run_thread(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._started.set()
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def run_forever(self) -> None:
        """Run the loop on the calling thread (rarely used; matches twisted's run_forever)."""
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        self._started.set()
        self.loop.run_forever()

    def terminate(self) -> None:
        """Stop the background loop and join the thread. After this, the
        manager is unusable in this process (matching twisted's one-shot
        ``reactor.stop()`` semantics — though asyncio could in principle
        be re-run, we keep parity).
        """
        if self.loop is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Scheduling primitives
    # ------------------------------------------------------------------

    def call_later(self, delay: float, callback: Callable[[], None]) -> None:
        """Run ``callback`` on the loop after ``delay`` seconds."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(loop.call_later, delay, callback)

    def call_in_thread(self, callback: Callable[[], None]) -> None:
        """Run ``callback`` on a worker thread (off the loop)."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(lambda: loop.run_in_executor(None, callback))

    def blocking_call_from_thread(self, callback: Callable[[Any], Any], timeout: Optional[float]) -> Any:
        """Run ``callback(result_placeholder)`` on the loop, block until result is set.

        ``callback`` is a function that accepts an ``asyncio.Future``; the
        callback is expected to register handlers that eventually resolve the
        future. We then block on a stdlib ``threading.Event`` set by a done-
        callback, so the caller doesn't have to know anything about asyncio.

        Mirrors ``TwistedEventLoopManager.blocking_call_from_thread``; the
        ``result_placeholder`` argument it passes to ``callback`` is an
        :class:`asyncio.Future` rather than a twisted ``Deferred``, but
        ``get_inner_callback`` / ``get_inner_errback`` keep the shape uniform
        for ``Ros`` consumers.
        """
        loop = self.loop
        if loop is None or loop.is_closed():
            raise RuntimeError("asyncio loop is not running")

        result_box: dict = {}
        done = threading.Event()

        def _on_loop() -> None:
            future = loop.create_future()

            def _on_future_done(fut: asyncio.Future) -> None:
                try:
                    result_box["result"] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    result_box["error"] = exc
                finally:
                    done.set()

            future.add_done_callback(_on_future_done)
            try:
                callback(future)
            except Exception as exc:  # noqa: BLE001
                result_box["error"] = exc
                done.set()

        loop.call_soon_threadsafe(_on_loop)
        if not done.wait(timeout=timeout if timeout else None):
            raise RosTimeoutError("No service response received")
        if "error" in result_box:
            raise result_box["error"]
        return result_box["result"]

    def get_inner_callback(self, result_placeholder: asyncio.Future) -> Callable[[Any], None]:
        """Return a callback that resolves ``result_placeholder`` with success."""

        def inner_callback(result: Any) -> None:
            if not result_placeholder.done():
                result_placeholder.set_result({"result": result})

        return inner_callback

    def get_inner_errback(self, result_placeholder: asyncio.Future) -> Callable[[Any], None]:
        """Return an errback that resolves ``result_placeholder`` with an error."""

        def inner_errback(error: Any) -> None:
            if not result_placeholder.done():
                result_placeholder.set_result({"exception": error})

        return inner_errback
