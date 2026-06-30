"""Asyncio-based transport for roslibpy.

Opt-in alternative to the default Twisted-based transport. Selected via:

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

This transport reuses the very same Autobahn WebSocket stack as the default
transport; the only difference is that it runs on an asyncio event loop
(``autobahn.asyncio``) rather than the Twisted reactor. No extra dependencies
are required beyond Autobahn, which roslibpy already depends on.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
from typing import Any, Callable, Optional

from autobahn.asyncio.websocket import WebSocketClientFactory, WebSocketClientProtocol
from autobahn.websocket.compress import (
    PerMessageDeflateOffer,
    PerMessageDeflateResponse,
    PerMessageDeflateResponseAccept,
)
from autobahn.websocket.util import create_url

from ..core import RosTimeoutError
from ..event_emitter import EventEmitterMixin
from . import RosBridgeProtocol

LOGGER = logging.getLogger("roslibpy")

# Defaults matched to ReconnectingClientFactory's behaviour so users moving
# between transports see the same retry cadence. Autobahn's asyncio integration
# does not ship a reconnecting factory (unlike the Twisted side), so this
# transport reimplements the same exponential backoff.
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
        if _MANAGER_SINGLETON is None:
            _MANAGER_SINGLETON = AsyncioEventLoopManager()
        return _MANAGER_SINGLETON


class AsyncioRosBridgeProtocol(RosBridgeProtocol, WebSocketClientProtocol):
    """ROS Bridge protocol over an Autobahn asyncio WebSocket connection.

    Mirrors :class:`AutobahnRosBridgeProtocol` almost exactly — the protocol
    callbacks (``onConnect`` / ``onOpen`` / ``onMessage`` / ``onClose``) are
    identical. The only difference is that ``send_message`` / ``send_close``
    schedule the IO onto the background asyncio loop (via
    ``call_soon_threadsafe``) instead of the Twisted reactor.
    """

    def __init__(self, *args, **kwargs):
        super(AsyncioRosBridgeProtocol, self).__init__(*args, **kwargs)
        self._manual_disconnect = False

    def onConnect(self, response):
        LOGGER.debug("Server connected: %s", response.peer)

    def onOpen(self):
        LOGGER.info("Connection to ROS ready.")
        self._manual_disconnect = False
        self.factory.ready(self)

    def onMessage(self, payload, isBinary):
        if isBinary:
            raise NotImplementedError("Add support for binary messages")

        try:
            self.on_message(payload)
        except Exception:
            LOGGER.exception(
                "Exception on start_listening while trying to handle message received."
                + "It could indicate a bug in user code on message handlers. Message skipped."
            )

    def onClose(self, wasClean, code, reason):
        LOGGER.info("WebSocket connection closed: Code=%s, Reason=%s", str(code), reason)
        # Notify the factory so it can clear its protocol reference and, unless
        # this was a manual disconnect, schedule a reconnect attempt.
        if self.factory is not None:
            self.factory.connection_lost(self)

    def send_message(self, payload):
        """Send an already-encoded ROS bridge message frame.

        Safe to call from any thread; the actual send is scheduled onto the
        background loop.
        """
        loop = self.factory.manager.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._send, payload)

    def _send(self, payload):
        try:
            # ROS bridge frames are JSON text; send them as (non-binary) text
            # frames, matching the autobahn/twisted transport.
            self.sendMessage(payload, isBinary=False)
        except Exception:
            LOGGER.exception("Failed to send ROS bridge frame; connection likely dropped.")

    def send_close(self):
        """Initiate a clean WebSocket close.

        Sets the manual-disconnect flag so the factory's reconnect logic knows
        to stand down, then asks the loop to close the socket.
        """
        self._manual_disconnect = True
        loop = self.factory.manager.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self.sendClose)


class AsyncioRosBridgeClientFactory(EventEmitterMixin, WebSocketClientFactory):
    """ROS Bridge client factory built on Autobahn's asyncio integration.

    Mirrors the public surface of :class:`AutobahnRosBridgeClientFactory` so
    that callers (``Ros`` and friends) don't care which transport is selected.
    Because the asyncio side of Autobahn has no ``ReconnectingClientFactory``
    equivalent, this factory implements its own exponential-backoff reconnect.
    """

    protocol = AsyncioRosBridgeProtocol

    # Class-level reconnect tuning, kept as class attributes so the
    # `set_initial_delay` / `set_max_delay` / `set_max_retries` classmethods
    # behave like their autobahn/twisted counterparts.
    initialDelay = DEFAULT_INITIAL_RECONNECT_DELAY
    maxDelay = DEFAULT_MAX_RECONNECT_DELAY
    factor = DEFAULT_RECONNECT_FACTOR
    jitter = DEFAULT_RECONNECT_JITTER
    maxRetries = DEFAULT_MAX_RECONNECT_RETRIES
    compression = "deflate"

    def __init__(self, *args, **kwargs):
        # Autobahn's asyncio factory binds to an event loop at construction
        # time, so make sure our background loop is up and hand it over.
        self._manager = _get_shared_manager()
        self._manager.run()
        kwargs.setdefault("loop", self._manager.loop)

        super(AsyncioRosBridgeClientFactory, self).__init__(*args, **kwargs)

        self._proto: Optional[AsyncioRosBridgeProtocol] = None
        # Lock guarding `_proto` reads/writes in on_ready / ready. Closes the
        # TOCTOU race between checking ``_proto`` and registering a one-shot
        # "ready" listener.
        self._proto_lock = threading.Lock()
        # Reconnect bookkeeping, mutated only from the loop thread.
        self._stop = False
        self._retry_count = 0
        self._reconnect_delay = self.initialDelay

        self.setProtocolOptions(closeHandshakeTimeout=5)
        self._configure_compression()

    # ------------------------------------------------------------------
    # Public surface mirroring AutobahnRosBridgeClientFactory
    # ------------------------------------------------------------------

    def connect(self):
        """Schedule the initial WebSocket connection on the background loop."""
        self._stop = False
        self._retry_count = 0
        self._reconnect_delay = self.initialDelay

        manager = self.manager
        manager.run()  # ensure background loop is up
        loop = manager.loop
        assert loop is not None
        loop.call_soon_threadsafe(self._open_connection)

    @property
    def is_connected(self):
        """Indicate if the WebSocket connection is open or not.

        Returns:
            bool: True if WebSocket is connected, False otherwise.
        """
        proto = self._proto
        return proto is not None and not proto._manual_disconnect

    def on_ready(self, callback):
        """Register a callback to fire as soon as the connection is established.

        If the connection is already established, fires synchronously. Otherwise
        registers a one-shot listener for the next "ready" event.
        """
        proto_to_fire: Optional[AsyncioRosBridgeProtocol] = None
        with self._proto_lock:
            if self._proto is not None:
                proto_to_fire = self._proto
            else:
                self.once("ready", callback)
        if proto_to_fire is not None:
            callback(proto_to_fire)

    def ready(self, proto):
        """Mark the connection as ready and notify any pending listeners."""
        with self._proto_lock:
            self._proto = proto
        # Reset backoff on every successful connect.
        self._retry_count = 0
        self._reconnect_delay = self.initialDelay
        self.emit("ready", proto)

    def connection_lost(self, proto):
        """Handle a dropped connection (called from the protocol's ``onClose``).

        Clears the protocol reference, emits ``close`` (mirroring the autobahn
        factory's ``clientConnectionLost`` emit), and unless the disconnect was
        manual, schedules a reconnect with exponential backoff.
        """
        with self._proto_lock:
            self._proto = None
        try:
            self.emit("close", proto)
        except Exception:
            LOGGER.exception("Error in user 'close' listener.")

        if proto._manual_disconnect or self._stop:
            self._stop = True
            return
        self._schedule_reconnect()

    @classmethod
    def create_url(cls, host, port=None, is_secure=False):
        url = host if port is None else create_url(host, port, is_secure)
        return url

    @classmethod
    def set_max_delay(cls, max_delay):
        """Set the maximum reconnect backoff delay in seconds (3600 by default)."""
        LOGGER.debug("Updating max delay to {} seconds".format(max_delay))
        cls.maxDelay = max_delay

    @classmethod
    def set_initial_delay(cls, initial_delay):
        """Set the initial reconnect backoff delay in seconds (1 by default)."""
        LOGGER.debug("Updating initial delay to {} seconds".format(initial_delay))
        cls.initialDelay = initial_delay

    @classmethod
    def set_max_retries(cls, max_retries):
        """Set the max reconnect attempts when the connection is lost (unbounded by default)."""
        LOGGER.debug("Updating max retries to {}".format(max_retries))
        cls.maxRetries = max_retries

    @property
    def manager(self) -> "AsyncioEventLoopManager":
        """Get an instance of the event loop manager for this factory."""
        if self._manager is None:
            self._manager = _get_shared_manager()
        return self._manager

    # ------------------------------------------------------------------
    # Connect / reconnect machinery (runs on the loop thread)
    # ------------------------------------------------------------------

    def _configure_compression(self):
        """Enable per-message deflate negotiation unless compression is disabled."""
        if not self.compression or self.compression == "none":
            return

        offers = [PerMessageDeflateOffer()]
        self.setProtocolOptions(perMessageCompressionOffers=offers)

        def accept(response):
            if isinstance(response, PerMessageDeflateResponse):
                return PerMessageDeflateResponseAccept(response)

        self.setProtocolOptions(perMessageCompressionAccept=accept)

    def _open_connection(self):
        # Scheduled onto the loop thread, where there is a running loop.
        asyncio.ensure_future(self._connect_async())

    async def _connect_async(self):
        loop = self.manager.loop
        if loop is None or loop.is_closed():
            return

        ssl = None
        if self.isSecure:
            import ssl as ssl_module

            ssl = ssl_module.create_default_context()

        try:
            LOGGER.debug("Connecting to %s...", self.url)
            # The factory itself is the (callable) protocol factory expected by
            # ``create_connection``; autobahn drives the WebSocket handshake
            # from the protocol's ``connection_made``.
            await loop.create_connection(self, self.host, self.port, ssl=ssl)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — any connect error triggers a retry
            LOGGER.debug("Connection attempt failed: %s", exc)
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        """Schedule the next reconnect attempt with jittered exponential backoff.

        Always invoked from the loop thread, so it can use ``call_later``
        directly rather than ``call_soon_threadsafe``.
        """
        if self._stop:
            return

        self._retry_count += 1
        if self.maxRetries is not None and self._retry_count > self.maxRetries:
            LOGGER.warning("Exceeded max reconnect retries (%s); giving up.", self.maxRetries)
            return

        delay = self._reconnect_delay
        jittered = delay + (random.random() * 2 - 1) * delay * self.jitter
        sleep_for = max(0.0, min(jittered, self.maxDelay))
        # Advance the backoff for the following attempt.
        self._reconnect_delay = min(delay * self.factor, self.maxDelay)

        LOGGER.debug("Will retry connection in %.2fs (attempt %d).", sleep_for, self._retry_count)
        loop = self.manager.loop
        if loop is None or loop.is_closed():
            return
        loop.call_later(sleep_for, self._open_connection)


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
