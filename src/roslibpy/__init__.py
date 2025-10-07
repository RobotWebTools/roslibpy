"""

This library relies on the `ROS bridge suite <http://wiki.ros.org/rosbridge_suite>`_
by Robot Web Tools to interact with ROS via WebSockets.

The `ROS bridge protocol <https://github.com/RobotWebTools/rosbridge_suite/blob/master/ROSBRIDGE_PROTOCOL.md>`_
uses JSON as message transport to allow access to ROS functionality such as
publishing, subscribing, service calls, actionlib, TF, etc.

.. _ros-setup:

ROS Setup
=========

In order to use this library, your ROS environment needs to be setup to run ``rosbridge``.

First install the **rosbridge suite** with the following commands::

    sudo apt-get install -y ros-kinetic-rosbridge-server
    sudo apt-get install -y ros-kinetic-tf2-web-republisher

And before starting a connection, make sure you launch all services::

    roslaunch rosbridge_server rosbridge_websocket.launch
    rosrun tf2_web_republisher tf2_web_republisher


Connecting to ROS
=================

The connection to ROS is managed by the :class:`Ros` class. Besides connection and
disposal, it handles automatic reconnections when needed.

Other classes that need an active connection with ROS receive this instance
as an argument to their constructors.

.. autoclass:: Ros
   :members:
.. autofunction:: set_rosapi_timeout

Main ROS concepts
=================

ROS 1 vs ROS 2
--------------

This library has been tested to work with ROS 1. ROS 2 should work, but it is still
in the works.

One area in which ROS 1 and ROS 2 differ is in the header interface. To use ROS 2, use
the header defined in the `roslibpy.ros2` module.

.. autoclass:: roslibpy.ros2.Header
   :members:


Topics
------

ROS is a communication infrastructure. In ROS, different **nodes** communicate with
each other through messages. **ROS messages** are represented by the :class:`Message`
class and are passed around via :class:`Topics <Topic>` using a **publish/subscribe**
model.

.. autoclass:: Message
   :members:
.. autoclass:: Header
   :members:
.. autoclass:: Topic
   :members:

Services
--------

Besides the publish/subscribe model used with topics, ROS offers a request/response
model via :class:`Services <Service>`.

.. autoclass:: Service
   :members:
.. autoclass:: ServiceRequest
   :members:
.. autoclass:: ServiceResponse
   :members:

Actions (ROS 2)
---------------

An Action client for ROS 2 Actions can be used by managing goal/feedback/result
messages via :class:`ActionClient <ActionClient>`.

.. autoclass:: ActionClient
   :members:
.. autoclass:: Goal
   :members:
.. autoclass:: GoalStatus
   :members:
.. autoclass:: Feedback
   :members:
.. autoclass:: Result
   :members:

Parameter server
----------------

ROS provides a parameter server to share data among different nodes. This service
can be accessed via the :class:`Param` class.

.. autoclass:: Param
   :members:

Time
----

To represent time, there is the concept of ROS time primitive type, which consists of
two integers: seconds since epoch and nanoseconds since seconds.

.. autoclass:: Time
   :members:

"""

from .__version__ import (
    __author__,
    __author_email__,
    __copyright__,
    __description__,
    __license__,
    __title__,
    __url__,
    __version__,
)
from .core import (
    ActionClient,
    Feedback,
    Goal,
    GoalStatus,
    Header,
    Message,
    Param,
    Result,
    Service,
    ServiceRequest,
    ServiceResponse,
    Time,
    Topic,
)
from .ros import Ros, set_rosapi_timeout

__all__ = [
    "__author__",
    "__author_email__",
    "__copyright__",
    "__description__",
    "__license__",
    "__title__",
    "__url__",
    "__version__",
    "ActionClient",
    "Feedback",
    "Goal",
    "GoalStatus",
    "Header",
    "Message",
    "Param",
    "Result",
    "Ros",
    "Service",
    "ServiceRequest",
    "ServiceResponse",
    "set_rosapi_timeout",
    "Time",
    "Topic",
]
