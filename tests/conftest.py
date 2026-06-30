import os
import sys

import pytest

# The ``twisted`` and ``asyncio`` transports both run on Autobahn, whose txaio
# layer binds a single async framework per process. They are therefore mutually
# exclusive within one interpreter, so each test process exercises exactly one
# transport, selected via ``ROSLIBPY_TRANSPORT`` (default: ``twisted``). CI runs
# the suite once per transport in separate processes.
if sys.platform == "cli":
    ROS_TRANSPORTS = ("cli",)
else:
    ROS_TRANSPORTS = (os.environ.get("ROSLIBPY_TRANSPORT", "twisted"),)


@pytest.fixture(params=ROS_TRANSPORTS)
def ros_transport(request):
    if request.param == "asyncio":
        pytest.importorskip("autobahn.asyncio.websocket")
    return request.param
