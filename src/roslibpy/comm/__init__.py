"""Transport selection for the ROS bridge connection.

Three transports are available:

* ``twisted``: default. Built on autobahn + twisted. The historical
  implementation.
* ``asyncio``: opt-in (2.1+). Built on Autobahn's asyncio integration (the
  same Autobahn WebSocket stack as ``twisted``, running on an asyncio event
  loop). Cleaner per-test loop isolation; no extra dependencies.
* ``cli``: IronPython only (auto-selected on ``sys.platform == "cli"``).

Selection precedence (highest → lowest):

1. ``transport=`` kwarg on ``Ros`` (per-instance).
2. ``ROSLIBPY_TRANSPORT`` environment variable.
3. Module-level default set via ``roslibpy.set_default_transport(...)``.
4. Platform default: ``cli`` on IronPython, ``twisted`` elsewhere.
"""

import os
import sys

from .comm import RosBridgeException, RosBridgeProtocol

__all__ = [
    "RosBridgeException",
    "RosBridgeProtocol",
    "RosBridgeClientFactory",
    "select_factory",
    "set_default_transport",
    "TRANSPORT_TWISTED",
    "TRANSPORT_ASYNCIO",
    "TRANSPORT_CLI",
]

TRANSPORT_TWISTED = "twisted"
TRANSPORT_ASYNCIO = "asyncio"
TRANSPORT_CLI = "cli"

_VALID_TRANSPORTS = (TRANSPORT_TWISTED, TRANSPORT_ASYNCIO, TRANSPORT_CLI)
_PLATFORM_DEFAULT = TRANSPORT_CLI if sys.platform == "cli" else TRANSPORT_TWISTED
_DEFAULT_TRANSPORT = _PLATFORM_DEFAULT


def set_default_transport(name):
    """Set the process-wide default transport.

    Args:
        name (str): One of ``"twisted"``, ``"asyncio"``, ``"cli"``.

    Raises:
        ValueError: If ``name`` is not a known transport.
    """
    global _DEFAULT_TRANSPORT
    if name not in _VALID_TRANSPORTS:
        raise ValueError("Unknown transport %r; expected one of %s" % (name, _VALID_TRANSPORTS))
    _DEFAULT_TRANSPORT = name


def _resolve_transport(explicit=None):
    """Apply the precedence rules to land on a single transport name."""
    if explicit is not None:
        if explicit not in _VALID_TRANSPORTS:
            raise ValueError("Unknown transport %r; expected one of %s" % (explicit, _VALID_TRANSPORTS))
        return explicit
    env_choice = os.environ.get("ROSLIBPY_TRANSPORT")
    if env_choice:
        if env_choice not in _VALID_TRANSPORTS:
            raise ValueError("Unknown ROSLIBPY_TRANSPORT=%r; expected one of %s" % (env_choice, _VALID_TRANSPORTS))
        return env_choice
    return _DEFAULT_TRANSPORT


def _transport_conflict_error(requested, cause):
    """Build a clear error for the txaio single-framework-per-process limit.

    The ``twisted`` and ``asyncio`` transports both build on Autobahn, whose
    ``txaio`` layer binds a single async framework (Twisted *or* asyncio) per
    Python process. Selecting one after the other has already been activated
    surfaces as a ``RuntimeError`` from deep inside ``txaio``; we translate it
    into actionable guidance.
    """
    other = TRANSPORT_ASYNCIO if requested == TRANSPORT_TWISTED else TRANSPORT_TWISTED
    return RuntimeError(
        "Cannot activate the %r transport: the %r transport is already in use "
        "in this process. Both build on Autobahn, whose txaio layer binds a "
        "single async framework per process, so they are mutually exclusive. "
        "Select one transport per process (e.g. via the ROSLIBPY_TRANSPORT "
        "environment variable or roslibpy.set_default_transport()), and use "
        "separate processes if you need both. Original error: %s" % (requested, other, cause)
    )


def select_factory(transport=None):
    """Return the factory class for the requested (or resolved) transport.

    The transport modules are imported lazily so a process that never uses the
    asyncio transport never imports ``autobahn.asyncio``, and a process that
    never uses the twisted transport never imports ``twisted``. This laziness
    also matters because the two Autobahn-based transports cannot coexist in a
    single process (see :func:`_transport_conflict_error`).

    Args:
        transport (str, optional): One of ``"twisted"``, ``"asyncio"``,
            ``"cli"``. If ``None``, applies the precedence rules described in
            the module docstring.

    Returns:
        The factory class to use for new ``Ros`` instances.

    Raises:
        RuntimeError: If the requested Autobahn-based transport conflicts with
            one already activated in this process.
    """
    name = _resolve_transport(transport)
    if name == TRANSPORT_CLI:
        from .comm_cli import CliRosBridgeClientFactory

        return CliRosBridgeClientFactory
    if name == TRANSPORT_ASYNCIO:
        try:
            from .comm_asyncio import AsyncioRosBridgeClientFactory
        except RuntimeError as cause:  # txaio already bound to twisted
            raise _transport_conflict_error(TRANSPORT_ASYNCIO, cause)

        return AsyncioRosBridgeClientFactory

    # Fallback to default
    try:
        from .comm_autobahn import AutobahnRosBridgeClientFactory
    except RuntimeError as cause:  # txaio already bound to asyncio
        raise _transport_conflict_error(TRANSPORT_TWISTED, cause)

    return AutobahnRosBridgeClientFactory


def __getattr__(name):
    # ``RosBridgeClientFactory`` remains a module-level binding for
    # back-compatibility, but is resolved lazily via PEP 562 so that merely
    # importing roslibpy does not import a transport — and, through Autobahn's
    # txaio, irreversibly lock the process to a single async framework before
    # the user has had a chance to choose one.
    if name == "RosBridgeClientFactory":
        return select_factory()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
