from __future__ import print_function

import time

from roslibpy import Ros, Service, ServiceRequest


def test_add_two_ints_service(ros_transport):
    ros = Ros("127.0.0.1", 9090, transport=ros_transport)
    ros.run()

    def add_two_ints(request, response):
        response["sum"] = request["a"] + request["b"]

        return False

    service_name = "/test_sum_service"
    service_type = "rospy_tutorials/AddTwoInts"
    service = Service(ros, service_name, service_type)
    service.advertise(add_two_ints)
    time.sleep(1)

    client = Service(ros, service_name, service_type)
    result = client.call(ServiceRequest({"a": 2, "b": 40}))
    assert result["sum"] == 42

    service.unadvertise()
    time.sleep(2)
    ros.close()


def test_empty_service(ros_transport):
    ros = Ros("127.0.0.1", 9090, transport=ros_transport)
    ros.run()

    service = Service(ros, "/test_empty_service", "std_srvs/Empty")
    service.advertise(lambda req, resp: True)
    time.sleep(1)

    client = Service(ros, "/test_empty_service", "std_srvs/Empty")
    client.call(ServiceRequest())

    service.unadvertise()
    time.sleep(2)
    ros.close()
