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

The API of **roslibpy** is modeled to closely match that of `roslibjs`_.

ROS 1 is fully supported. ROS 2 support is still in progress.


Main features
-------------

* Topic publishing and subscribing.
* Service calls (client).
* Service advertisement (server).
* ROS parameter management (get/set/delete).
* ROS API services for getting ROS meta-information.
* Actionlib support for interfacing with preemptable tasks.
* TF Client via the ``tf2_web_republisher``.

**Roslibpy** runs on Python 3.x and IronPython 2.7.


Installation
------------

To install **roslibpy**, simply use ``pip``::

    pip install roslibpy

For IronPython, the ``pip`` command is slightly different::

    ipy -X:Frames -m pip install --user roslibpy

Remember that you will need a working ROS setup including the
**rosbridge server** and **TF2 web republisher** accessible within your network.


Documentation
-------------

The full documentation, including examples and API reference
is available on `readthedocs <https://roslibpy.readthedocs.io/>`_.


Contributing
------------

Make sure you setup your local development environment correctly:

* Clone the `roslibpy <https://github.com/gramaziokohler/roslibpy>`_ repository.
* Create a virtual environment.
* Install development dependencies:

::

    pip install -r requirements-dev.txt

**You're ready to start coding!**

During development, use `pyinvoke <http://docs.pyinvoke.org/>`_ tasks on the
command prompt to ease recurring operations:

* ``invoke clean``: Clean all generated artifacts.
* ``invoke check``: Run various code and documentation style checks.
* ``invoke docs``: Generate documentation.
* ``invoke test``: Run all tests and checks in one swift command.
* ``invoke``: Show available tasks.

For more details, check the *Contributor's Guide* available as part of `the documentation <https://roslibpy.readthedocs.io/>`_.

The default branch was recently renamed to `main`. If you've already cloned this repository,
you'll need to update your local repository structure with the following lines:

::

    git branch -m master main
    git fetch origin
    git branch -u origin/main main


Releasing this project
----------------------

Ready to release a new version **roslibpy**? Here's how to do it:

* We use `semver <http://semver.org/>`_, i.e. we bump versions as follows:

  * ``patch``: bugfixes.
  * ``minor``: backwards-compatible features added.
  * ``major``: backwards-incompatible changes.

* Update the ``CHANGELOG.rst`` with all novelty!
* Create a release branch and prepare the release:

::

    git checkout -b release-x.y.z
    invoke release [patch|minor|major]

* This will run tests, bump the version, create a git tag, and commit changes.
* Push the release branch and tag, then create a Pull Request to ``main``:

::

    git push origin release-x.y.z
    git push origin --tags

* Once the PR is reviewed and merged into ``main``, the release workflow will automatically publish to PyPI.
* The workflow verifies the tag is on the ``main`` branch before publishing, preventing accidental releases from feature branches.


Credits
-------

This library is based on `roslibjs`_ and to a
large extent, it is a line-by-line port to Python, changing only where a more
idiomatic form makes sense, so a huge part of the credit goes to the
`roslibjs authors <https://github.com/RobotWebTools/roslibjs/blob/develop/AUTHORS.md>`_.

.. _roslibjs: http://wiki.ros.org/roslibjs
