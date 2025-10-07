from __future__ import print_function

import json
import logging

from roslibpy.core import (
    Feedback,
    GoalStatus,
    Message,
    MessageEncoder,
    Result,
    ServiceResponse,
)

LOGGER = logging.getLogger("roslibpy")


class RosBridgeException(Exception):
    """Exception raised on the ROS bridge communication."""

    def __init__(self, message, cause=None):
        super(RosBridgeException, self).__init__(message, cause)


class RosBridgeProtocol(object):
    """Implements the websocket client protocol to encode/decode JSON ROS Bridge messages."""

    def __init__(self, *args, **kwargs):
        super(RosBridgeProtocol, self).__init__(*args, **kwargs)
        self.factory = None
        self._pending_service_requests = {}
        self._pending_action_requests = {}
        self._message_handlers = {
            "publish": self._handle_publish,
            "service_response": self._handle_service_response,
            "call_service": self._handle_service_request,
            "send_action_goal": self._handle_action_request,  # TODO: action server
            "cancel_action_goal": self._handle_action_cancel,  # TODO: action server
            "action_feedback": self._handle_action_feedback,
            "action_result": self._handle_action_result,
            "status": None,  # TODO: add handlers for op: status
        }

    def on_message(self, payload):
        message = Message(json.loads(payload.decode("utf8")))
        handler = self._message_handlers.get(message["op"], None)
        if not handler:
            raise RosBridgeException('No handler registered for operation "%s"' % message["op"])
        handler(message)

    def send_ros_message(self, message):
        """Encode and serialize ROS Bridge protocol message.

        Args:
            message (:class:`.Message`): ROS Bridge Message to send.
        """
        try:
            json_message = json.dumps(dict(message), cls=MessageEncoder).encode("utf8")
            LOGGER.debug("Sending ROS message|<pre>%s</pre>", json_message)

            self.send_message(json_message)
        except Exception as exception:
            # TODO: Check if it makes sense to raise exception again here
            # Since this is wrapped in many layers of indirection
            LOGGER.exception("Failed to send message, %s", exception)

    def register_message_handlers(self, operation, handler):
        """Register a message handler for a specific operation type.

        Args:
            operation (:obj:`str`): ROS Bridge operation.
            handler: Callback to handle the message.
        """
        if operation in self._message_handlers:
            raise RosBridgeException("Only one handler can be registered per operation")

        self._message_handlers[operation] = handler

    def send_ros_service_request(self, message, callback, errback):
        """Initiate a ROS service request through the ROS Bridge.

        Args:
            message (:class:`.Message`): ROS Bridge Message containing the service request.
            callback: Callback invoked on successful execution.
            errback: Callback invoked on error.
        """
        request_id = message["id"]
        self._pending_service_requests[request_id] = (callback, errback)

        json_message = json.dumps(dict(message), cls=MessageEncoder).encode("utf8")
        LOGGER.debug("Sending ROS service request: %s", json_message)

        self.send_message(json_message)

    def _handle_publish(self, message):
        self.factory.emit(message["topic"], message["msg"])

    def _handle_service_response(self, message):
        request_id = message["id"]
        service_handlers = self._pending_service_requests.get(request_id, None)

        if not service_handlers:
            raise RosBridgeException('No handler registered for service request ID: "%s"' % request_id)

        callback, errback = service_handlers
        del self._pending_service_requests[request_id]

        if "result" in message and message["result"] is False:
            if errback:
                errback(message["values"])
        else:
            if callback:
                callback(ServiceResponse(message["values"]))

    def _handle_service_request(self, message):
        if "service" not in message:
            raise ValueError("Expected service name missing in service request")

        self.factory.emit(message["service"], message)

    def send_ros_action_goal(self, message, resultback, feedback, errback):
        """Initiate a ROS action request by sending a goal through the ROS Bridge.

        Args:
        message (:class:`.Message`): ROS Bridge Message containing the action request.
        callback: Callback invoked on receiving result.
        feedback: Callback invoked when receiving feedback from action server.
        errback: Callback invoked on error.
        """
        request_id = message["id"]
        self._pending_action_requests[request_id] = (resultback, feedback, errback)

        json_message = json.dumps(dict(message), cls=MessageEncoder).encode("utf8")
        LOGGER.debug("Sending ROS action goal request: %s", json_message)

        self.send_message(json_message)

    def _handle_action_request(self, message):
        if "action" not in message:
            raise ValueError("Expected action name missing in action request")
        raise RosBridgeException("Action server capabilities not yet implemented")

    def _handle_action_cancel(self, message):
        if "action" not in message:
            raise ValueError("Expected action name missing in action request")
        raise RosBridgeException("Action server capabilities not yet implemented")

    def _handle_action_feedback(self, message):
        if "action" not in message:
            raise ValueError("Expected action name missing in action feedback")

        request_id = message["id"]
        _, feedback, _ = self._pending_action_requests.get(request_id, None)
        feedback(Feedback(message["values"]))

    def _handle_action_result(self, message):
        request_id = message["id"]
        action_handlers = self._pending_action_requests.get(request_id, None)

        if not action_handlers:
            raise RosBridgeException('No handler registered for action request ID: "%s"' % request_id)

        resultback, _, errback = action_handlers
        del self._pending_action_requests[request_id]

        # Handle different message formats for status field
        # ROS 2 rosbridge may send status at top level or inside values
        status = message.get("status")
        if status is None and "values" in message:
            status = message["values"].get("status")
        if status is None:
            # Default to UNKNOWN if status is not found
            status = GoalStatus.UNKNOWN.value

        LOGGER.debug("Received Action result with status: %s", status)

        results = {"status": GoalStatus(status), "values": message.get("values", {})}

        if "result" in message and message["result"] is False:
            if errback:
                errback(results)
        else:
            if resultback:
                resultback(Result(results))
