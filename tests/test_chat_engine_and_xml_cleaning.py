import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import app, active_pty_sessions
from backend.sessions import clean_transcript_xml, get_session_details, get_sessions

client = TestClient(app)


def test_clean_transcript_xml_unit():
    # 1. Full AGY wrapper with metadata and settings change
    raw = (
        "<USER_REQUEST>\n"
        "przeanalizuj prometeusz_todo.txt i jak rodzielić te 7 zadań na kilka konwersacji\n"
        "</USER_REQUEST>\n"
        "<ADDITIONAL_METADATA>\n"
        "The current local time is: 2026-10-06T18:43:53+02:00.\n"
        "</ADDITIONAL_METADATA>\n"
        "<USER_SETTINGS_CHANGE>\n"
        "The user changed setting `Model Selection` from None to Gemini 3.8 Flash (High).\n"
        "</USER_SETTINGS_CHANGE>"
    )
    cleaned = clean_transcript_xml(raw)
    assert cleaned == "przeanalizuj prometeusz_todo.txt i jak rodzielić te 7 zadań na kilka konwersacji"
    assert "<USER_REQUEST>" not in cleaned
    assert "</USER_REQUEST>" not in cleaned
    assert "<ADDITIONAL_METADATA>" not in cleaned
    assert "<USER_SETTINGS_CHANGE>" not in cleaned

    # 2. Plain prompt without tags
    assert clean_transcript_xml("Zwykłe zapytanie użytkownika") == "Zwykłe zapytanie użytkownika"

    # 3. Only metadata without USER_REQUEST tag
    raw_meta_only = (
        "Cześć model\n"
        "<ADDITIONAL_METADATA>\n"
        "time: 12345\n"
        "</ADDITIONAL_METADATA>"
    )
    assert clean_transcript_xml(raw_meta_only) == "Cześć model"

    # 4. Empty or None
    assert clean_transcript_xml("") == ""
    assert clean_transcript_xml(None) == ""


def test_session_details_cleans_xml_via_testclient(tmp_path, monkeypatch):
    """Verify FastAPI TestClient returns clean prompt in /api/sessions/{session_id}."""
    monkeypatch.setenv("ANTIGRAVITY_CLI_DIR", str(tmp_path))

    conv_id = "test-conv-xml-clean"
    logs_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = logs_dir / "transcript.jsonl"

    raw_user_msg = (
        "<USER_REQUEST>\n"
        "Napisz prosty serwer HTTP w Pythonie\n"
        "</USER_REQUEST>\n"
        "<ADDITIONAL_METADATA>\n"
        "The current local time is: 2026-10-06T20:00:00+02:00.\n"
        "</ADDITIONAL_METADATA>\n"
        "<USER_SETTINGS_CHANGE>\n"
        "Model changed\n"
        "</USER_SETTINGS_CHANGE>"
    )

    records = [
        {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": raw_user_msg, "created_at": "2026-10-06T20:00:00Z"},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Oto serwer HTTP...", "created_at": "2026-10-06T20:00:01Z"}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    resp = client.get(f"/api/sessions/{conv_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert len(data["messages"]) == 2

    user_msg = data["messages"][0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Napisz prosty serwer HTTP w Pythonie"
    assert "<USER_REQUEST>" not in user_msg["content"]
    assert "<ADDITIONAL_METADATA>" not in user_msg["content"]
    assert "<USER_SETTINGS_CHANGE>" not in user_msg["content"]


def test_chat_stream_status_ready_and_text_delta(monkeypatch):
    """Test that /api/chat yields status ready and immediately streams text delta."""
    from backend.chat_engine import stream_agy_chat
    import asyncio

    class FakeStdout:
        def __init__(self):
            self.lines = [b"Oto natychmiastowa odpowiedz modelu!\n"]
        async def readline(self):
            if self.lines:
                return self.lines.pop(0)
            return b""

    class FakeStderr:
        async def read(self):
            return b""

    class DummyProc:
        def __init__(self):
            self.returncode = 0
            self.pid = 1234
            self.stdout = FakeStdout()
            self.stderr = FakeStderr()

        async def wait(self):
            return 0

    dummy_proc = DummyProc()

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        # Verify stdin=DEVNULL was used
        assert kwargs.get("stdin") == asyncio.subprocess.DEVNULL
        return dummy_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/agy")
    monkeypatch.setattr("os.path.exists", lambda x: True)
    monkeypatch.setattr("os.access", lambda x, y: True)

    resp = client.post("/api/chat", json={"prompt": "Powiedz czesc"})
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]

    types = [item.get("type") for item in lines]
    assert "init" in types
    assert "text_delta" in types
    assert "done" in types

    # Status must change to 'ready' via tool_update
    tool_updates = [item for item in lines if item.get("type") == "tool_update"]
    assert len(tool_updates) > 0
    ready_updates = [tu for tu in tool_updates if tu.get("state") == "ready"]
    assert len(ready_updates) > 0

    # Text delta must contain the model response
    deltas = [item.get("delta") for item in lines if item.get("type") == "text_delta"]
    assert any("Oto natychmiastowa odpowiedz modelu!" in d for d in deltas)


def test_chat_forwards_to_active_pty(monkeypatch):
    """Verify that if an active PTY session exists, prompt is forwarded to it."""
    written_data = []

    class MockPTY:
        def is_alive(self):
            return True

        def write(self, data):
            written_data.append(data)

    mock_pty = MockPTY()
    active_pty_sessions.add(mock_pty)

    try:
        async def mock_stream(prompt, conversation_id=None, model=None, agent=None, task_id=None):
            yield '{"type": "init"}\n'
            yield '{"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}\n'
            yield '{"type": "text_delta", "delta": "ok"}\n'
            yield '{"type": "done"}\n'

        monkeypatch.setattr("backend.app.stream_agy_chat", mock_stream)

        resp = client.post("/api/chat", json={"prompt": "prompt do pty"})
        assert resp.status_code == 200
        assert any("prompt do pty" in w for w in written_data)
    finally:
        active_pty_sessions.discard(mock_pty)


def test_sessions_polling_and_preview_cleaned(tmp_path, monkeypatch):
    """Test that new sessions in SQLite DB appear immediately via TestClient and have clean previews."""
    import sqlite3
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
            last_modified_time TEXT,
            status TEXT
        )
        """
    )
    raw_preview = "<USER_REQUEST>\nNowy prompt sesji\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime\n</ADDITIONAL_METADATA>"
    conn.execute(
        """
        INSERT INTO conversation_summaries (conversation_id, title, preview, step_count, last_modified_time, status)
        VALUES ('sess-100', 'Tytuł 100', ?, 5, '2026-10-06T21:00:00Z', 'IDLE')
        """,
        (raw_preview,)
    )
    conn.commit()
    conn.close()

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["conversation_id"] == "sess-100"
    assert sessions[0]["preview"] == "Nowy prompt sesji"
    assert "<USER_REQUEST>" not in sessions[0]["preview"]
    assert "<ADDITIONAL_METADATA>" not in sessions[0]["preview"]

