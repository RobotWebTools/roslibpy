from __future__ import print_function

import time

from roslibpy import Ros
from roslibpy.ros1.actionlib import ActionClient, Goal, GoalStatus, SimpleActionServer


def test_action_success():
    ros = Ros("127.0.0.1", 9090)
    ros.run()

    server = SimpleActionServer(ros, "/test_action", "actionlib/TestAction")

    def execute(goal):
        server.set_succeeded({"result": goal["goal"]})

    server.start(execute)

    client = ActionClient(ros, "/test_action", "actionlib/TestAction")
    goal = Goal(client, {"goal": 13})

    goal.send()
    result = goal.wait(10)

    assert result["result"] == 13
    assert goal.status["status"] == GoalStatus.SUCCEEDED

    client.dispose()
    time.sleep(2)
    ros.close()


def test_action_preemt():
    ros = Ros("127.0.0.1", 9090)
    ros.run()

    server = SimpleActionServer(ros, "/test_action", "actionlib/TestAction")

    def execute(_goal):
        while not server.is_preempt_requested():
            time.sleep(0.1)
        server.set_preempted()

    server.start(execute)

    client = ActionClient(ros, "/test_action", "actionlib/TestAction")
    goal = Goal(client, {"goal": 13})

    goal.send()
    time.sleep(0.5)
    goal.cancel()

    result = goal.wait(10)

    assert result["result"] == 0
    assert goal.status["status"] == GoalStatus.PREEMPTED

    client.dispose()
    time.sleep(2)
    ros.close()
