import os
import sys

import pytest

from roslibpy import Ros, set_default_transport
from roslibpy.comm import (
    TRANSPORT_ASYNCIO,
    TRANSPORT_CLI,
    TRANSPORT_TWISTED,
    _resolve_transport,
)

PLATFORM_DEFAULT = TRANSPORT_CLI if sys.platform == "cli" else TRANSPORT_TWISTED

# The transport this process is dedicated to. Autobahn's txaio binds a single
# async framework per process, so importing ``comm_asyncio`` (which loads
# ``autobahn.asyncio``) must be avoided unless this is the asyncio process —
# otherwise it would poison a twisted-designated process. CI runs the suite
# once per transport.
ACTIVE_TRANSPORT = TRANSPORT_CLI if sys.platform == "cli" else os.environ.get("ROSLIBPY_TRANSPORT", TRANSPORT_TWISTED)


@pytest.fixture(autouse=True)
def reset_transport(monkeypatch):
    monkeypatch.delenv("ROSLIBPY_TRANSPORT", raising=False)
    set_default_transport(PLATFORM_DEFAULT)
    yield
    set_default_transport(PLATFORM_DEFAULT)


def test_transport_can_be_selected_from_environment(monkeypatch):
    monkeypatch.setenv("ROSLIBPY_TRANSPORT", TRANSPORT_ASYNCIO)

    assert _resolve_transport() == TRANSPORT_ASYNCIO


def test_transport_can_be_selected_as_process_default():
    set_default_transport(TRANSPORT_ASYNCIO)

    assert _resolve_transport() == TRANSPORT_ASYNCIO


def test_explicit_transport_takes_precedence(monkeypatch):
    monkeypatch.setenv("ROSLIBPY_TRANSPORT", TRANSPORT_TWISTED)
    set_default_transport(TRANSPORT_TWISTED)

    assert _resolve_transport(TRANSPORT_ASYNCIO) == TRANSPORT_ASYNCIO


def test_ros_passes_explicit_transport_to_factory_selector(monkeypatch):
    selected = []

    class Factory(object):
        @classmethod
        def create_url(cls, host, port=None, is_secure=False):
            return "ws://127.0.0.1:9090"

        def __init__(self, url, headers=None):
            self.is_connected = False

        def connect(self):
            pass

        def on_ready(self, callback):
            pass

    def select_factory(transport):
        selected.append(transport)
        return Factory

    monkeypatch.setattr("roslibpy.ros.select_factory", select_factory)

    Ros("127.0.0.1", 9090, transport=TRANSPORT_ASYNCIO)

    assert selected == [TRANSPORT_ASYNCIO]


def _import_asyncio_protocol():
    """Import the asyncio protocol, skipping unless this process is dedicated to
    the asyncio transport.

    Importing ``comm_asyncio`` loads ``autobahn.asyncio`` and locks this
    process's txaio framework to asyncio, so we must not do it in a
    twisted-designated process."""
    if ACTIVE_TRANSPORT != TRANSPORT_ASYNCIO:
        pytest.skip("asyncio protocol tests run only when ROSLIBPY_TRANSPORT=asyncio")
    try:
        from roslibpy.comm.comm_asyncio import AsyncioRosBridgeProtocol
    except (ImportError, RuntimeError) as exc:
        pytest.skip("asyncio transport unavailable in this process: %s" % exc)
    return AsyncioRosBridgeProtocol


def test_asyncio_protocol_sends_text_frames():
    AsyncioRosBridgeProtocol = _import_asyncio_protocol()

    # Build the protocol without going through autobahn's connection setup; we
    # only exercise the ROS-bridge send path here.
    protocol = AsyncioRosBridgeProtocol.__new__(AsyncioRosBridgeProtocol)

    sent = []
    protocol.sendMessage = lambda payload, isBinary=False: sent.append((payload, isBinary))

    protocol._send(b'{"op": "call_service"}')

    assert sent == [(b'{"op": "call_service"}', False)]


def test_asyncio_protocol_send_message_is_thread_safe():
    AsyncioRosBridgeProtocol = _import_asyncio_protocol()

    scheduled = []

    class FakeLoop(object):
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, fn, *args):
            scheduled.append((fn, args))

    class FakeManager(object):
        loop = FakeLoop()

    class FakeFactory(object):
        manager = FakeManager()

    protocol = AsyncioRosBridgeProtocol.__new__(AsyncioRosBridgeProtocol)
    protocol.factory = FakeFactory()

    protocol.send_message(b'{"op": "call_service"}')

    assert len(scheduled) == 1
    fn, args = scheduled[0]
    assert fn == protocol._send
    assert args == (b'{"op": "call_service"}',)
