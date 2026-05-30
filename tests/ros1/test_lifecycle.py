"""Lifecycle regression tests for the 2.1 fixes.

Targets bugs that emerged from downstream pytest sessions (``compas_fab``)
where many sequential ``Ros`` instances are constructed, run, and closed
in the same Python process.

If these tests flake, the corresponding fix is regressing — diagnose,
don't retry-loop.
"""

from __future__ import print_function

from roslibpy import Ros

HOST = "127.0.0.1"
PORT = 9090
URL = "ws://%s:%d" % (HOST, PORT)


def test_log_observer_does_not_leak():
    """Constructing many ``Ros`` instances must not leak twisted log observers.

    Before A1 every ``TwistedEventLoopManager.__init__`` (created lazily
    one-per-``Ros``) called ``PythonLoggingObserver().start()`` and never
    cleaned up unless ``manager.terminate()`` was explicitly called.
    Downstream wrappers (compas_fab's ``RosClient.__exit__``) call
    ``close()``, not ``terminate()`` — by design, since ``terminate()``
    stops the reactor permanently. So observers piled up forever.

    After A1 there's exactly one process-wide observer regardless of how
    many ``Ros()`` instances come and go.
    """
    from twisted.logger import globalLogPublisher

    initial = len(list(globalLogPublisher._observers))

    for _ in range(10):
        ros = Ros(URL)
        ros.run()
        ros.close()

    final = len(list(globalLogPublisher._observers))
    # Allow a single-observer drift in case the very first cycle is the one
    # that registers the singleton. The leak case grows by len(cycles).
    assert final - initial <= 1, (
        "Leaked %d twisted log observers across 10 lifecycle cycles "
        "(expected at most 1)" % (final - initial)
    )


