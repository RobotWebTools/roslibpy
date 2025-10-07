from __future__ import print_function
import roslibpy
import time


global result

def result_callback(msg):
    global result
    result = msg
    print("Action result:", msg)

def feedback_callback(msg):
    print(f"Action feedback: {msg['sequence']}")

def fail_callback(msg):
    print(f"Action failed: {msg}")


def test_action_success(action_client):
    """ This test function sends a action goal to an Action server.
    """
    global result
    result = None
    
    goal = roslibpy.Goal({"order": 8})
    action_client.send_goal(goal,
                                result_callback,
                                feedback_callback,
                                fail_callback)

    while result == None:
        time.sleep(1)

    print("-----------------------------------------------")
    print("Action status:", result["status"])
    print("Action result: {}".format(result["values"]["sequence"]))


def test_action_cancel(action_client):
    """ This test function sends a cancel request to an Action server.
        NOTE: Make sure to start the "rosbridge_server" node with the parameter
              "send_action_goals_in_new_thread" set to "true".
    """
    global result
    result = None

    goal = roslibpy.Goal({"order": 8})
    goal_id = action_client.send_goal(goal,
                                    result_callback,
                                    feedback_callback,
                                    fail_callback)
    time.sleep(3)
    print("Sending action goal cancel request...")
    action_client.cancel_goal(goal_id)

    while result == None:
        time.sleep(1)

    print("-----------------------------------------------")
    print("Action status:", result["status"])
    print("Action result: {}".format(result["values"]["sequence"]))


if __name__ == "__main__":
    client = roslibpy.Ros(host="localhost", port=9090)
    client.run()

    action_client = roslibpy.ActionClient(client,
                                        "/fibonacci",
                                      "example_interfaces/action/Fibonacci")
    print("\n** Starting action client test **")
    test_action_success(action_client)

    print("\n** Starting action goal cancelation test **")
    test_action_cancel(action_client)
