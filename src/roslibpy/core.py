from __future__ import print_function

import json
import logging
import threading
import time
from enum import Enum

# Python 2/3 compatibility import list
try:
    from collections import UserDict
except ImportError:
    from UserDict import UserDict

LOGGER = logging.getLogger("roslibpy")

__all__ = [
    "Header",
    "Message",
    "Param",
    "RosTimeoutError",
    "Service",
    "ServiceRequest",
    "ServiceResponse",
    "Goal",
    "GoalStatus",
    "Feedback",
    "Result",
    "Time",
    "Topic",
]


try:

    class RosTimeoutError(TimeoutError):
        pass

except NameError:

    class RosTimeoutError(Exception):
        pass


class Message(UserDict):
    """Message objects used for publishing and subscribing to/from topics.

    A message is fundamentally a dictionary and behaves as one."""

    def __init__(self, values=None):
        self.data = {}
        if values is not None:
            self.update(values)


class Header(UserDict):
    """Represents a message header of the ROS type std_msgs/Header.

    This header is only compatible with ROS 1. For ROS 2 headers, use :class:`roslibpy.ros2.Header`.

    """

    def __init__(self, seq=None, stamp=None, frame_id=None):
        self.data = {}
        self.data["seq"] = seq
        self.data["stamp"] = Time(stamp["secs"], stamp["nsecs"]) if stamp else None
        self.data["frame_id"] = frame_id


class Time(UserDict):
    """Represents ROS time with two integers: seconds since epoch and nanoseconds since seconds."""

    def __init__(self, secs, nsecs):
        self.data = {}
        self.data["secs"] = self._ensure_int(secs)
        self.data["nsecs"] = self._ensure_int(nsecs)

    def _ensure_int(self, n):
        if isinstance(n, int):
            return n
        if isinstance(n, float) and n.is_integer():
            return int(n)
        raise ValueError("argument must be an integer")

    @property
    def secs(self):
        """Seconds since epoch."""
        return self.data["secs"]

    @property
    def nsecs(self):
        """Nanoseconds since seconds."""
        return self.data["nsecs"]

    def is_zero(self):
        """Return ``True`` if zero (secs and nsecs) otherwise ``False``."""
        return self.data["secs"] == 0 and self.data["nsecs"] == 0

    def to_nsec(self):
        """Return time as nanoseconds from epoch."""
        stamp_secs = self.data["secs"]
        stamp_nsecs = self.data["nsecs"]
        return stamp_secs * int(1e9) + stamp_nsecs

    def to_sec(self):
        """Return time as float seconds representation (same as ``time.time()``)."""
        return float(self.data["secs"]) + float(self.data["nsecs"]) / int(1e9)

    @staticmethod
    def from_sec(float_secs):
        """Create new Time instance from a float seconds representation (e.g. ``time.time()``)."""
        secs = int(float_secs)
        nsecs = int((float_secs - secs) * int(1e9))
        return Time(secs, nsecs)

    @staticmethod
    def now():
        """Create new Time instance from the current system time (not ROS time)."""
        return Time.from_sec(time.time())


class ServiceRequest(UserDict):
    """Request for a service call."""

    def __init__(self, values=None):
        self.data = {}
        if values is not None:
            self.update(values)


class ServiceResponse(UserDict):
    """Response returned from a service call."""

    def __init__(self, values=None):
        self.data = {}
        if values is not None:
            self.update(values)


class Result(UserDict):
    """Result returned from an action call."""

    def __init__(self, values=None):
        self.data = {}
        if values is not None:
            self.update(values)


class Feedback(UserDict):
    """Feedback returned from an action call."""

    def __init__(self, values=None):
        self.data = {}
        if values is not None:
            self.update(values)


class GoalStatus(Enum):
    """ ROS 2 goal statuses.
        Reference: https://docs.ros2.org/latest/api/action_msgs/msg/GoalStatus.html
    """

    UNKNOWN = 0
    ACCEPTED = 1
    EXECUTING = 2
    CANCELING = 3
    SUCCEEDED = 4
    CANCELED = 5
    ABORTED = 6


class Goal(UserDict):
    """Goal for an action call."""

    def __init__(self, values=None):
        self.data = {}
        if values is not None:
            self.update(values)


class MessageEncoder(json.JSONEncoder):
    """Internal class to serialize some of the core data types into json."""

    def default(self, o):
        if isinstance(o, Header):
            return dict(o)
        if isinstance(o, Time):
            return dict(o)

        return super(MessageEncoder, self).default(o)


class Topic(object):
    """Publish and/or subscribe to a topic in ROS.

    Args:
        ros (:class:`.Ros`): Instance of the ROS connection.
        name (:obj:`str`): Topic name, e.g. ``/cmd_vel``.
        message_type (:obj:`str`): Message type, e.g. ``std_msgs/String``.
        compression (:obj:`str`): Type of compression to use, e.g. `png`. Defaults to `None`.
        throttle_rate (:obj:`int`): Rate (in ms between messages) at which to throttle the topics.
        queue_size (:obj:`int`): Queue size created at bridge side for re-publishing webtopics.
        latch (:obj:`bool`): True to latch the topic when publishing, False otherwise.
        queue_length (:obj:`int`): Queue length at bridge side used when subscribing.
        reconnect_on_close (:obj:`bool`): Reconnect topic (both publisher & subscriber) on reconnection.
    """

    SUPPORTED_COMPRESSION_TYPES = ("png", "none")

    def __init__(
        self,
        ros,
        name,
        message_type,
        compression=None,
        latch=False,
        throttle_rate=0,
        queue_size=100,
        queue_length=0,
        reconnect_on_close=True,
    ):
        self.ros = ros
        self.name = name
        self.message_type = message_type
        self.compression = compression
        self.latch = latch
        self.throttle_rate = throttle_rate
        self.queue_size = queue_size
        self.queue_length = queue_length

        self._subscribe_id = None
        self._advertise_id = None

        if self.compression is None:
            self.compression = "none"

        if self.compression not in self.SUPPORTED_COMPRESSION_TYPES:
            raise ValueError("Unsupported compression type. Must be one of: " + str(self.SUPPORTED_COMPRESSION_TYPES))

        self.reconnect_on_close = reconnect_on_close

    @property
    def is_advertised(self):
        """Indicate if the topic is currently advertised or not.

        Returns:
            bool: True if advertised as publisher of this topic, False otherwise.
        """
        return self._advertise_id is not None

    @property
    def is_subscribed(self):
        """Indicate if the topic is currently subscribed or not.

        Returns:
            bool: True if subscribed to this topic, False otherwise.
        """
        return self._subscribe_id is not None

    def subscribe(self, callback):
        """Register a subscription to the topic.

        Every time a message is published for the given topic,
        the callback will be called with the message object.

        Args:
            callback: Function to be called when messages of this topic are published.
        """
        # Avoid duplicate subscription
        if self._subscribe_id:
            return

        self._subscribe_id = "subscribe:%s:%d" % (self.name, self.ros.id_counter)

        self.ros.on(self.name, callback)
        self._connect_topic(
            Message(
                {
                    "op": "subscribe",
                    "id": self._subscribe_id,
                    "type": self.message_type,
                    "topic": self.name,
                    "compression": self.compression,
                    "throttle_rate": self.throttle_rate,
                    "queue_length": self.queue_length,
                }
            )
        )

    def unsubscribe(self):
        """Unregister from a subscribed the topic."""
        if not self._subscribe_id:
            return

        # Do not try to reconnect when manually unsubscribing
        if self.reconnect_on_close:
            self.ros.off("close", self._reconnect_topic)

        self.ros.off(self.name)
        self.ros.send_on_ready(Message({"op": "unsubscribe", "id": self._subscribe_id, "topic": self.name}))
        self._subscribe_id = None

    def publish(self, message):
        """Publish a message to the topic.

        Args:
            message (:class:`.Message`): ROS Bridge Message to publish.
        """
        if not self.is_advertised:
            self.advertise()

        self.ros.send_on_ready(
            Message(
                {
                    "op": "publish",
                    "id": "publish:%s:%d" % (self.name, self.ros.id_counter),
                    "topic": self.name,
                    "msg": dict(message),
                    "latch": self.latch,
                }
            )
        )

    def advertise(self):
        """Register as a publisher for the topic."""
        if self.is_advertised:
            return

        self._advertise_id = "advertise:%s:%d" % (self.name, self.ros.id_counter)

        self._connect_topic(
            Message(
                {
                    "op": "advertise",
                    "id": self._advertise_id,
                    "type": self.message_type,
                    "topic": self.name,
                    "latch": self.latch,
                    "queue_size": self.queue_size,
                }
            )
        )

        if not self.reconnect_on_close:
            self.ros.on("close", self._reset_advertise_id)

    def _reset_advertise_id(self, _proto):
        self._advertise_id = None

    def _connect_topic(self, message):
        self._connect_message = message
        self.ros.send_on_ready(message)

        if self.reconnect_on_close:
            self.ros.on("close", self._reconnect_topic)

    def _reconnect_topic(self, _proto):
        # Delay a bit the event hookup because
        #  1) _proto is not yet nullified, and
        #  2) reconnect anyway takes a few seconds
        self.ros.call_later(1, lambda: self.ros.send_on_ready(self._connect_message))

    def unadvertise(self):
        """Unregister as a publisher for the topic."""
        if not self.is_advertised:
            return

        # Do not try to reconnect when manually unadvertising
        if self.reconnect_on_close:
            self.ros.off("close", self._reconnect_topic)

        self.ros.send_on_ready(
            Message(
                {
                    "op": "unadvertise",
                    "id": self._advertise_id,
                    "topic": self.name,
                }
            )
        )

        self._advertise_id = None


class ServiceException(Exception):
    """Exception that is thrown when a service call fails."""

    pass


class Service(object):
    """Client/server of ROS services.

    This class can be used both to consume other ROS services as a client,
    or to provide ROS services as a server.

    Args:
        ros (:class:`.Ros`): Instance of the ROS connection.
        name (:obj:`str`): Service name, e.g. ``/add_two_ints``.
        service_type (:obj:`str`): Service type, e.g. ``rospy_tutorials/AddTwoInts``.
    """

    def __init__(self, ros, name, service_type, reconnect_on_close=True):
        self.ros = ros
        self.name = name
        self.service_type = service_type

        self._service_callback = None
        self._is_advertised = False
        self.reconnect_on_close = reconnect_on_close

    @property
    def is_advertised(self):
        """Service servers are registered as advertised on ROS.

        This class can be used to be a service client or a server.

        Returns:
            bool: True if this is a server, False otherwise.
        """
        return self._is_advertised

    def call(self, request, callback=None, errback=None, timeout=None):
        """Start a service call.

        Note:
            The service can be used either as blocking or non-blocking.
            If the ``callback`` parameter is ``None``, then the call will
            block until receiving a response. Otherwise, the service response
            will be returned in the callback.

        Args:
            request (:class:`.ServiceRequest`): Service request.
            callback: Callback invoked on successful execution.
            errback: Callback invoked on error.
            timeout: Timeout for the operation, in seconds. Only used if blocking.

        Returns:
            object: Service response if used as a blocking call, otherwise ``None``.
        """
        if self.is_advertised:
            return

        service_call_id = "call_service:%s:%d" % (self.name, self.ros.id_counter)

        message = Message(
            {
                "op": "call_service",
                "id": service_call_id,
                "service": self.name,
                "args": dict(request),
            }
        )

        # Non-blocking mode
        if callback:
            self.ros.call_async_service(message, callback, errback)
            return

        # Blocking mode
        call_results = self.ros.call_sync_service(message, timeout)
        if "exception" in call_results:
            raise ServiceException(call_results["exception"])

        return call_results["result"]

    def advertise(self, callback):
        """Start advertising the service.

        This turns the instance from a client into a server. The callback will be
        invoked with every request that is made to the service.

        If the service is already advertised, this call does nothing.

        Args:
            callback: Callback invoked on every service call. It should accept two parameters: `service_request` and
                `service_response`. It should return `True` if executed correctly, otherwise `False`.
        """
        if self.is_advertised:
            return

        if not callable(callback):
            raise ValueError("Callback is not a valid callable")

        self._service_callback = callback
        self.ros.on(self.name, self._service_response_handler)
        self._connect_service(Message({"op": "advertise_service", "type": self.service_type, "service": self.name}))
        self._is_advertised = True
        if not self.reconnect_on_close:
            self.ros.on("close", self._reset_advertise_id)

    def _reset_advertise_id(self, _proto):
        self._is_advertised = False

    def _connect_service(self, message):
        self._connect_message = message
        self.ros.send_on_ready(message)

        if self.reconnect_on_close:
            self.ros.on("close", self._reconnect_service)

    def _reconnect_service(self, _proto):
        # Delay a bit the event hookup because
        #  1) _proto is not yet nullified, and
        #  2) reconnect anyway takes a few seconds
        self.ros.call_later(1, lambda: self.ros.send_on_ready(self._connect_message))

    def unadvertise(self):
        """Unregister as a service server."""
        if not self.is_advertised:
            return

        # Do not try to reconnect when manually unadvertising
        if self.reconnect_on_close:
            self.ros.off("close", self._reconnect_service)

        self.ros.send_on_ready(
            Message(
                {
                    "op": "unadvertise_service",
                    "service": self.name,
                }
            )
        )
        self.ros.off(self.name, self._service_response_handler)

        self._is_advertised = False

    def _service_response_handler(self, request):
        response = ServiceResponse()
        success = self._service_callback(request["args"], response)

        call = Message({"op": "service_response", "service": self.name, "values": dict(response), "result": success})

        if "id" in request:
            call["id"] = request["id"]

        self.ros.send_on_ready(call)


class ActionClient(object):
    """Action Client of ROS 2 actions.

    Args:
        ros (:class:`.Ros`): Instance of the ROS connection.
        name (:obj:`str`): Service name, e.g. ``/fibonacci``.
        action_type (:obj:`str`): Action type, e.g. ``example_interfaces/action/Fibonacci``.
    """

    def __init__(self, ros, name, action_type, reconnect_on_close=True):
        self.ros = ros
        self.name = name
        self.action_type = action_type

        self._service_callback = None
        self._is_advertised = False
        self.reconnect_on_close = reconnect_on_close
        self.wait_results = {}

    def send_goal(self, goal, resultback, feedback, errback):
        """Start a call to an action.

        Note: The action client is non-blocking.

        Args:
            goal (:class:`.Goal`): Action goal.
            resultback: Callback invoked on receiving action result.
            feedback: Callback invoked on receiving action feedback.
            errback: Callback invoked on error.

        Returns:
            object: goal ID if successfull, otherwise ``None``.
        """
        if self._is_advertised:
            return

        action_goal_id = "send_action_goal:%s:%d" % (self.name, self.ros.id_counter)
        self.wait_results[action_goal_id] = threading.Event()

        message = Message(
            {
                "op": "send_action_goal",
                "id": action_goal_id,
                "action": self.name,
                "action_type": self.action_type,
                "args": dict(goal),
                "feedback": True,
            }
        )

        def _internal_resultback(result):
            wait_result_event = self.wait_results.get(action_goal_id)
            if wait_result_event is not None:
                wait_result_event.set()
            resultback(result)

        def _internal_errback(err):
            wait_result_event = self.wait_results.get(action_goal_id)
            if wait_result_event is not None:
                wait_result_event.set()
            errback(err)

        self.ros.call_async_action(message,  _internal_resultback, feedback, _internal_errback)
        return action_goal_id

    def cancel_goal(self, goal_id):
        """Cancel an ongoing action.

        NOTE: Async cancelation is not yet supported on rosbridge (rosbridge_suite issue #909)

        Args:
            goal_id: Goal ID returned from ``send_goal()``
        """
        message = Message(
            {
                "op": "cancel_action_goal",
                "id": goal_id,
                "action": self.name,
            }
        )
        self.ros.send_on_ready(message)

        # Remove message_id from RosBridgeProtocol._pending_action_requests in comms.py?
        # Not needed since an action result is returned upon cancelation.

    def wait_goal(self, goal_id, timeout=None):
        """Block until the result is available.

        If ``timeout`` is ``None``, it will wait indefinitely.

        Args:
            goal_id: Goal ID returned from ``send_goal()``
            timeout (:obj:`int`): Timeout to wait for the result expressed in seconds.
        """

        wait_result_event = self.wait_results.get(goal_id)
        if wait_result_event is None:
            raise ValueError("Unknown goal ID")

        if not wait_result_event.wait(timeout):
            raise RosTimeoutError("Goal failed to receive result")

        self.wait_results.pop(goal_id, None)


class Param(object):
    """A ROS parameter.

    Args:
        ros (:class:`.Ros`): Instance of the ROS connection.
        name (:obj:`str`): Parameter name, e.g. ``max_vel_x``.
    """

    def __init__(self, ros, name):
        self.ros = ros
        self.name = name

    def get(self, callback=None, errback=None, timeout=None):
        """Fetch the current value of the parameter.

        Note:
            This method can be used either as blocking or non-blocking.
            If the ``callback`` parameter is ``None``, the call will
            block and return the parameter value. Otherwise, the parameter
            value will be passed on to the callback.

        Args:
            callback: Callable function to be invoked when the operation is completed.
            errback: Callback invoked on error.
            timeout: Timeout for the operation, in seconds. Only used if blocking.

        Returns:
            object: Parameter value if used as a blocking call, otherwise ``None``.
        """
        client = Service(self.ros, "/rosapi/get_param", "rosapi/GetParam")
        request = ServiceRequest({"name": self.name})

        if not callback:
            result = client.call(request, timeout=timeout)
            return json.loads(result["value"])
        else:
            client.call(request, lambda result: callback(json.loads(result["value"])), errback)

    def set(self, value, callback=None, errback=None, timeout=None):
        """Set a new value to the parameter.

        Note:
            This method can be used either as blocking or non-blocking.
            If the ``callback`` parameter is ``None``, the call will
            block until completion.

        Args:
            callback: Callable function to be invoked when the operation is completed.
            errback: Callback invoked on error.
            timeout: Timeout for the operation, in seconds. Only used if blocking.
        """
        client = Service(self.ros, "/rosapi/set_param", "rosapi/SetParam")
        request = ServiceRequest({"name": self.name, "value": json.dumps(value)})

        client.call(request, callback, errback, timeout=timeout)

    def delete(self, callback=None, errback=None, timeout=None):
        """Delete the parameter.

        Note:
            This method can be used either as blocking or non-blocking.
            If the ``callback`` parameter is ``None``, the call will
            block until completion.

        Args:
            callback: Callable function to be invoked when the operation is completed.
            errback: Callback invoked on error.
            timeout: Timeout for the operation, in seconds. Only used if blocking.
        """
        client = Service(self.ros, "/rosapi/delete_param", "rosapi/DeleteParam")
        request = ServiceRequest({"name": self.name})

        client.call(request, callback, errback, timeout=timeout)


if __name__ == "__main__":

    from . import Ros

    FORMAT = "%(asctime)-15s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=FORMAT)

    ros_client = Ros("127.0.0.1", 9090)

    def run_subscriber_example():
        listener = Topic(ros_client, "/chatter", "std_msgs/String")
        listener.subscribe(lambda message: LOGGER.info("Received message on: %s", message["data"]))

    def run_unsubscriber_example():
        listener = Topic(ros_client, "/chatter", "std_msgs/String")

        def print_message(message):
            LOGGER.info("Received message on: %s", message["data"])

        listener.subscribe(print_message)

        ros_client.call_later(5, lambda: listener.unsubscribe())
        ros_client.call_later(10, lambda: listener.subscribe(print_message))

    def run_publisher_example():
        publisher = Topic(ros_client, "/chatter", "std_msgs/String", compression="png")

        def start_sending():
            i = 0
            while ros_client.is_connected and i < 5:
                i += 1
                message = Message({"data": "test"})
                LOGGER.info("Publishing message to /chatter. %s", message)
                publisher.publish(message)

                time.sleep(0.75)

            publisher.unadvertise()

        ros_client.on_ready(start_sending, run_in_thread=True)

    def run_service_example():
        def h1(x):
            print("ok", x)

        def h2(x):
            print("error", x)

        service = Service(ros_client, "/turtle1/teleport_relative", "turtlesim/TeleportRelative")
        service.call(ServiceRequest({"linear": 2, "angular": 2}), h1, h2)

    def run_turtle_subscriber_example():
        listener = Topic(ros_client, "/turtle1/pose", "turtlesim/Pose", throttle_rate=500)

        def print_message(message):
            LOGGER.info("Received message on: %s", message)

        listener.subscribe(print_message)

    def run_get_example():
        param = Param(ros_client, "run_id")
        param.get(print)

    def run_set_example():
        param = Param(ros_client, "test_param")
        param.set("test_value")

    def run_delete_example():
        param = Param(ros_client, "test_param")
        param.delete()

    def run_server_example():
        service = Service(ros_client, "/test_server", "rospy_tutorials/AddTwoInts")

        def dispose_server():
            service.unadvertise()
            ros_client.call_later(1, service.ros.terminate)

        def add_two_ints(request, response):
            response["sum"] = request["a"] + request["b"]
            if response["sum"] == 42:
                ros_client.call_later(2, dispose_server)

            return True

        service.advertise(add_two_ints)

    run_server_example()
    ros_client.run_forever()
