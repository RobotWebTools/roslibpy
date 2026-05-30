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


def test_asyncio_protocol_sends_text_frames():
    asyncio = pytest.importorskip("asyncio")

    from roslibpy.comm.comm_asyncio import AsyncioRosBridgeProtocol

    class WebSocket(object):
        def __init__(self):
            self.payload = None

        async def send(self, payload):
            self.payload = payload

    async def run_test():
        websocket = WebSocket()
        protocol = AsyncioRosBridgeProtocol(object(), websocket)

        await protocol._send_async(b'{"op": "call_service"}')
        protocol._stop_sender()
        return websocket.payload

    payload = asyncio.run(run_test())

    assert payload == '{"op": "call_service"}'
    assert isinstance(payload, str)
