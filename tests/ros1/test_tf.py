import threading

from roslibpy import Ros
from roslibpy.tf import TFClient


def test_tf_test(ros_transport):
    context = dict(wait=threading.Event(), counter=0)
    ros = Ros("127.0.0.1", 9090, transport=ros_transport)
    ros.run()

    tf_client = TFClient(ros, fixed_frame="world")

    def callback(message):
        context["message"] = message
        context["counter"] += 1
        context["wait"].set()

    tf_client.subscribe(frame_id="/world", callback=callback)
    if not context["wait"].wait(5):
        raise Exception

    assert context["counter"] > 0
    assert context["message"]["translation"] == dict(x=0.0, y=0.0, z=0.0), "Unexpected translation received"
    assert context["message"]["rotation"] == dict(x=0.0, y=0.0, z=0.0, w=1.0), "Unexpected rotation received"
    ros.close()
