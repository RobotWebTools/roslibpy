"""Transport selection for the ROS bridge connection.

Three transports are available:

* ``twisted``: default. Built on autobahn + twisted. The historical
  implementation.
* ``asyncio``: opt-in (2.1+). Built on the ``websockets`` library. Cleaner
  per-test loop isolation; requires ``pip install roslibpy[asyncio]``.
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
            raise ValueError(
                "Unknown ROSLIBPY_TRANSPORT=%r; expected one of %s" % (env_choice, _VALID_TRANSPORTS)
            )
        return env_choice
    return _DEFAULT_TRANSPORT


def select_factory(transport=None):
    """Return the factory class for the requested (or resolved) transport.

    The optional dependencies are imported lazily so a process that never uses
    the asyncio transport never imports ``websockets``, and a process that
    never uses the twisted transport never imports ``twisted``.

    Args:
        transport (str, optional): One of ``"twisted"``, ``"asyncio"``,
            ``"cli"``. If ``None``, applies the precedence rules described in
            the module docstring.

    Returns:
        The factory class to use for new ``Ros`` instances.
    """
    name = _resolve_transport(transport)
    if name == TRANSPORT_CLI:
        from .comm_cli import CliRosBridgeClientFactory

        return CliRosBridgeClientFactory
    if name == TRANSPORT_ASYNCIO:
        from .comm_asyncio import AsyncioRosBridgeClientFactory

        return AsyncioRosBridgeClientFactory

    # Fallback to default
    from .comm_autobahn import AutobahnRosBridgeClientFactory

    return AutobahnRosBridgeClientFactory


# `RosBridgeClientFactory` remains a module-level binding for back-compatibility
RosBridgeClientFactory = select_factory()
