import sys

import pytest

ROS_TRANSPORTS = ("cli",) if sys.platform == "cli" else ("twisted", "asyncio")


@pytest.fixture(params=ROS_TRANSPORTS)
def ros_transport(request):
    if request.param == "asyncio":
        pytest.importorskip("websockets.asyncio.client")
    return request.param
