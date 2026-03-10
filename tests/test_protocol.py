"""Tests for the IPC protocol (``pdo.protocol.messages``)."""

from __future__ import annotations

import os
import socket
import tempfile
import threading

import pytest

from pdo.exceptions import ProtocolError
from pdo.protocol.messages import Request, Response, receive_message, send_message


class TestRequest:
    def test_round_trip(self) -> None:
        req = Request(action="import", payload={"csv_path": "/tmp/data.csv"})
        raw = req.to_json()
        restored = Request.from_json(raw)
        assert restored.action == "import"
        assert restored.payload["csv_path"] == "/tmp/data.csv"

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
        fd, sock_path = tempfile.mkstemp(suffix=".sock", dir="/tmp")
        os.close(fd)
        os.unlink(sock_path)  # mkstemp creates the file; we just need the name
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(1)

        received: list[dict] = []

        def _server_thread() -> None:
            conn, _ = server.accept()
            try:
                msg = receive_message(conn)
                received.append(msg)
            finally:
                conn.close()

        t = threading.Thread(target=_server_thread)
        t.start()

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        send_message(client, Request(action="ping"))
        client.close()

        t.join(timeout=2.0)
        server.close()
        os.unlink(sock_path)

        assert len(received) == 1
        assert received[0]["action"] == "ping"

    def test_receive_empty_connection(self) -> None:
        """Receive should raise on an immediately closed connection."""
        fd, sock_path = tempfile.mkstemp(suffix=".sock", dir="/tmp")
        os.close(fd)
        os.unlink(sock_path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(1)

        error_raised = threading.Event()

        def _server_thread() -> None:
            conn, _ = server.accept()
            try:
                receive_message(conn)
            except ProtocolError:
                error_raised.set()
            finally:
                conn.close()

        t = threading.Thread(target=_server_thread)
        t.start()

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        client.close()  # immediately close

        t.join(timeout=2.0)
        server.close()
        os.unlink(sock_path)
        assert error_raised.is_set()
