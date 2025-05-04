from __future__ import print_function

import logging
import math

from System import Action, Array, ArraySegment, Byte, TimeSpan, Uri, UriBuilder
from System.Net.WebSockets import (
    ClientWebSocket,
    WebSocketCloseStatus,
    WebSocketError,
    WebSocketMessageType,
    WebSocketReceiveResult,
    WebSocketState,
)
from System.Text import Encoding
from System.Threading import (
    CancellationToken,
    CancellationTokenSource,
    ManualResetEventSlim,
    SemaphoreSlim,
    Thread,
    ThreadPool,
    WaitCallback,
)
from System.Threading.Tasks import Task

from ..core import RosTimeoutError
from ..event_emitter import EventEmitterMixin
from . import RosBridgeException, RosBridgeProtocol

LOGGER = logging.getLogger('roslibpy')
RECEIVE_CHUNK_SIZE = 1024
SEND_CHUNK_SIZE = 1024


def _unwrap_exception(task):
    exception = task.Exception
    if exception.InnerException:
        exception = exception.InnerException

    if hasattr(exception, 'WebSocketErrorCode'):
        return (exception.WebSocketErrorCode, exception.Message)

    return (None, exception.Message)


class CliRosBridgeProtocol(RosBridgeProtocol):
    """Implements the ROS Bridge protocol on top of CLI WebSockets.

    This implementation is mainly intended to be used on IronPython
    implementations and makes use of the Tasks library of .NET for
    most internal scheduling and cancellation signals."""
    def __init__(self, factory, socket, *args, **kwargs):
        super(CliRosBridgeProtocol, self).__init__(*args, **kwargs)
        self.factory = factory
        self.socket = socket
        # According to docs, exactly one send and one receive is supported on each ClientWebSocket object in parallel.
        # https://msdn.microsoft.com/en-us/library/system.net.websockets.clientwebsocket.receiveasync(v=vs.110).aspx
        # So we configure the semaphore to allow for 2 concurrent requests
        # User-code might still end up in a race if multiple requests are triggered from different threads
        self.semaphore = SemaphoreSlim(2)

    def on_open(self, task):
        """Triggered when the socket connection has been established.

        This will kick-start the listening thread."""
        if task.IsFaulted:
            err_code, err_desc = _unwrap_exception(task)
            self.factory.client_connection_failed(self, err_code, err_desc)
            return

        LOGGER.info('Connection to ROS ready.')
        self.factory.manual_disconnect = False
        self.factory.ready(self)
        self.factory.manager.call_in_thread(self.start_listening)

    def receive_chunk_async(self, task, context):
        """Handle the reception of a message chuck asynchronously."""
        try:
            if task:

                if task.IsFaulted:
                    err_code, err_desc = _unwrap_exception(task)
                    self.factory.client_connection_lost(self, err_code, err_desc)
                    return

                result = task.Result

                if result.MessageType == WebSocketMessageType.Close:
                    LOGGER.info('WebSocket connection closed: [Code=%s] Description=%s',
                                result.CloseStatus, result.CloseStatusDescription)

                    try:
                        # Socket might be already disposed or nullified
                        if not self.socket:
                            return

                        # If not, we try to be good citizens and finalize the close handshake
                        return self.socket.CloseOutputAsync(result.CloseStatus,
                                                            result.CloseStatusDescription,
                                                            CancellationToken.None)  # noqa: E999 (disable flake8 error, which incorrectly parses None as the python keyword)
                    except:  # noqa: E722
                        # But it could also fail (eg. the socket was just disposed) we just warn and return then
                        LOGGER.warn('Unable to send close output. Socket might be already disposed.')
                        return
                else:
                    chunk = Encoding.UTF8.GetString(context['buffer'], 0, result.Count)
                    context['content'].append(chunk)

                    # Signal the listener thread if we're done parsing chunks
                    if result.EndOfMessage:
                        # NOTE: Once we reach the end of the message
                        # we release the lock (Semaphore)
                        self.semaphore.Release()

                        # And signal the manual reset event
                        context['mre'].Set()
                        return task

            # NOTE: We will enter the lock (Semaphore) at the start of receive
            # to make sure we're accessing the socket read/writes at most from
            # two threads, one for receiving and one for sending
            if not task:
                self.semaphore.Wait(self.factory.manager.cancellation_token)

            receive_task = self.socket.ReceiveAsync(ArraySegment[Byte](
                context['buffer']), self.factory.manager.cancellation_token)
            receive_task.ContinueWith.Overloads[Action[Task[WebSocketReceiveResult], object], object](
                self.receive_chunk_async, context)
        except Exception as exception:
            error_message = 'Exception on receive_chunk_async, processing will be aborted'
            if task:
                error_message += '; Task status: {}, Inner exception: {}'.format(task.Status, task.Exception)
            LOGGER.exception(error_message)
            raise RosBridgeException(error_message, exception)

    def start_listening(self):
        """Starts listening asynchronously while the socket is open.

        The inter-thread synchronization between this and the async
        reception threads is sync'd with a manual reset event."""
        try:
            LOGGER.debug(
                'About to start listening, socket state: %s', self.socket.State)

            while self.socket and self.socket.State == WebSocketState.Open:
                mre = ManualResetEventSlim(False)
                content = []
                buffer = Array.CreateInstance(Byte, RECEIVE_CHUNK_SIZE)

                self.receive_chunk_async(None, dict(
                    buffer=buffer, content=content, mre=mre))

                LOGGER.debug('Waiting for messages...')
                try:
                    mre.Wait(self.factory.manager.cancellation_token)
                except SystemError:
                    LOGGER.debug('Cancellation detected on listening thread, exiting...')
                    break

                try:
                    message_payload = ''.join(content)
                    LOGGER.debug('Message reception completed|<pre>%s</pre>', message_payload)
                    self.on_message(message_payload)
                except Exception:
                    LOGGER.exception('Exception on start_listening while trying to handle message received.' +
                                     'It could indicate a bug in user code on message handlers. Message skipped.')
        except Exception as exception:
            error_message = 'Exception on start_listening, processing will be aborted'
            LOGGER.exception(error_message)
            raise RosBridgeException(error_message, exception)
        finally:
            LOGGER.debug('Leaving the listening thread')

    def send_close(self):
        """Trigger the closure of the websocket indicating normal closing process."""
        self.factory.manual_disconnect = True

        err_desc = ''
        err_code = WebSocketCloseStatus.NormalClosure

        if self.socket:
            close_task = self.socket.CloseAsync(err_code,
                                                err_desc,
                                                CancellationToken.None)  # noqa: E999 (disable flake8 error, which incorrectly parses None as the python keyword)
        else:
            close_task = None

        self.factory.client_connection_lost(self, err_code, err_desc)

        return close_task

    def send_chunk_async(self, task, message_data):
        """Send a message chuck asynchronously."""
        try:
            if not task:
                self.semaphore.Wait(self.factory.manager.cancellation_token)

            message_buffer, message_length, chunks_count, i = message_data

            offset = SEND_CHUNK_SIZE * i
            is_last_message = (i == chunks_count - 1)

            if is_last_message:
                count = message_length - offset
            else:
                count = SEND_CHUNK_SIZE

            message_chunk = ArraySegment[Byte](message_buffer, offset, count)
            LOGGER.debug('Chunk %d of %d|From offset=%d, byte count=%d, Is last=%s',
                         i + 1, chunks_count, offset, count, str(is_last_message))
            task = self.socket.SendAsync(
                message_chunk, WebSocketMessageType.Text, is_last_message, self.factory.manager.cancellation_token)

            if not is_last_message:
                task.ContinueWith(self.send_chunk_async, [
                    message_buffer, message_length, chunks_count, i + 1])
            else:
                # NOTE: If we've reached the last chunk of the message
                # we can release the lock (Semaphore) again.
                task.ContinueWith(lambda _res: self.semaphore.Release())

            return task
        except Exception as exception:
            error_message = 'Exception while on send_chunk_async'
            LOGGER.exception(error_message)
            raise RosBridgeException(error_message, exception)

    def send_message(self, payload):
        """Start sending a message over the websocket asynchronously."""

        if self.socket.State != WebSocketState.Open:
            raise RosBridgeException(
                'Connection is not open. Socket state: %s' % self.socket.State)

        try:
            message_buffer = Encoding.UTF8.GetBytes(payload)
            message_length = len(message_buffer)
            chunks_count = int(math.ceil(float(message_length) / SEND_CHUNK_SIZE))

            send_task = self.send_chunk_async(
                None, [message_buffer, message_length, chunks_count, 0])

            return send_task
        except Exception as exception:
            error_message = 'Exception while sending message'
            LOGGER.exception(error_message)
            raise RosBridgeException(error_message, exception)

    def dispose(self, *args):
        """Dispose the resources held by this protocol instance, i.e. socket."""
        if self.socket:
            self.socket.Dispose()
            self.socket = None
            LOGGER.debug('Websocket disposed')

    def __del__(self):
        """Dispose correctly the connection."""
        self.dispose()


class CliRosBridgeClientFactory(EventEmitterMixin):
    """Factory to create instances of the ROS Bridge protocol built on top of .NET WebSockets."""

    max_delay = 3600.0
    initial_delay = 1.0
    max_retries = None

    # NOTE: The following factor was taken from Twisted's reconnecting factory:
    # https://github.com/twisted/twisted/blob/6ac66416c0238f403a8dc1d42924fb3ba2a2a686/src/twisted/internet/protocol.py#L369
    factor = 2.7182818284590451  # (math.e)

    def __init__(self, url, *args, **kwargs):
        super(CliRosBridgeClientFactory, self).__init__()
        self._manager = CliEventLoopManager()
        self.manual_disconnect = False
        self.proto = None
        self.url = url
        self.delay = self.initial_delay
        self.retries = 0

    @property
    def is_connected(self):
        """Indicate if the WebSocket connection is open or not.

        Returns:
            bool: True if WebSocket is connected, False otherwise.
        """
        if self.proto and self.proto.socket:
            return self.proto.socket.State == WebSocketState.Open

        return False

    def connect(self):
        """Establish WebSocket connection to the ROS server defined for this factory.

        Returns:
            async_task: The async task for the connection.
        """
        LOGGER.debug('Started to connect...')
        socket = ClientWebSocket()
        connect_task = socket.ConnectAsync(
            self.url, self.manager.cancellation_token)

        protocol = CliRosBridgeProtocol(self, socket)
        connect_task.ContinueWith(protocol.on_open)

        return connect_task

    def reset_delay(self):
        """
        Call this method after a successful connection to reset the delay.
        """
        self.delay = self.initial_delay

    def _reconnect_if_needed(self):
        if self.manual_disconnect:
            return

        if self.max_retries is not None and (self.retries >= self.max_retries):
            LOGGER.info("Abandoning after {} retries".format(self.retries))
            return

        self.retries += 1
        self.delay = min(self.delay * self.factor, self.max_delay)
        LOGGER.info("Connection manager will retry in {} seconds".format(int(self.delay)))

        self.manager.call_later(self.delay, self.connect)

    def client_connection_lost(self, connector, reason_code, reason_description):
        LOGGER.debug('Lost connection. Code: %s, Reason: %s', reason_code, reason_description)
        self.emit('close', self.proto)
        self._reconnect_if_needed()

        if self.proto:
            self.proto.dispose()
            self.proto = None

    def client_connection_failed(self, connector, reason_code, reason_description):
        LOGGER.debug('Connection failed. Reason: %s', reason_description)
        self._reconnect_if_needed()

        if self.proto:
            self.proto.dispose()
            self.proto = None

    def ready(self, proto):
        self.proto = proto
        self.reset_delay()
        self.emit('ready', proto)

    def on_ready(self, callback):
        if self.proto:
            callback(self.proto)
        else:
            self.once('ready', callback)

    @property
    def manager(self):
        """Get an instance of the event loop manager for this factory."""
        return self._manager

    @classmethod
    def create_url(cls, host, port=None, is_secure=False):
        if port is None:
            return Uri(host)
        else:
            scheme = 'wss' if is_secure else 'ws'
            builder = UriBuilder(scheme, host, port)
            return builder.Uri

    @classmethod
    def set_max_delay(cls, max_delay):
        """Set the maximum delay in seconds for reconnecting to rosbridge (3600 seconds by default).

        Args:
            max_delay: The new maximum delay, in seconds.
        """
        LOGGER.debug('Updating max delay to {} seconds'.format(max_delay))
        cls.max_delay = max_delay

    @classmethod
    def set_initial_delay(cls, initial_delay):
        """Set the initial delay in seconds for reconnecting to rosbridge (1 second by default).

        Args:
            initial_delay: The new initial delay, in seconds.
        """
        LOGGER.debug('Updating initial delay to {} seconds'.format(max_delay))
        cls.initial_delay = initial_delay

    @classmethod
    def set_max_retries(cls, max_retries):
        """Set the maximum number or connection retries when the rosbridge connection is lost (no limit by default).

        Args:
            max_retries: The new maximum number of retries.
        """
        LOGGER.debug('Updating max retries to {}'.format(max_retries))
        cls.max_retries = max_retries


class CliEventLoopManager(object):
    """Manage the main event loop using .NET threads.

    For the time being, this implementation is pretty light
    and mostly relies on .NET async doing "the right thing(tm)"
    with a sprinkle of threading here and there.
    """

    def __init__(self):
        self._init_cancellation()
        self._disconnect_event = ManualResetEventSlim(False)

    def _init_cancellation(self):
        """Initialize the cancellation source and token."""
        self.cancellation_token_source = CancellationTokenSource()
        self.cancellation_token = self.cancellation_token_source.Token
        self.cancellation_token.Register(lambda: LOGGER.debug('Started token cancellation'))

    def run(self):
        """Kick-starts a non-blocking event loop.

        In this implementation, this is a no-op."""
        pass

    def run_forever(self):
        """Kick-starts a blocking loop while the ROS client is connected."""
        self._disconnect_event.Wait(self.cancellation_token)
        LOGGER.debug('Received disconnect event on main loop')

    def call_later(self, delay, callback):
        """Call the given function after a certain period of time has passed.

        Args:
            delay (:obj:`int`): Number of seconds to wait before invoking the callback.
            callback (:obj:`callable`): Callable function to be invoked when the delay has elapsed.
        """
        # NOTE: Maybe there's a more elegant way of doing this
        def closure():
            Thread.Sleep(delay * 1000)
            callback()

        Task.Factory.StartNew(closure, self.cancellation_token)

    def call_in_thread(self, callback):
        """Call the given function on a thread.

        Args:
            callback (:obj:`callable`): Callable function to be invoked in a thread.
        """
        Task.Factory.StartNew(callback, self.cancellation_token)

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
        manual_event = ManualResetEventSlim(False)
        result_placeholder = {'manual_event': manual_event}
        ThreadPool.QueueUserWorkItem(WaitCallback(callback), result_placeholder)

        # Wait with timeout results bool indicating success/failure
        if timeout and manual_event.Wait(timeout * 1000, self.cancellation_token):
            return result_placeholder

        # Wait without timeouts raises in case of failure triggered by cancellation
        if not timeout:
            manual_event.Wait(self.cancellation_token)
            return result_placeholder

        self.raise_timeout_exception()

    def raise_timeout_exception(self, _result=None, _timeout=None):
        """Callback called on timeout.

        Args:
            _result: Unused--required by Twister.
            _timeout: Unused--required by Twister.

        Raises:
            An exception.
        """
        raise RosTimeoutError('No service response received')

    def get_inner_callback(self, result_placeholder):
        """Get the callback which, when called, provides result_placeholder with the result.

        Args:
            result_placeholder: (:obj:`dict`): Object in which to store the result.

        Returns:
            A callable which provides result_placeholder with the result in the case of success.
        """
        def inner_callback(result):
            result_placeholder['result'] = result
            result_placeholder['manual_event'].Set()
        return inner_callback

    def get_inner_errback(self, result_placeholder):
        """Get the errback which, when called, provides result_placeholder with the error.

        Args:
            result_placeholder: (:obj:`dict`): Object in which to store the result.

        Returns:
            A callable which provides result_placeholder with the error in the case of failure.
        """
        def inner_errback(error):
            result_placeholder['exception'] = error
            result_placeholder['manual_event'].Set()
        return inner_errback

    def terminate(self):
        """Signals the termination of the main event loop."""
        self._disconnect_event.Set()

        if self.cancellation_token_source:
            self.cancellation_token_source.Cancel()

        # Renew to allow re-connects
        self._init_cancellation()
