
Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog <http://keepachangelog.com/en/1.0.0/>`_
and this project adheres to `Semantic Versioning <http://semver.org/spec/v2.0.0.html>`_.

2.0.0
----------

**Added**

* Added ROS 2 action client support.
* Added ``wait_goal`` method to ``ActionClient`` to block until a goal reaches a terminal state.
* Moved ``actionlib`` module to ``roslibpy.ros1`` namespace.

**Changed**

**Fixed**

* Fixed KeyError in ROS 2 ActionClient when receiving action results with different message formats from rosbridge.

**Deprecated**

**Removed**

1.8.1
----------

**Added**

**Changed**

**Fixed**

* Fixed ROS connection issue on IronPython.

**Deprecated**

**Removed**

1.8.0
----------

**Added**

* Added websocket header support to the ROS-client.

**Changed**

**Fixed**

**Deprecated**

**Removed**

1.7.0
----------

**Added**

* Added a ROS 2 compatible header class in ``roslibpy.ros2.Header``.

**Changed**

**Fixed**

**Deprecated**

**Removed**

1.6.0
----------

**Added**

* Added authentication functionality described in [rosauth](http://wiki.ros.org/rosauth).

**Changed**

**Fixed**

**Deprecated**

**Removed**

1.5.0
----------

**Added**

* Added a wait event to close on IronPython to ensure the close request is sent before returning.

**Changed**

**Fixed**

* Fixed reconnection behavior on IronPython which would trigger reconnects even after a manual disconnect.

**Deprecated**

**Removed**

1.4.2
----------

**Added**

**Changed**

* Added ``tls`` to the twisted requirement (#111).

**Fixed**

**Deprecated**

**Removed**

1.4.1
----------

**Added**

**Changed**

**Fixed**

* Fixed bug with action client/server and now they work as expected.
* Fixed Python 2.7 incompatibilities introduced in 1.4.0.

**Deprecated**

**Removed**

1.4.0
----------

**Added**

**Changed**

* Switched to ``black`` for python code formatting.
* Fix incompatible settings between ``black`` and ``flake8``.
* Updated Github Actions workflows to remove python 3.6 builds.
* Replaced occurrences of ``raise Exception`` with more specific ``Exception`` subclasses.

**Fixed**

**Deprecated**

**Removed**

1.3.0
----------

**Added**

* Added function to set the default timeout value.
* Added ROS host and port parameters to the command-line interface.

**Fixed**

* Fixed #87 where a goal could be marked as terminal on result alone rather
  than both result and status.
* Ensure input of ``Time`` is always two integers.

1.2.1
----------

**Added**

**Changed**

**Fixed**

* Fixed blocking issues on the Twisted/Autobahn-based implementation of websockets.

**Deprecated**

**Removed**

1.2.0
----------

**Changed**

* Changed behavior: Advertising services automatically reconnect when websockets is reconnected.
* References to ROS master change to ROS.

**Added**

* Added ``Header`` and ``Time`` data types.
* Added ROS API method to retrieve current ROS time: ``ros.get_time``.

1.1.0
----------

**Added**

* Added ``set_initial_delay``, ``set_max_delay`` and ``set_max_retries``  to ``RosBridgeClientFactory`` to control reconnection parameters.
* Added ``closing`` event to ``Ros`` class that gets triggered right before closing the connection.

1.0.0
----------

**Changed**

* Changed behavior: Topics automatically reconnect when websockets is reconnected.

**Added**

* Added blocking behavior to more ROS API methods: ``ros.get_nodes`` and ``ros.get_node_details``.
* Added reconnection support to IronPython implementation of websockets.
* Added automatic topic reconnection support for both subscribers and publishers.

**Fixed**

* Fixed reconnection issues on the Twisted/Autobahn-based implementation of websockets.

0.7.1
----------

**Fixed**

* Fixed blocking service calls for Mac OS.

0.7.0
----------

**Changed**

* The non-blocking event loop runner ``run()`` now defaults to 10 seconds timeout before raising an exception.

**Added**

* Added blocking behavior to ROS API methods, e.g. ``ros.get_topics``.
* Added command-line mode to ROS API, e.g. ``roslibpy topic list``.
* Added blocking behavior to the ``Param`` class.
* Added parameter manipulation methods to ``Ros`` class: ``get_param``, ``set_param``, ``delete_param``.

0.6.0
----------

**Changed**

* For consistency, ``timeout`` parameter of ``Goal.send()`` is now expressed in **seconds**, instead of milliseconds.

**Deprecated**

* The ``timeout`` parameter of ``ActionClient()`` is ignored in favor of blocking until the connection is established.

**Fixed**

* Raise exceptions when timeouts expire on ROS connection or service calls.

**Added**

* Support for calling a function in a thread from the Ros client.
* Added implementation of a Simple Action Server.

0.5.0
----------

**Changed**

* The non-blocking event loop runner now waits for the connection to be established in order to minimize the need for ``on_ready`` handlers.

**Added**

* Support blocking and non-blocking service calls.

**Fixed**

* Fixed an internal unsubscribing issue.

0.4.1
----------

**Fixed**

* Resolve reconnection issues.

0.4.0
----------

**Added**

* Add a non-blocking event loop runner.

0.3.0
----------

**Changed**

* Unsubscribing from a listener no longer requires the original callback to be passed.

0.2.1
----------

**Fixed**

* Fix JSON serialization error on TF Client (on Python 3.x).

0.2.0
----------

**Added**

* Add support for IronPython 2.7.

**Changed**

* Handler ``on_ready`` now defaults to run the callback in thread.

**Deprecated**

* Rename ``run_event_loop`` to the more fitting ``run_forever``.

0.1.1
----------

**Fixed**

* Minimal documentation fixes.

0.1.0
----------

**Added**

* Initial version.
