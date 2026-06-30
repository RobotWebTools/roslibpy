import threading

import pytest

from roslibpy import Ros

host = "127.0.0.1"
port = 9090
url = "ws://%s:%d" % (host, port)


def test_rosapi_topics(ros_transport):
    context = dict(wait=threading.Event(), result=None)
    ros = Ros(host, port, transport=ros_transport)
    ros.run()

    def callback(topic_list):
        context["result"] = topic_list
        context["wait"].set()

    ros.get_topics(callback)
    if not context["wait"].wait(5):
        raise Exception

    assert "/rosout" in context["result"]["topics"]
    ros.close()


def test_rosapi_topics_blocking(ros_transport):
    ros = Ros(host, port, transport=ros_transport)
    ros.run()
    topic_list = ros.get_topics()

    print(topic_list)
    assert "/rosout" in topic_list

    ros.close()


def test_connection_fails_when_missing_port(ros_transport):
    with pytest.raises(Exception):
        Ros(host, transport=ros_transport)


def test_connection_fails_when_schema_not_ws(ros_transport):
    with pytest.raises(Exception):
        Ros("http://%s:%d" % (host, port), transport=ros_transport)
