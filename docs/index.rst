============================
roslibpy: ROS Bridge library
============================

.. start-badges

.. image:: https://readthedocs.org/projects/roslibpy/badge/?style=flat
    :target: https://roslibpy.readthedocs.io/en/latest/
    :alt: Documentation Status

.. image:: https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-brightgreen.svg
    :target: https://roslibpy-docs-zh.readthedocs.io
    :alt: Documentation: Chinese translation

.. image:: https://github.com/gramaziokohler/roslibpy/workflows/build/badge.svg
    :target: https://github.com/gramaziokohler/roslibpy/actions
    :alt: Github Actions CI Build Status

.. image:: https://img.shields.io/github/license/gramaziokohler/roslibpy.svg
    :target: https://pypi.python.org/pypi/roslibpy
    :alt: License

.. image:: https://img.shields.io/pypi/v/roslibpy.svg
    :target: https://pypi.python.org/pypi/roslibpy
    :alt: PyPI Package latest release

.. image:: https://anaconda.org/conda-forge/roslibpy/badges/version.svg
    :target: https://anaconda.org/conda-forge/roslibpy

.. image:: https://img.shields.io/pypi/implementation/roslibpy.svg
    :target: https://pypi.python.org/pypi/roslibpy
    :alt: Supported implementations

.. end-badges

**Python ROS Bridge library** allows to use Python and IronPython to interact
with `ROS <http://www.ros.org>`_, the open-source robotic middleware.
It uses WebSockets to connect to
`rosbridge 2.0 <http://wiki.ros.org/rosbridge_suite>`_ and provides publishing,
subscribing, service calls, actionlib, TF, and other essential ROS functionality.

Unlike the `rospy <http://wiki.ros.org/rospy>`_ library, this does not require a
local ROS environment, allowing usage from platforms other than Linux.

The API of **roslibpy** is modeled to closely match that of `roslibjs <http://wiki.ros.org/roslibjs>`_.

ROS 1 is fully supported. ROS 2 support is still in progress.

========
Contents
========

.. toctree::
   :maxdepth: 2

   readme
   examples
   reference/index
   contributing
   authors
   changelog

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

