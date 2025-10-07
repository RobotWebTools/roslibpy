"""Tests for ROS 2 ActionClient message handling."""

from unittest.mock import Mock

from roslibpy.comm.comm import RosBridgeProtocol
from roslibpy.core import GoalStatus, Result


def test_action_result_with_status_at_top_level():
    """Test handling of action results with status at the top level of the message."""
    protocol = RosBridgeProtocol()
    protocol.factory = Mock()
    protocol.send_message = Mock()

    result_callback = Mock()
    feedback_callback = Mock()
    error_callback = Mock()

    request_id = "send_action_goal:/test_action:1"
    protocol._pending_action_requests[request_id] = (result_callback, feedback_callback, error_callback)

    # ROS 2 rosbridge message format with status at top level
    message = {
        "op": "action_result",
        "action": "/test_action",
        "id": request_id,
        "status": 4,  # SUCCEEDED
        "values": {"result": {"success": True, "message": "Action completed"}},
        "result": True,
    }

    protocol._handle_action_result(message)

    assert result_callback.called
    result = result_callback.call_args[0][0]
    assert isinstance(result, Result)
    assert result["status"] == GoalStatus.SUCCEEDED
    assert result["values"] == message["values"]


def test_action_result_with_status_in_values():
    """Test handling of action results with status inside the values field.

    This reproduces the KeyError issue reported in GitHub issue.
    """
    protocol = RosBridgeProtocol()
    protocol.factory = Mock()
    protocol.send_message = Mock()

    result_callback = Mock()
    feedback_callback = Mock()
    error_callback = Mock()

    request_id = "send_action_goal:/test_action:2"
    protocol._pending_action_requests[request_id] = (result_callback, feedback_callback, error_callback)

    # Alternative message format with status inside values
    message = {
        "op": "action_result",
        "action": "/test_action",
        "id": request_id,
        "values": {
            "status": 4,  # SUCCEEDED - status is here instead
            "result": {"success": True, "message": "Action completed"},
        },
        "result": True,
    }

    # This should not raise KeyError
    protocol._handle_action_result(message)

    assert result_callback.called
    result = result_callback.call_args[0][0]
    assert isinstance(result, Result)
    assert result["status"] == GoalStatus.SUCCEEDED


def test_action_result_failure_with_status_at_top_level():
    """Test handling of failed action results."""
    protocol = RosBridgeProtocol()
    protocol.factory = Mock()
    protocol.send_message = Mock()

    result_callback = Mock()
    feedback_callback = Mock()
    error_callback = Mock()

    request_id = "send_action_goal:/test_action:3"
    protocol._pending_action_requests[request_id] = (result_callback, feedback_callback, error_callback)

    message = {
        "op": "action_result",
        "action": "/test_action",
        "id": request_id,
        "status": 6,  # ABORTED
        "values": {"result": {"success": False, "message": "Action failed"}},
        "result": False,
    }

    protocol._handle_action_result(message)

    assert error_callback.called
    result = error_callback.call_args[0][0]
    assert result["status"] == GoalStatus.ABORTED
    assert result["values"] == message["values"]


def test_action_result_without_status_field():
    """Test handling of action results when status field is missing entirely.

    This is a defensive test for cases where neither top-level nor values contain status.
    In such cases, we should use a default status.
    """
    protocol = RosBridgeProtocol()
    protocol.factory = Mock()
    protocol.send_message = Mock()

    result_callback = Mock()
    feedback_callback = Mock()
    error_callback = Mock()

    request_id = "send_action_goal:/test_action:4"
    protocol._pending_action_requests[request_id] = (result_callback, feedback_callback, error_callback)

    # Message without status anywhere
    message = {
        "op": "action_result",
        "action": "/test_action",
        "id": request_id,
        "values": {"result": {"success": True}},
        "result": True,
    }

    # Should not raise KeyError, should use default status
    protocol._handle_action_result(message)

    assert result_callback.called
    result = result_callback.call_args[0][0]
    assert isinstance(result, Result)
    # Should have some status value (likely UNKNOWN)
    assert "status" in result
