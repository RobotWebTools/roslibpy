from __future__ import print_function

import time

import pytest

from roslibpy import Ros, ActionGoal
from roslibpy.actionlib import ActionClient

# @pytest.fixture
# def action_client():
#     ros = Ros(host="localhost", port=9090)
#     ros.run()

#     return ActionClient(
#         ros,
#         "/fibonacci",
#         "custom_action_interfaces/action/Fibonacci"
#     )


def feedback_callback(msg):
    print(f"Action feedback: {msg['partial_sequence']}")


def test_action_success():

    ros = Ros(host="localhost", port=9090)
    ros.run()

    action_client = ActionClient(ros, "/fibonacci", "example_interfaces/action/Fibonacci")

    result = None

    def result_feedback(msg):
        result = msg

    action_client.send_goal(ActionGoal({"order": 8}), result_feedback, feedback_callback)

    while result is None:
        time.sleep(1)

    assert result["status"] == "success"
    assert result["values"]["sequence"][-1] == 21


def test_action_cancellation():

    ros = Ros(host="localhost", port=9090)
    ros.run()

    action_client = ActionClient(ros, "/fibonacci", "example_interfaces/action/Fibonacci")

    result = None

    goal_id = action_client.send_goal(
        ActionGoal({"order": 8}), None, feedback_callback, lambda msg: print(f"Action failed with message: {msg}")
    )
    time.sleep(3)
    print("Sending action goal cancel request...")
    action_client.cancel_goal(goal_id)

    while result is None:
        time.sleep(1)

    assert result["status"] == "cancelled"
    assert result["values"]
