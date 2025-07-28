Examples
========

Getting started with **roslibpy** is simple. The following examples will help you
on the first steps using it to connect to a ROS environment. Before you start, make sure
you have ROS and `rosbridge` running (see :ref:`ros-setup`).

These examples assume ROS is running on the same computer where you run the examples.
If that is not the case, change the ``host`` argument from ``'localhost'``
to the *IP Address* of your ROS instance.

First connection
----------------

We start importing ``roslibpy`` as follows::

    >>> import roslibpy

And we initialize the connection with::

    >>> ros = roslibpy.Ros(host='localhost', port=9090)
    >>> ros.run()

Easy, right?
Let's check the status::

    >>> ros.is_connected
    True

**Yay! Our first connection to ROS!**

Putting it all together
-----------------------

Let's build a full example into a python file. Create a file named
``ros-hello-world.py`` and paste the following content:

.. literalinclude :: files/ros-hello-world.py
   :language: python

Now run it from the command prompt typing::

    $ python ros-hello-world.py

The program will run, print once we are connected and terminate the connection.

Controlling the event loop
^^^^^^^^^^^^^^^^^^^^^^^^^^

In the previous examples, we started the ROS connection with a call to ``run()``,
which starts the event loop in the background. In some cases, we want to handle the
main event loop more explicitely in the foreground. :class:`roslibpy.Ros` provides
the method ``run_forever()`` for this purpose.

If we use this method to start the event loop, we need to setup all connection handlers
beforehand. We will use the :meth:`roslibpy.Ros.on_ready` method to do this.
We will pass a function to it, that will be invoked when the connection is ready.

The following snippet shows the same connection example above but
using ``run_forever()`` and ``on_ready``:

.. literalinclude :: files/ros-hello-world-run-forever.py
   :language: python

.. note::

    The difference between ``run()`` and ``run_forever()`` is that the former
    starts the event processing in a separate thread, while the latter
    blocks the calling thread.

Disconnecting
-------------

Once your task is done, you should disconnect cleanly from ``rosbridge``. There are two related methods available for this:

 - :meth:`roslibpy.Ros.close`: Disconnect the websocket connection. Once the connection is closed,
   it is still possible to reconnect by calling :meth:`roslibpy.Ros.connect`: again.
 - :meth:`roslibpy.Ros.terminate`: Terminate the main event loop. If the connection is still open,
   it will first close it.

.. note::

  Terminating the event loop is an irreversible action when using the ``twisted/authbahn`` loop because ``twisted``
  reactors cannot be restarted. This operation should be reserved to be executed at the very end of your program.

Reconnecting
------------

If ``rosbridge`` is not responsive when the connection is started or if an established connection drops uncleanly, ``roslibpy``
will try to reconnect automatically, and reconnect subscriber and publisher topics as well. Reconnect will be retried
with an exponential back-off.

Hello World: Topics
-------------------

The ``Hello world`` of ROS is to start two nodes that communicate using
topic subscription/publishing. The nodes (a talker and a listener) are
extremely simple but they exemplify a distributed system with communication
between two processes over the ROS infrastructure.

Writing the talker node
^^^^^^^^^^^^^^^^^^^^^^^

The following example starts a ROS node and begins to publish
messages in loop (to terminate, press ``ctrl+c``):

.. literalinclude :: files/ros-hello-world-talker.py
   :language: python

* :download:`ros-hello-world-talker.py <files/ros-hello-world-talker.py>`

Writing the listener node
^^^^^^^^^^^^^^^^^^^^^^^^^

Now let's move on to the listener side:

.. literalinclude :: files/ros-hello-world-listener.py
   :language: python

* :download:`ros-hello-world-listener.py <files/ros-hello-world-listener.py>`

Running the example
^^^^^^^^^^^^^^^^^^^

Open a command prompt and start the talker:

::

    python ros-hello-world-talker.py


Now open a second command prompt and start the listener:

::

    python ros-hello-world-listener.py


.. note::

    It is not relevant where the files are located. They can be in different
    folders or even in different computers as long as the ROS instance is the same.


Using services
--------------

Another way for nodes to communicate between each other is through ROS Services.

Services require the definition of request and response types so the following
example shows how to use an existing service called ``get_loggers``:

.. literalinclude :: files/ros-service-call-logger.py
   :language: python

* :download:`ros-service-call-logger.py <files/ros-service-call-logger.py>`

Creating services
-----------------

It is also possible to create new services, as long as the service type
definition is present in your ROS environment.

The following example shows how to create a simple service that uses
one of the standard service types defined in ROS (``std_srvs/SetBool``):

.. literalinclude :: files/ros-service.py
   :language: python

* :download:`ros-service.py <files/ros-service.py>`

Download it and run it from the command prompt typing::

    $ python ros-service.py

The service will be active while the program is running (to terminate,
press ``ctrl+c``).

Leave this service running and download and run the following service calling
code example to verify the service is working:

* :download:`ros-service-call-set-bool.py <files/ros-service-call-set-bool.py>`

Download it and run it from the command prompt typing::

    $ python ros-service-call-set-bool.py


.. note::

    Now that you have a grasp of the basics of ``roslibpy``,
    check out more details in the :ref:`ros-api-reference`.

Actions
-------

Besides Topics and Services, ROS provides **Actions**, which are intended for
long-running tasks, such as navigation, because they are non-blocking and allow
the cancellation (preempting) of an action while it is executing.

``roslibpy`` supports both consuming actions (i.e. action clients) and also
providing actions, through the :class:`roslibpy.actionlib.SimpleActionServer`.

The following examples use the **Fibonacci** action, which is defined in the
`actionlib_tutorials <http://wiki.ros.org/actionlib_tutorials>`_.

Action servers
^^^^^^^^^^^^^^

Let's start with the definition of the fibonacci server:

.. literalinclude :: files/ros-action-server.py
   :language: python

* :download:`ros-action-server.py <files/ros-action-server.py>`

Download it and run it from the command prompt typing::

    $ python ros-action-server.py

The action server will be active while the program is running (to terminate,
press ``ctrl+c``).

Leave this window running if you want to test it with the next example.

Action clients
^^^^^^^^^^^^^^

Now let's see how to write an action client for our newly created server.

The following program shows a simple action client:

.. literalinclude :: files/ros-action-client.py
   :language: python

* :download:`ros-action-client.py <files/ros-action-client.py>`

Download it and run it from the command prompt typing::

    $ python ros-action-client.py

You will immediately see all the intermediate calculations of our action server,
followed by a line indicating the resulting fibonacci sequence.

This example is very simplified and uses the :meth:`roslibpy.actionlib.Goal.wait`
function to make the code easier to read as an example. A more robust way to handle
results is to hook up to the ``result`` event with a callback.

For action clients to deal with ROS 2 action servers, check the following example: 

.. literalinclude :: files/ros2-action-client.py
   :language: python

* :download:`ros2-action-client.py <files/ros2-action-client.py>`

Querying ROS API
----------------

ROS provides an API to inspect topics, services, nodes and much more. This API can be
used programmatically from Python code, and also be invoked from the command line.

Usage from the command-line
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The command line mimics closely that of ROS itself.

The following commands are available::

    $ roslibpy topic list
    $ roslibpy topic type /rosout
    $ roslibpy topic find std_msgs/Int32
    $ roslibpy msg info rosgraph_msgs/Log

    $ roslibpy service list
    $ roslibpy service type /rosout/get_loggers
    $ roslibpy service find roscpp/GetLoggers
    $ roslibpy srv info roscpp/GetLoggers

    $ roslibpy param list
    $ roslibpy param set /foo "[\"1\", 1, 1.0]"
    $ roslibpy param get /foo
    $ roslibpy param delete /foo

Usage from Python code
^^^^^^^^^^^^^^^^^^^^^^

And conversely, the following methods allow to query the ROS API from Python code.

Topics
""""""

* :meth:`roslibpy.Ros.get_topics`
* :meth:`roslibpy.Ros.get_topic_type`
* :meth:`roslibpy.Ros.get_topics_for_type`
* :meth:`roslibpy.Ros.get_message_details`

Services
""""""""

* :meth:`roslibpy.Ros.get_services`
* :meth:`roslibpy.Ros.get_service_type`
* :meth:`roslibpy.Ros.get_services_for_type`
* :meth:`roslibpy.Ros.get_service_request_details`
* :meth:`roslibpy.Ros.get_service_response_details`

Params
""""""

* :meth:`roslibpy.Ros.get_params`
* :meth:`roslibpy.Ros.get_param`
* :meth:`roslibpy.Ros.set_param`
* :meth:`roslibpy.Ros.delete_param`

Time
""""

* :meth:`roslibpy.Ros.get_time`

Advanced examples
-----------------

The following list is a compilation of more elaborate examples of the usage of ``roslibpy``.

We encourage everyone to submit suggestions for new examples, either send a pull request or request it via the issue tracker.

.. toctree::
    :maxdepth: 2
    :glob:

    examples/*
