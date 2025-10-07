from __future__ import print_function

import time

from roslibpy import ActionClient, Goal, GoalStatus, Ros


def test_fibonacci():
    ros = Ros("127.0.0.1", 9090)
    ros.run()

    action = ActionClient(
        ros,
        '/fibonacci',
        'example_interfaces/action/Fibonacci'
    )

    results = {}

    def on_result(result):
        print(f"Result: {result}")
        results["result"] = result

    def on_feedback(feedback):
        print(f"Feedback: {feedback}")

    def on_error(error):
        print(f"Error: {error}")

    goal = Goal({"order": 4})
    goal_id = action.send_goal(goal, on_result, on_feedback, on_error)
    action.wait_goal(goal_id)
    time.sleep(0.2)

    assert results["result"]["values"]["sequence"] == [0, 1, 1, 2, 3]
    assert results["result"]["status"] == GoalStatus.SUCCEEDED

    ros.close()


def test_cancel():
    ros = Ros("127.0.0.1", 9090)
    ros.run()

    action = ActionClient(
        ros,
        '/fibonacci',
        'example_interfaces/action/Fibonacci'
    )

    results = {}

    def on_result(result):
        print(f"Result: {result}")
        results["result"] = result

    def on_feedback(feedback):
        print(f"Feedback: {feedback}")

    def on_error(error):
        print(f"Error: {error}")

    goal = Goal({"order": 10})
    goal_id = action.send_goal(goal, on_result, on_feedback, on_error)
    time.sleep(2)
    action.cancel_goal(goal_id)
    action.wait_goal(goal_id)
    time.sleep(0.2)

    assert results["result"]["status"] == GoalStatus.CANCELED

    ros.close()


if __name__ == "__main__":
    test_cancel()
