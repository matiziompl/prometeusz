import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "/workspace/prometeusz")
from backend.app import app, MAX_CONCURRENT_PTY, MAX_WS_MESSAGE_SIZE, active_pty_sessions
from backend.sessions import validate_conversation_id, validate_filename

client = TestClient(app)


def test_validation_helpers():
    # Valid conversation IDs
    assert validate_conversation_id("session-123_abc") == "session-123_abc"
    assert validate_conversation_id("9bc35b72-05de-41ae-91e8-8867c899f985")

    # Invalid conversation IDs (traversal, special chars, flag injection)
    with pytest.raises(ValueError):
        validate_conversation_id("../../etc/passwd")
    with pytest.raises(ValueError):
        validate_conversation_id("-flag-injection")
    with pytest.raises(ValueError):
        validate_conversation_id("session;rm -rf")
    with pytest.raises(ValueError):
        validate_conversation_id("")

    # Valid filenames
    assert validate_filename("report.md") == "report.md"
    assert validate_filename("artifact_1.json") == "artifact_1.json"

    # Invalid filenames (traversal)
    with pytest.raises(ValueError):
        validate_filename("../secret.txt")
    with pytest.raises(ValueError):
        validate_filename("/etc/shadow")
    with pytest.raises(ValueError):
        validate_filename("dir\\file.txt")


def test_api_session_details_path_traversal():
    # Path traversal attempts must return 400 Bad Request or 404 from URL router normalization
    resp = client.get("/api/sessions/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)

    # Flag injection attempt
    resp2 = client.get("/api/sessions/--help")
    assert resp2.status_code == 400

    # Special character injection
    resp3 = client.get("/api/sessions/session;id")
    assert resp3.status_code == 400


def test_api_session_artifacts_path_traversal():
    resp = client.get("/api/sessions/..%2F..%2Fetc/artifacts")
    assert resp.status_code in (400, 404)

    resp2 = client.get("/api/sessions/session;id/artifacts")
    assert resp2.status_code == 400


def test_api_artifact_content_path_traversal():
    # Traversal in session_id
    resp = client.get("/api/sessions/..%2F..%2Fetc/artifacts/passwd")
    assert resp.status_code in (400, 404)

    # Traversal in filename
    resp2 = client.get("/api/sessions/valid-session/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert resp2.status_code in (400, 404)

    # Invalid filename characters
    resp3 = client.get("/api/sessions/valid-session/artifacts/bad;filename")
    assert resp3.status_code == 400


import asyncio
from unittest.mock import patch
from tests.mock_pty import MockPTYSession


def test_websocket_pty_session_id_sanitization():
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/pty?session_id=--dangerously-skip-permissions"):
            pass


def test_websocket_pty_cswsh_protection():
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/pty", headers={"Origin": "https://evil-attacker.com"}):
            pass


def test_websocket_pty_payload_limit():
    with patch("backend.app.PTYSession", MockPTYSession):
        with client.websocket_connect("/ws/pty") as ws:
            huge_payload = "a" * (MAX_WS_MESSAGE_SIZE + 1024)
            ws.send_text(huge_payload)
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "exceeds limit" in msg["message"]


def test_websocket_pty_malformed_json_resilience():
    with patch("backend.app.PTYSession", MockPTYSession):
        with client.websocket_connect("/ws/pty") as ws:
            ws.send_text("12345")
            ws.send_text("[1, 2, 3]")
            ws.send_text("invalid json string {")
            ws.send_json({"type": "stdin", "data": "echo TEST_OK\n"})
            msg = ws.receive_json()
            assert msg["type"] == "stdout"


def test_websocket_pty_concurrency_limit():
    with patch("backend.app.PTYSession", MockPTYSession):
        active_pty_sessions.clear()
        connections = []
        try:
            for _ in range(MAX_CONCURRENT_PTY):
                ws = client.websocket_connect("/ws/pty")
                ws.__enter__()
                connections.append(ws)

            with pytest.raises(Exception):
                with client.websocket_connect("/ws/pty"):
                    pass
        finally:
            for ws in connections:
                try:
                    ws.__exit__(None, None, None)
                except Exception:
                    pass
            active_pty_sessions.clear()
