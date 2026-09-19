"""Tests for the IPC protocol (``pdo.protocol.messages``)."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from pdo.exceptions import ProtocolError
from pdo.protocol.messages import Request, Response, receive_message, send_message


class TestRequest:
    def test_round_trip(self) -> None:
        req = Request(
            action="import",
            payload={"csv_path": "/tmp/data.csv"},
            auth_token="test-token",
        )
        raw = req.to_json()
        restored = Request.from_json(raw)
        assert restored.action == "import"
        assert restored.payload["csv_path"] == "/tmp/data.csv"
        assert restored.auth_token == "test-token"

    def test_from_json_missing_action(self) -> None:
        with pytest.raises(ProtocolError, match="action"):
            Request.from_json('{"payload": {}}')

    def test_from_json_invalid_json(self) -> None:
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            Request.from_json("not valid json {{{")

    def test_default_payload(self) -> None:
        req = Request(action="status")
        assert req.payload == {}
        restored = Request.from_json(req.to_json())
        assert restored.payload == {}


class TestResponse:
    def test_round_trip_success(self) -> None:
        resp = Response(success=True, data={"count": 42})
        raw = resp.to_json()
        restored = Response.from_json(raw)
        assert restored.success is True
        assert restored.data["count"] == 42
        assert restored.error is None

    def test_round_trip_error(self) -> None:
        resp = Response(success=False, error="Something broke")
        restored = Response.from_json(resp.to_json())
        assert restored.success is False
        assert restored.error == "Something broke"

    def test_from_json_missing_success(self) -> None:
        with pytest.raises(ProtocolError, match="success"):
            Response.from_json('{"data": {}}')

    def test_from_json_invalid_json(self) -> None:
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            Response.from_json("broken!!!")


class TestSocketHelpers:
    def test_send_and_receive(self) -> None:
        """Send a Request through a real socket pair and read it back."""
        client, server = socket.socketpair()

        received: list[dict] = []

        def _server_thread() -> None:
            try:
                msg = receive_message(server)
                received.append(msg)
            finally:
                server.close()

        t = threading.Thread(target=_server_thread)
        t.start()

        send_message(client, Request(action="ping"))
        client.close()

        t.join(timeout=2.0)

        assert len(received) == 1
        assert received[0]["action"] == "ping"

    def test_receive_empty_connection(self) -> None:
        """Receive should raise on an immediately closed connection."""
        client, server = socket.socketpair()

        error_raised = threading.Event()

        def _server_thread() -> None:
            try:
                receive_message(server)
            except ProtocolError:
                error_raised.set()
            finally:
                server.close()

        t = threading.Thread(target=_server_thread)
        t.start()

        client.close()  # immediately close

        t.join(timeout=2.0)
        assert error_raised.is_set()

    def test_receive_deadline_rejects_incomplete_client(self) -> None:
        """A client cannot hold the daemon's only request thread indefinitely."""
        client, server = socket.socketpair()
        try:
            client.sendall(b'{"action":')
            with pytest.raises(TimeoutError):
                receive_message(server, deadline=time.monotonic() + 0.05)
        finally:
            client.close()
            server.close()
