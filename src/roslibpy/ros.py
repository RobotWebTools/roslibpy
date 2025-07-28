from __future__ import print_function

import logging
import threading

from . import Message, Param, Service, ServiceRequest, Time
from .comm import RosBridgeClientFactory
from .core import RosTimeoutError

__all__ = ["Ros", "set_rosapi_timeout"]

LOGGER = logging.getLogger("roslibpy")
CONNECTION_TIMEOUT = 10
ROSAPI_TIMEOUT = 3


def set_rosapi_timeout(timeout):
    """Set the default number of seconds to wait for a response before
    raising an exception.

    Args:
         timeout (:obj:`int`): Duration in seconds.
    """
    global ROSAPI_TIMEOUT
    ROSAPI_TIMEOUT = timeout


class Ros(object):
    """Connection manager to ROS server.

    Args:
        host (:obj:`str`): Name or IP address of the ROS bridge host, e.g. ``127.0.0.1``.
        port (:obj:`int`): ROS bridge port, e.g. ``9090``.
        is_secure (:obj:`bool`): ``True`` to use a secure web sockets connection, otherwise ``False``.
        headers (:obj:`dict`): Additional headers to include in the WebSocket connection.
    """

    def __init__(self, host, port=None, is_secure=False, headers=None):
        self._id_counter = 0
        url = RosBridgeClientFactory.create_url(host, port, is_secure)
        self.factory = RosBridgeClientFactory(url, headers=headers)
        self.is_connecting = False
        self.connect()

    @property
    def id_counter(self):
        """Generate an auto-incremental ID starting from 1.

        Returns:
            int: An auto-incremented ID.
        """
        self._id_counter += 1
        return self._id_counter

    @property
    def is_connected(self):
        """Indicate if the ROS connection is open or not.

        Returns:
            bool: True if connected to ROS, False otherwise.
        """
        return self.factory.is_connected

    def connect(self):
        """Connect to ROS."""
        # Don't try to reconnect if already connected.
        if self.is_connected or self.is_connecting:
            return

        self.is_connecting = True

        def _unset_connecting_flag(*args):
            self.is_connecting = False

        self.factory.on_ready(_unset_connecting_flag)
        self.factory.connect()

    def close(self, timeout=CONNECTION_TIMEOUT):
        """Disconnect from ROS."""
        if self.is_connected:
            wait_disconnect = threading.Event()

            def _wrapper_callback(proto):
                self.emit("closing")
                proto.send_close()
                wait_disconnect.set()
                return proto

            self.factory.on_ready(_wrapper_callback)

            if not wait_disconnect.wait(timeout):
                raise RosTimeoutError("Failed to disconnect to ROS")

    def run(self, timeout=CONNECTION_TIMEOUT):
        """Kick-starts a non-blocking event loop.

        Args:
            timeout: Timeout to wait until connection is ready.
        """
        self.factory.manager.run()

        wait_connect = threading.Event()
        self.factory.on_ready(lambda _: wait_connect.set())

        if not wait_connect.wait(timeout):
            raise RosTimeoutError("Failed to connect to ROS")

    def run_forever(self):
        """Kick-starts a blocking loop to wait for events.

        Depending on the implementations, and the client applications,
        running this might be required or not.
        """
        self.factory.manager.run_forever()

    def run_event_loop(self):
        LOGGER.warn("Deprecation warning: use run_forever instead of run_event_loop ")
        self.run_forever()

    def call_in_thread(self, callback):
        """Call the given function in a thread.

        The threading implementation is deferred to the factory.

        Args:
            callback (:obj:`callable`): Callable function to be invoked.
        """
        self.factory.manager.call_in_thread(callback)

    def call_later(self, delay, callback):
        """Call the given function after a certain period of time has passed.

        Args:
            delay (:obj:`int`): Number of seconds to wait before invoking the callback.
            callback (:obj:`callable`): Callable function to be invoked when ROS connection is ready.
        """
        self.factory.manager.call_later(delay, callback)

    def terminate(self):
        """Signals the termination of the main event loop."""
        if self.is_connected:
            self.close()

        self.factory.manager.terminate()

    def on(self, event_name, callback):
        """Add a callback to an arbitrary named event.

        Args:
            event_name (:obj:`str`): Name of the event to which to subscribe.
            callback: Callable function to be executed when the event is triggered.
        """
        self.factory.on(event_name, callback)

    def off(self, event_name, callback=None):
        """Remove a callback from an arbitrary named event.

        Args:
            event_name (:obj:`str`): Name of the event from which to unsubscribe.
            callback: Callable function. If ``None``, all callbacks of the event
                will be removed.
        """
        if callback:
            self.factory.off(event_name, callback)
        else:
            self.factory.remove_all_listeners(event_name)

    def emit(self, event_name, *args):
        """Trigger a named event."""
        self.factory.emit(event_name, *args)

    def on_ready(self, callback, run_in_thread=True):
        """Add a callback to be executed when the connection is established.

        If a connection to ROS is already available, the callback is executed immediately.

        Args:
            callback: Callable function to be invoked when ROS connection is ready.
            run_in_thread (:obj:`bool`): True to run the callback in a separate thread, False otherwise.
        """

        def _wrapper_callback(proto):
            if run_in_thread:
                self.factory.manager.call_in_thread(callback)
            else:
                callback()

            return proto

        self.factory.on_ready(_wrapper_callback)

    def send_on_ready(self, message):
        """Send message to ROS once the connection is established.

        If a connection to ROS is already available, the message is sent immediately.

        Args:
            message (:class:`.Message`): ROS Bridge Message to send.
        """

        def _send_internal(proto):
            proto.send_ros_message(message)
            return proto

        self.factory.on_ready(_send_internal)

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
        return self.factory.manager.blocking_call_from_thread(callback, timeout)

    def get_service_request_callback(self, message):
        """Get the callback which, when called, sends the service request.

        Args:
            message (:class:`.Message`): ROS Bridge Message containing the request.

        Returns:
            A callable which makes the service request.
        """

        def get_call_results(result_placeholder):

            inner_callback = self.factory.manager.get_inner_callback(result_placeholder)

            inner_errback = self.factory.manager.get_inner_errback(result_placeholder)

            self.call_async_service(message, inner_callback, inner_errback)

            return result_placeholder

        return get_call_results

    def call_sync_service(self, message, timeout):
        """Send a blocking service request to ROS once the connection is established,
        waiting for the result to be return.

        If a connection to ROS is already available, the request is sent immediately.

        Args:
            message (:class:`.Message`): ROS Bridge Message containing the request.
            timeout (:obj:`int`): Number of seconds to wait for the response before
                raising an exception.
        Returns:
            Either returns the service request results or raises a timeout exception.
        """
        get_call_results = self.get_service_request_callback(message)
        return self.blocking_call_from_thread(get_call_results, timeout)

    def call_async_service(self, message, callback, errback):
        """Send a service request to ROS once the connection is established.

        If a connection to ROS is already available, the request is sent immediately.

        Args:
            message (:class:`.Message`): ROS Bridge Message containing the request.
            callback: Callback invoked on successful execution.
            errback: Callback invoked on error.
        """

        def _send_internal(proto):
            proto.send_ros_service_request(message, callback, errback)
            return proto

        self.factory.on_ready(_send_internal)

    def call_async_action(self, message, resultback, feedback, errback):
        """Send a action request to ROS once the connection is established.

        If a connection to ROS is already available, the request is sent immediately.

        Args:
            message (:class:`.Message`): ROS Bridge Message containing the request.
            resultback: Callback invoked on successful execution.
            feedback: Callback invoked on receiving action feedback.
            errback: Callback invoked on error.
        """

        def _send_internal(proto):
            proto.send_ros_action_goal(message, resultback, feedback, errback)
            return proto

        self.factory.on_ready(_send_internal)

    def set_status_level(self, level, identifier):
        level_message = Message({"op": "set_level", "level": level, "id": identifier})

        self.send_on_ready(level_message)

    def get_time(self, callback=None, errback=None):
        """Retrieve the current ROS time.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            :class:`.Time`: An instance of ROS Time.
        """
        service = Service(self, "/rosapi/get_time", "rosapi/GetTime")

        result = service.call(ServiceRequest(), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "time" in result
        return Time(result["time"]["secs"], result["time"]["nsecs"])

    def get_topics(self, callback=None, errback=None):
        """Retrieve list of topics in ROS.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            list: List of topics if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/topics", "rosapi/Topics")

        result = service.call(ServiceRequest(), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "topics" in result
        return result["topics"]

    def get_topic_type(self, topic, callback=None, errback=None):
        """Retrieve the type of a topic in ROS.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            str: Topic type if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/topic_type", "rosapi/TopicType")

        result = service.call(ServiceRequest({"topic": topic}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "type" in result
        return result["type"]

    def get_topics_for_type(self, topic_type, callback=None, errback=None):
        """Retrieve list of topics in ROS matching the specified type.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            list: List of topics matching the specified type if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/topics_for_type", "rosapi/TopicsForType")

        result = service.call(ServiceRequest({"type": topic_type}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "topics" in result
        return result["topics"]

    def get_services(self, callback=None, errback=None):
        """Retrieve list of active service names in ROS.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            list: List of services if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/services", "rosapi/Services")

        result = service.call(ServiceRequest(), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "services" in result
        return result["services"]

    def get_service_type(self, service_name, callback=None, errback=None):
        """Retrieve the type of a service in ROS.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            str: Service type if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/service_type", "rosapi/ServiceType")

        result = service.call(ServiceRequest({"service": service_name}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "type" in result
        return result["type"]

    def get_services_for_type(self, service_type, callback=None, errback=None):
        """Retrieve list of services in ROS matching the specified type.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            list: List of services matching the specified type if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/services_for_type", "rosapi/ServicesForType")

        result = service.call(ServiceRequest({"type": service_type}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "services" in result
        return result["services"]

    def get_service_request_details(self, type, callback=None, errback=None):
        """Retrieve details of a ROS Service Request.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            Service Request details if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/service_request_details", "rosapi/ServiceRequestDetails")

        result = service.call(ServiceRequest({"type": type}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        return result

    def get_service_response_details(self, type, callback=None, errback=None):
        """Retrieve details of a ROS Service Response.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            Service Response details if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/service_response_details", "rosapi/ServiceResponseDetails")

        result = service.call(ServiceRequest({"type": type}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        return result

    def get_message_details(self, message_type, callback=None, errback=None):
        """Retrieve details of a message type in ROS.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            Message type details if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/message_details", "rosapi/MessageDetails")

        result = service.call(ServiceRequest({"type": message_type}), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        return result

    def get_params(self, callback=None, errback=None):
        """Retrieve list of param names from the ROS Parameter Server.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            list: List of parameters if blocking, otherwise ``None``.
        """
        service = Service(self, "/rosapi/get_param_names", "rosapi/GetParamNames")

        result = service.call(ServiceRequest(), callback, errback, timeout=ROSAPI_TIMEOUT)

        if callback:
            return

        assert "names" in result
        return result["names"]

    def get_param(self, name, callback=None, errback=None):
        """Get the value of a parameter from the ROS Parameter Server.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .

        Returns:
            Parameter value if blocking, otherwise ``None``.
        """
        param = Param(self, name)
        return param.get(callback, errback, timeout=ROSAPI_TIMEOUT)

    def set_param(self, name, value, callback=None, errback=None):
        """Set the value of a parameter from the ROS Parameter Server.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .
        """
        param = Param(self, name)
        param.set(value, callback, errback, timeout=ROSAPI_TIMEOUT)

    def delete_param(self, name, callback=None, errback=None):
        """Delete parameter from the ROS Parameter Server.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .
        """
        param = Param(self, name)
        param.delete(callback, errback, timeout=ROSAPI_TIMEOUT)

    def get_action_servers(self, callback, errback=None):
        """Retrieve list of action servers in ROS."""
        service = Service(self, "/rosapi/action_servers", "rosapi/GetActionServers")

        service.call(ServiceRequest(), callback, errback)

    def get_nodes(self, callback=None, errback=None):
        """Retrieve list of active node names in ROS.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .
        """
        service = Service(self, "/rosapi/nodes", "rosapi/Nodes")

        result = service.call(ServiceRequest(), callback, errback)

        if callback:
            return

        assert "nodes" in result
        return result["nodes"]

    def get_node_details(self, node, callback=None, errback=None):
        """Retrieve list subscribed topics, publishing topics and services of a specific node name.

        Note:
            To make this a blocking call, pass ``None`` to the ``callback`` parameter .
        """
        service = Service(self, "/rosapi/node_details", "rosapi/NodeDetails")

        result = service.call(ServiceRequest({"node": node}), callback, errback)
        if callback:
            return

        output = {
            "services": result["services"],
            "subscribing": result["subscribing"],
            "publishing": result["publishing"],
        }

        return output

    def authenticate(self, mac, client, dest, rand, t, level, end):
        """Sends an authorization request to the server.

        Note:
            Sends authentication on connection.

        Args:
            mac (:obj:`str`): MAC (hash) string given by the trusted source.
            client (:obj:`str`): IP of the client.
            dest (:obj:`str`): IP of the destination.
            rand (:obj:`str`): Random string given by the trusted source.
            t (:obj:`float`): Time of the authorization request.
            level (:obj:`str`): User level as a string given by the client.
            end (:obj:`float`): End time of the client's session.
        """

        def _ready_callback(*args):
            self.send_on_ready(
                Message(
                    {
                        "op": "auth",
                        "mac": mac,
                        "client": client,
                        "dest": dest,
                        "rand": rand,
                        "t": t,
                        "level": level,
                        "end": end,
                    }
                )
            )

        self.on("ready", _ready_callback)


if __name__ == "__main__":
    FORMAT = "%(asctime)-15s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=FORMAT)

    ros_client = Ros("127.0.0.1", 9090)

    ros_client.on_ready(lambda: ros_client.get_topics(print))
    ros_client.call_later(3, ros_client.close)
    ros_client.call_later(5, ros_client.terminate)

    ros_client.run_forever()
