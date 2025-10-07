"""
Actionlib (ROS 1)
=================

Another way to interact with ROS is through the **actionlib** stack. Actions in
ROS allow to execute preemptable tasks, i.e. tasks that can be interrupted by the client.

Actions are used via the :class:`ActionClient` to which :class:`Goals <Goal>`
can be added. Each goal emits events that can be listened to in order to react to the
updates from the action server. There are four events emmitted: **status**, **result**,
**feedback**, and **timeout**.

.. autoclass:: Goal
   :members:
.. autoclass:: ActionClient
   :members:
.. autoclass:: SimpleActionServer
   :members:
.. autoclass:: GoalStatus
   :members:

"""
from __future__ import print_function

import logging
import math
import random
import threading
import time

from roslibpy import Message, Topic
from roslibpy.core import RosTimeoutError
from roslibpy.event_emitter import EventEmitterMixin

__all__ = ["Goal", "GoalStatus", "ActionClient", "SimpleActionServer"]


LOGGER = logging.getLogger("roslibpy")
DEFAULT_CONNECTION_TIMEOUT = 3  # in seconds


def _is_earlier(t1, t2):
    """Compares two timestamps."""
    if t1["secs"] > t2["secs"]:
        return False
    elif t1["secs"] < t2["secs"]:
        return True
    elif t1["nsecs"] < t2["nsecs"]:
        return True

    return False


class GoalStatus:
    """Valid goal statuses."""

    PENDING = 0
    ACTIVE = 1
    PREEMPTED = 2
    SUCCEEDED = 3
    ABORTED = 4
    REJECTED = 5
    PREEMPTING = 6
    RECALLING = 7
    RECALLED = 8
    LOST = 9


class Goal(EventEmitterMixin):
    """Goal for an action server.

    After an event has been added to an action client, it will emit different
    events to indicate its progress:

    * ``status``: fires to notify clients on the current state of the goal.
    * ``feedback``: fires to send clients periodic auxiliary information of the goal.
    * ``result``: fires to send clients the result upon completion of the goal.
    * ``timeout``: fires when the goal did not complete in the specified timeout window.

    Args:
        action_client (:class:`.ActionClient`): Instance of the action client associated with the goal.
        goal_message (:class:`.Message`): Goal for the action server.
    """

    def __init__(self, action_client, goal_message):
        super(Goal, self).__init__()

        self.action_client = action_client
        self.goal_message = goal_message
        self.goal_id = "goal_%s_%d" % (random.random(), time.time() * 1000)

        self.wait_result = threading.Event()
        self.result = None
        self.status = None
        self.feedback = None

        self.goal_message = Message(
            {"goal_id": {"stamp": {"secs": 0, "nsecs": 0}, "id": self.goal_id}, "goal": dict(self.goal_message)}
        )

        self.action_client.add_goal(self)

        self.on("status", self._set_status)
        self.on("result", self._set_result)
        self.on("feedback", self._set_feedback)

    def send(self, result_callback=None, timeout=None):
        """Send goal to the action server.

        Args:
            timeout (:obj:`int`): Timeout for the goal's result expressed in seconds.
            callback (:obj:`callable`): Function to be called when a result is received.
            It is a shorthand for hooking on the ``result`` event.
        """
        if result_callback:
            self.on("result", result_callback)

        self.status = {"status": GoalStatus.PENDING}

        self.action_client.goal_topic.publish(self.goal_message)
        if timeout:
            self.action_client.ros.call_later(timeout, self._trigger_timeout)

    def cancel(self):
        """Cancel the current goal."""
        self.action_client.cancel_topic.publish(Message({"id": self.goal_id}))

    def wait(self, timeout=None):
        """Block until the result is available.

        If ``timeout`` is ``None``, it will wait indefinitely.

        Args:
            timeout (:obj:`int`): Timeout to wait for the result expressed in seconds.

        Returns:
            Result of the goal.
        """
        if not self.wait_result.wait(timeout):
            raise RosTimeoutError("Goal failed to receive result")

        return self.result

    def _trigger_timeout(self):
        if not self.is_finished:
            self.emit("timeout")

    def _set_status(self, status):
        self.status = status
        if self.is_finished:
            self.wait_result.set()

    def _set_result(self, result):
        self.result = result
        if self.is_finished:
            self.wait_result.set()

    def _set_feedback(self, feedback):
        self.feedback = feedback

    @property
    def is_active(self):
        if self.status is None:
            return False
        return self.status["status"] == GoalStatus.ACTIVE or self.status["status"] == GoalStatus.PENDING

    @property
    def is_finished(self):
        """Indicate if the goal is finished or not.

        Returns:
            bool: True if finished, False otherwise.
        """
        return self.result is not None and not self.is_active


class ActionClient(EventEmitterMixin):
    """Client to use ROS actions.

    Args:
        ros (:class:`.Ros`): Instance of the ROS connection.
        server_name (:obj:`str`): Action server name, e.g. ``/fibonacci``.
        action_name (:obj:`str`): Action message name, e.g. ``actionlib_tutorials/FibonacciAction``.
        timeout (:obj:`int`): **Deprecated.** Connection timeout, expressed in seconds.
    """

    def __init__(
        self, ros, server_name, action_name, timeout=None, omit_feedback=False, omit_status=False, omit_result=False
    ):
        super(ActionClient, self).__init__()
        self.ros = ros
        self.server_name = server_name
        self.action_name = action_name
        self.omit_feedback = omit_feedback
        self.omit_status = omit_status
        self.omit_result = omit_result
        self.goals = {}

        # Create the topics associated with actionlib
        self.feedback_listener = Topic(ros, server_name + "/feedback", action_name + "Feedback")
        self.status_listener = Topic(ros, server_name + "/status", "actionlib_msgs/GoalStatusArray")
        self.result_listener = Topic(ros, server_name + "/result", action_name + "Result")
        self.goal_topic = Topic(ros, server_name + "/goal", action_name + "Goal")
        self.cancel_topic = Topic(ros, server_name + "/cancel", "actionlib_msgs/GoalID")

        # Advertise the goal and cancel topics
        self.goal_topic.advertise()
        self.cancel_topic.advertise()

        # Subscribe to the status topic
        if not self.omit_status:
            self.status_listener.subscribe(self._on_status_message)

        # Subscribe to the feedback topic
        if not self.omit_feedback:
            self.feedback_listener.subscribe(self._on_feedback_message)

        # Subscribe to the result topic
        if not self.omit_result:
            self.result_listener.subscribe(self._on_result_message)

        if timeout:
            LOGGER.warn(
                "Deprecation warning: timeout parameter ignored and replaced by DEFAULT_CONNECTION_TIMEOUT constant."
            )

        self.wait_status = threading.Event()

        if not self.wait_status.wait(DEFAULT_CONNECTION_TIMEOUT):
            raise RosTimeoutError("Action client failed to connect, no status received.")

    def _on_status_message(self, message):
        self.wait_status.set()

        for status in message["status_list"]:
            goal_id = status["goal_id"]["id"]
            goal = self.goals.get(goal_id, None)

            if goal:
                goal.emit("status", status)

    def _on_feedback_message(self, message):
        goal_id = message["status"]["goal_id"]["id"]
        goal = self.goals.get(goal_id, None)

        if goal:
            goal.emit("feedback", message["feedback"])

    def _on_result_message(self, message):
        goal_id = message["status"]["goal_id"]["id"]
        goal = self.goals.get(goal_id, None)

        if goal:
            goal.emit("result", message["result"])

    def add_goal(self, goal):
        """Add a goal to this action client.

        Args:
            goal (:class:`.Goal`): Goal to add.
        """
        self.goals[goal.goal_id] = goal

    def cancel(self):
        """Cancel all goals associated with this action client."""
        self.cancel_topic.publish(Message())

    def dispose(self):
        """Unsubscribe and unadvertise all topics associated with this action client."""
        self.goal_topic.unadvertise()
        self.cancel_topic.unadvertise()

        if not self.omit_status:
            self.status_listener.unsubscribe()
        if not self.omit_feedback:
            self.feedback_listener.unsubscribe()
        if not self.omit_result:
            self.result_listener.unsubscribe()


class SimpleActionServer(EventEmitterMixin):
    """Implementation of the simple action server.

    The server emits the following events:

    * ``goal``: fires when a new goal has been received by the server.
    * ``cancel``: fires when the client has requested the cancellation of the action.

    Args:
        ros (:class:`.Ros`): Instance of the ROS connection.
        server_name (:obj:`str`): Action server name, e.g. ``/fibonacci``.
        action_name (:obj:`str`): Action message name, e.g. ``actionlib_tutorials/FibonacciAction``.
    """

    STATUS_PUBLISH_INTERVAL = 0.5  # In seconds

    def __init__(self, ros, server_name, action_name):
        super(SimpleActionServer, self).__init__()

        self.ros = ros
        self.server_name = server_name
        self.action_name = action_name
        self._lock = threading.Lock()

        # Create all required publishers and listeners
        self.feedback_publisher = Topic(ros, server_name + "/feedback", action_name + "Feedback")
        self.status_publisher = Topic(ros, server_name + "/status", "actionlib_msgs/GoalStatusArray")
        self.result_publisher = Topic(ros, server_name + "/result", action_name + "Result")
        self.goal_listener = Topic(ros, server_name + "/goal", action_name + "Goal")
        self.cancel_listener = Topic(ros, server_name + "/cancel", "actionlib_msgs/GoalID")

        # Advertise all publishers
        self.feedback_publisher.advertise()
        self.status_publisher.advertise()
        self.result_publisher.advertise()

        # Track the goals and their status in order to publish status
        self.status_message = Message(dict(header=dict(stamp=dict(secs=0, nsecs=100), frame_id=""), status_list=[]))

        # Needed for handling preemption prompted by a new goal being received
        self.current_goal = None  # currently tracked goal
        self.next_goal = None  # the one that'll be preempting
        self.preempt_request = False

        self.goal_listener.subscribe(self._on_goal_message)
        self.cancel_listener.subscribe(self._on_cancel_message)

        # Intentionally not publishing immediately and instead
        # waiting one interval for the first message
        self.ros.call_later(self.STATUS_PUBLISH_INTERVAL, self._periodic_publish_status)

    def start(self, action_callback):
        """Start the action server.

        Args:
            action_callback: Callable function to be invoked when a new goal is received.
            It takes one paramter containing the goal message.
        """
        LOGGER.info("Action server {} started".format(self.server_name))

        def _internal_goal_callback(goal):
            LOGGER.info("Action server {} received new goal".format(self.server_name))
            self.ros.call_in_thread(lambda: action_callback(goal))

        def _internal_preempt_callback():
            LOGGER.info("Action server {} received preemption request".format(self.server_name))
            self.preempt_request = True

        self.on("goal", _internal_goal_callback)
        self.on("cancel", _internal_preempt_callback)

    def _publish_status(self):
        current_time = time.time()
        secs = int(math.floor(current_time))
        nsecs = int(round(1e9 * (current_time - secs)))

        self.status_message["header"]["stamp"]["secs"] = secs
        self.status_message["header"]["stamp"]["nsecs"] = nsecs

        self.status_publisher.publish(self.status_message)

    def _periodic_publish_status(self):
        # Status publishing is required for clients to know they've connected
        with self._lock:
            self._publish_status()

        # Invoke again in the defined interval
        self.ros.call_later(self.STATUS_PUBLISH_INTERVAL, self._periodic_publish_status)

    def _on_goal_message(self, message):
        will_cancel = False
        will_emit_goal = None

        with self._lock:
            if self.current_goal:
                self.next_goal = message
                # needs to happen AFTER rest is set up
                will_cancel = True
            else:
                self.status_message["status_list"] = [dict(goal_id=message["goal_id"], status=GoalStatus.ACTIVE)]
                self.current_goal = message
                will_emit_goal = message["goal"]

        if will_cancel:
            self.emit("cancel")
        if will_emit_goal:
            self.emit("goal", will_emit_goal)

    def _on_cancel_message(self, message):
        # As described in the comments of the original roslibjs code
        # this may be more complicated than necessary, since it's
        # not sure the callbacks can ever wind up with a scenario
        # where we've been preempted by a next goal, it hasn't finished
        # processing, and then we get a cancel message.

        will_cancel = False

        with self._lock:
            message_id = message["id"]
            message_stamp = message["stamp"]
            secs = message["stamp"]["secs"]

            if secs == 0 and secs == 0 and message_id == "":
                self.next_goal = None
                if self.current_goal:
                    will_cancel = True

            else:  # treat id and stamp independently
                if self.current_goal and message_id == self.current_goal["goal_id"]["id"]:
                    will_cancel = True
                elif self.next_goal and message_id == self.next_goal["goal_id"]["id"]:
                    self.next_goal = None

                if self.next_goal and _is_earlier(self.next_goal["goal_id"]["stamp"], message_stamp):
                    self.next_goal = None
                if self.current_goal and _is_earlier(self.current_goal["goal_id"]["stamp"], message_stamp):
                    will_cancel = True

        if will_cancel:
            self.emit("cancel")

    def is_preempt_requested(self):
        """Indicate whether the client has requested preemption of the current goal."""
        with self._lock:
            return self.preempt_request

    def set_succeeded(self, result):
        """Set the current action state to succeeded.

        Args:
            result (:obj:`dict`): Dictionary of key/values to set as the result of the action.
        """
        LOGGER.info("Action server {} setting current goal to SUCCEEDED".format(self.server_name))

        with self._lock:
            status = dict(goal_id=self.current_goal["goal_id"], status=GoalStatus.SUCCEEDED)
            self.status_message["status_list"] = [status]
            self._publish_status()
            self.status_message["status_list"] = []

            result_message = Message({"status": status, "result": result})
            self.result_publisher.publish(result_message)

            if self.next_goal:
                self.current_goal = self.next_goal
                self.next_goal = None
            else:
                self.current_goal = None

            self.preempt_request = False

        # If there's a new current goal assigned, emit it
        if self.current_goal:
            self.emit("goal", self.current_goal["goal"])

    def send_feedback(self, feedback):
        """Send feedback.

        Args:
            feedback (:obj:`dict`): Dictionary of key/values of the feedback message.
        """
        feedback_message = Message(
            {"status": {"goal_id": self.current_goal["goal_id"], "status": GoalStatus.ACTIVE}, "feedback": feedback}
        )

        self.feedback_publisher.publish(feedback_message)

    def set_preempted(self):
        """Set the current action to preempted (cancelled)."""
        LOGGER.info("Action server {} preempting current goal".format(self.server_name))

        with self._lock:
            status = dict(goal_id=self.current_goal["goal_id"], status=GoalStatus.PREEMPTED)
            self.status_message["status_list"] = [status]
            self._publish_status()
            self.status_message["status_list"] = []

            result_message = Message({"status": status})
            self.result_publisher.publish(result_message)

            if self.next_goal:
                self.current_goal = self.next_goal
                self.next_goal = None
            else:
                self.current_goal = None

            # Preemption completed
            self.preempt_request = False

        # If there's a new current goal assigned, emit it
        if self.current_goal:
            self.emit("goal", self.current_goal["goal"])
