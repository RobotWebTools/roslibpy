from __future__ import print_function

import logging
import threading

from autobahn.twisted.websocket import (
    WebSocketClientFactory,
    WebSocketClientProtocol,
    connectWS,
)
from autobahn.websocket.util import create_url
from twisted.internet import defer, reactor, threads
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log

from ..core import RosTimeoutError
from ..event_emitter import EventEmitterMixin
from . import RosBridgeProtocol

LOGGER = logging.getLogger("roslibpy")


class AutobahnRosBridgeProtocol(RosBridgeProtocol, WebSocketClientProtocol):
    def __init__(self, *args, **kwargs):
        super(AutobahnRosBridgeProtocol, self).__init__(*args, **kwargs)

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

    def send_message(self, payload):
        return reactor.callFromThread(
            self.sendMessage, payload, isBinary=False, fragmentSize=None, sync=False, doNotCompress=False
        )

    def send_close(self):
        self._manual_disconnect = True
        reactor.callFromThread(self.sendClose)


class AutobahnRosBridgeClientFactory(EventEmitterMixin, ReconnectingClientFactory, WebSocketClientFactory):
    """Factory to create instances of the ROS Bridge protocol built on top of Autobahn/Twisted."""

    protocol = AutobahnRosBridgeProtocol

    def __init__(self, *args, **kwargs):
        super(AutobahnRosBridgeClientFactory, self).__init__(*args, **kwargs)
        self._proto = None
        self._manager = None
        self.connector = None
        self.setProtocolOptions(closeHandshakeTimeout=5)

    def connect(self):
        """Establish WebSocket connection to the ROS server defined for this factory."""
        self.connector = connectWS(self)

    @property
    def is_connected(self):
        """Indicate if the WebSocket connection is open or not.

        Returns:
            bool: True if WebSocket is connected, False otherwise.
        """
        return self.connector and self.connector.state == "connected"

    def on_ready(self, callback):
        if self._proto:
            callback(self._proto)
        else:
            self.once("ready", callback)

    def ready(self, proto):
        self.resetDelay()
        self._proto = proto
        self.emit("ready", proto)

    def startedConnecting(self, connector):
        LOGGER.debug("Started to connect...")

    def clientConnectionLost(self, connector, reason):
        LOGGER.debug("Lost connection. Reason: %s", reason)
        self.emit("close", self._proto)

        if not self._proto or (self._proto and not self._proto._manual_disconnect):
            ReconnectingClientFactory.clientConnectionLost(self, connector, reason)
        self._proto = None

    def clientConnectionFailed(self, connector, reason):
        LOGGER.debug("Connection failed. Reason: %s", reason)
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)
        self._proto = None

    @property
    def manager(self):
        """Get an instance of the event loop manager for this factory."""
        if not self._manager:
            self._manager = TwistedEventLoopManager()

        return self._manager

    @classmethod
    def create_url(cls, host, port=None, is_secure=False):
        url = host if port is None else create_url(host, port, is_secure)
        return url

    @classmethod
    def set_max_delay(cls, max_delay):
        """Set the maximum delay in seconds for reconnecting to rosbridge (3600 seconds by default).

        Args:
            max_delay: The new maximum delay, in seconds.
        """
        LOGGER.debug("Updating max delay to {} seconds".format(max_delay))
        # See https://twistedmatrix.com/documents/19.10.0/api/twisted.internet.protocol.ReconnectingClientFactory.html
        cls.maxDelay = max_delay

    @classmethod
    def set_initial_delay(cls, initial_delay):
        """Set the initial delay in seconds for reconnecting to rosbridge (1 second by default).

        Args:
            initial_delay: The new initial delay, in seconds.
        """
        LOGGER.debug("Updating initial delay to {} seconds".format(initial_delay))
        # See https://twistedmatrix.com/documents/19.10.0/api/twisted.internet.protocol.ReconnectingClientFactory.html
        cls.initialDelay = initial_delay

    @classmethod
    def set_max_retries(cls, max_retries):
        """Set the maximum number or connection retries when the rosbridge connection is lost (no limit by default).

        Args:
            max_retries: The new maximum number of retries.
        """
        LOGGER.debug("Updating max retries to {}".format(max_retries))
        # See https://twistedmatrix.com/documents/19.10.0/api/twisted.internet.protocol.ReconnectingClientFactory.html
        cls.maxRetries = max_retries


# The twisted reactor is a process-wide singleton, so the log observer that
# fans twisted's log events into the stdlib `logging` module is one too. Any
# Python process only ever needs one of these registered — registering more
# means every log event walks an O(n) observer list and ``globalLogPublisher``
# keeps strong references to every observer for the life of the process.
#
# Prior to 2.1, ``TwistedEventLoopManager.__init__`` started a fresh
# ``PythonLoggingObserver`` per instance, and downstream wrappers that call
# ``Ros.close()`` (rather than ``Ros.terminate()``, which stops the reactor
# permanently) never invoked ``manager.terminate()`` and so never stopped the
# observer. Long-running pytest sessions that create many ``Ros`` instances
# would accumulate one observer per ``Ros``, slowing every log emission
# linearly and contributing to occasional ``RosTimeoutError`` flakes on the
# next ``Ros.run()``.
_LOG_OBSERVER = None
_LOG_OBSERVER_LOCK = threading.Lock()


def _ensure_log_observer_started():
    """Lazily start the single process-wide twisted log → stdlib logging bridge."""
    global _LOG_OBSERVER
    if _LOG_OBSERVER is not None:
        return
    with _LOG_OBSERVER_LOCK:
        if _LOG_OBSERVER is not None:
            return
        observer = log.PythonLoggingObserver()
        observer.start()
        _LOG_OBSERVER = observer


class TwistedEventLoopManager(object):
    """Manage the main event loop using Twisted reactor.

    The event loop is a Twisted application is a very opinionated
    management strategy. Other communication layers use different
    event loop handlers that might be more fitting for different
    execution environments.
    """

    def __init__(self):
        # Twisted's reactor is a process singleton — so is the observer that
        # bridges twisted's log events into stdlib `logging`. See the module-
        # level comment for the lifecycle details.
        _ensure_log_observer_started()
        self._log_observer = _LOG_OBSERVER

    def run(self):
        """Kick-starts a non-blocking event loop.

        This implementation starts the Twisted Reactor
        on a separate thread to avoid blocking."""

        if reactor.running:
            return

        self._thread = threading.Thread(target=reactor.run, args=(False,))
        self._thread.daemon = True
        self._thread.start()

    def run_forever(self):
        """Kick-starts the main event loop of the ROS client.

        This implementation relies on Twisted Reactors
        to control the event loop."""
        reactor.run()

    def call_later(self, delay, callback):
        """Call the given function after a certain period of time has passed.

        Args:
            delay (:obj:`int`): Number of seconds to wait before invoking the callback.
            callback (:obj:`callable`): Callable function to be invoked when the delay has elapsed.
        """
        reactor.callFromThread(reactor.callLater, delay, callback)

    def call_in_thread(self, callback):
        """Call the given function on a thread.

        Args:
            callback (:obj:`callable`): Callable function to be invoked in a thread.
        """
        reactor.callFromThread(reactor.callInThread, callback)

    def blocking_call_from_thread(self, callback, timeout):
        """Call the given function from a thread, and wait for the result synchronously
        for as long as the timeout will allow.

        Args:
            callback: Callable function to be invoked from the thread.
            timeout (:obj:`int`): Number of seconds to wait for the response before
                raising an exception.

        Returns:
            The results from the callback, or a timeout exception.
        """
        result_placeholder = defer.Deferred()
        if timeout:
            result_placeholder.addTimeout(timeout, reactor, onTimeoutCancel=self.raise_timeout_exception)
        return threads.blockingCallFromThread(reactor, callback, result_placeholder)

    def raise_timeout_exception(self, _result=None, _timeout=None):
        """Callback called on timeout.

        Args:
            _result: Unused--required by Twister.
            _timeout: Unused--required by Twister.

        Raises:
            An exception.
        """
        raise RosTimeoutError("No service response received")

    def get_inner_callback(self, result_placeholder):
        """Get the callback which, when called, provides result_placeholder with the result.

        Args:
            result_placeholder: (:class:`Deferred`): Object in which to store the result.

        Returns:
            A callable which provides result_placeholder with the result in the case of success.
        """

        def inner_callback(result):
            result_placeholder.callback({"result": result})

        return inner_callback

    def get_inner_errback(self, result_placeholder):
        """Get the errback which, when called, provides result_placeholder with the error.

        Args:
            result_placeholder: (:class:`Deferred`): Object in which to store the result.

        Returns:
            A callable which provides result_placeholder with the error in the case of failure.
        """

        def inner_errback(error):
            result_placeholder.callback({"exception": error})

        return inner_errback

    def terminate(self):
        """Signals the termination of the main event loop."""
        if reactor.running:
            reactor.callFromThread(reactor.stop)

        if self._thread:
            self._thread.join()

        # The observer is the process-wide singleton (see module top). Stop
        # it once on terminate — the reactor cannot be restarted after stop,
        # so no future TwistedEventLoopManager will need the bridge in this
        # process. Subsequent terminates no-op.
        global _LOG_OBSERVER
        with _LOG_OBSERVER_LOCK:
            if _LOG_OBSERVER is not None:
                _LOG_OBSERVER.stop()
                _LOG_OBSERVER = None
        self._log_observer = None
