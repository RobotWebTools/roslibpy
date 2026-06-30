import threading
import time

import pytest

from roslibpy import Ros

asyncio = pytest.importorskip("asyncio")
websockets = pytest.importorskip("websockets")

headers = {"cookie": "token=rosbridge", "authorization": "Some auth"}


async def websocket_handler(websocket, path):
    request_headers = websocket.request_headers
    for key, value in headers.items():
        assert request_headers.get(key) == value, f"Header {key} did not match expected value {value}"
    await websocket.close()


async def start_server(stop_event):
    server = await websockets.serve(websocket_handler, "127.0.0.1", 9000)
    await stop_event.wait()
    server.close()
    await server.wait_closed()


def run_server(stop_event):
    asyncio.run(start_server(stop_event))


def run_client(ros_transport):
    client = Ros("127.0.0.1", 9000, headers=headers, transport=ros_transport)
    client.run()
    client.close()


def test_websocket_headers(ros_transport):
    server_stop_event = asyncio.Event()
    stop_event = threading.Event()

    server_thread = threading.Thread(target=run_server, args=(server_stop_event,))
    server_thread.start()

    time.sleep(1)  # Give the server time to start

    client_thread = threading.Thread(target=run_client, args=(ros_transport,))
    client_thread.start()

    # Wait for the client thread to finish or timeout after 10 seconds
    client_thread.join(timeout=10)

    if client_thread.is_alive():
        raise Exception("Client did not terminate as expected")

    # Signal the server to stop
    server_stop_event.set()
    server_thread.join(timeout=10)

    if server_thread.is_alive():
        raise Exception("Server did not stop as expected")

    stop_event.set()
