from unittest.mock import Mock
import pytest
from roslibpy import Topic


@pytest.mark.parametrize("first", ["subscribe", "advertise"])
def test_dual_role_topic_reconnects_both_roles(first):
    ros = Mock()
    ros.id_counter = 1
    delayed = []
    ros.call_later.side_effect = lambda delay, callback: delayed.append(callback)
    topic = Topic(ros, "/state", "std_msgs/String")
    actions = {"subscribe": lambda: topic.subscribe(lambda _: None), "advertise": topic.advertise}
    actions[first]()
    actions["advertise" if first == "subscribe" else "subscribe"]()
    assert sum(call.args[0] == "close" for call in ros.on.call_args_list) == 1
    ros.send_on_ready.reset_mock()
    topic._reconnect_topic(None)
    for callback in delayed:
        callback()
    operations = [call.args[0]["op"] for call in ros.send_on_ready.call_args_list]
    assert sorted(operations) == ["advertise", "subscribe"]


@pytest.mark.parametrize("removed,remaining", [("unsubscribe", "advertise"), ("unadvertise", "subscribe")])
def test_removing_one_role_preserves_other_reconnect(removed, remaining):
    ros = Mock()
    ros.id_counter = 1
    callbacks = []
    ros.call_later.side_effect = lambda delay, callback: callbacks.append(callback)
    topic = Topic(ros, "/state", "std_msgs/String")
    topic.subscribe(lambda _: None)
    topic.advertise()
    topic._reconnect_topic(None)
    getattr(topic, removed)()
    assert not any(call.args[0] == "close" for call in ros.off.call_args_list)
    ros.send_on_ready.reset_mock()
    for callback in callbacks:
        callback()
    assert [call.args[0]["op"] for call in ros.send_on_ready.call_args_list] == [remaining]


def test_removing_both_roles_cancels_pending_reconnect():
    ros = Mock()
    ros.id_counter = 1
    callbacks = []
    ros.call_later.side_effect = lambda delay, callback: callbacks.append(callback)
    topic = Topic(ros, "/state", "std_msgs/String")
    topic.subscribe(lambda _: None)
    topic.advertise()
    topic._reconnect_topic(None)
    topic.unsubscribe()
    topic.unadvertise()
    assert any(call.args == ("close", topic._reconnect_topic) for call in ros.off.call_args_list)
    ros.send_on_ready.reset_mock()
    for callback in callbacks:
        callback()
    ros.send_on_ready.assert_not_called()
