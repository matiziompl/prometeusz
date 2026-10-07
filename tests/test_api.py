import asyncio
import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

sys.path.insert(0, "/workspace/prometeusz")
from backend.app import app
from tests.mock_pty import MockPTYSession

client = TestClient(app)


def test_api_metrics():
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "cpu_percent" in data
    assert "memory_percent" in data
    assert "disk_percent" in data


def test_api_slash_commands():
    response = client.get("/api/slash-commands")
    assert response.status_code == 200
    cmds = response.json()
    assert isinstance(cmds, list)
    cmd_names = [c["command"] for c in cmds]
    assert "/goal" in cmd_names
    assert "/plan" in cmd_names


def test_api_sessions():
    response = client.get("/api/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert isinstance(sessions, list)


def test_api_nonexistent_session():
    response = client.get("/api/sessions/non-existent-id-12345")
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "non-existent-id-12345"
    assert data["messages"] == []


def test_websocket_pty_connection():
    with patch("backend.app.PTYSession", MockPTYSession):
        with client.websocket_connect("/ws/pty") as ws:
            ws.send_json({"type": "resize", "rows": 24, "cols": 80})
            ws.send_json({"type": "stdin", "data": "echo PROMETEUSZ_OK\n"})
            msg = ws.receive_json()
            assert msg["type"] == "stdout"
            assert isinstance(msg["data"], str)


def test_api_fork_session(tmp_path, monkeypatch):
    import sqlite3
    from backend.sessions import get_antigravity_dir

    monkeypatch.setenv("ANTIGRAVITY_CLI_DIR", str(tmp_path))
    db_path = tmp_path / "conversation_summaries.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            title TEXT,
            preview TEXT,
            step_count INTEGER,
            last_modified_time TIMESTAMP,
            status TEXT
        )
        """
    )
    conn.execute("INSERT INTO conversation_summaries VALUES ('api-test-orig', 'Sesja testowa', 'Podgląd', 2, '2026-10-06 10:00:00', 'IDLE')")
    conn.commit()
    conn.close()

    response = client.post("/api/sessions/api-test-orig/fork")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "conversation_id" in data
    assert data["conversation_id"] != "api-test-orig"
    assert "Fork" in data["title"]


def test_api_fork_nonexistent_session(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_CLI_DIR", str(tmp_path))
    response = client.post("/api/sessions/nonexistent-session-id/fork")
    assert response.status_code == 404

