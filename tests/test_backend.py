import asyncio
import os
import sys
import pytest

# Add project root to sys.path
sys.path.insert(0, "/workspace/prometeusz")

from backend.metrics import get_system_metrics
from backend.sessions import get_sessions, get_session_details, get_session_artifacts
from backend.pty_manager import PTYSession


def test_system_metrics():
    metrics = get_system_metrics()
    assert isinstance(metrics, dict)
    assert "cpu_percent" in metrics
    assert "memory_total" in metrics
    assert "memory_used" in metrics
    assert "memory_percent" in metrics
    assert "disk_total" in metrics
    assert "disk_used" in metrics
    assert "disk_percent" in metrics
    assert 0 <= metrics["memory_percent"] <= 100
    assert metrics["memory_total"] > 0


def test_sessions_list():
    sessions = get_sessions()
    assert isinstance(sessions, list)
    # If conversations exist in antigravity directory, check their schema
    if sessions:
        first = sessions[0]
        assert "conversation_id" in first
        assert "title" in first
        assert "last_modified" in first


def test_transcript_parsing_synthetic(tmp_path):
    # Create synthetic transcript log
    import json
    brain_dir = tmp_path / "test-conv-id" / ".system_generated" / "logs"
    brain_dir.mkdir(parents=True)
    transcript_file = brain_dir / "transcript.jsonl"
    
    entries = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Hello Prometeusz"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "Let me think about it", "tool_calls": [{"toolAction": "Run bash", "toolSummary": "Run bash", "arguments": {"cmd": "ls"}}]},
        {"step_index": 2, "source": "MODEL", "type": "GENERIC", "content": "Here is the response"}
    ]
    with open(transcript_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
            
    details = get_session_details("test-conv-id", base_dir=str(tmp_path))
    assert details["conversation_id"] == "test-conv-id"
    assert len(details["messages"]) >= 2
    user_msg = details["messages"][0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Hello Prometeusz"
    
    assistant_msg = details["messages"][1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["thinking"] == "Let me think about it"
    assert len(assistant_msg["tool_calls"]) == 1
    assert assistant_msg["tool_calls"][0]["toolAction"] == "Run bash"


def test_pty_session_lifecycle():
    async def _run():
        pty = PTYSession(command=["echo", "HELLO_PROMETEUSZ"])
        await pty.start()
        output = await pty.read_until("HELLO_PROMETEUSZ", timeout=3.0)
        assert "HELLO_PROMETEUSZ" in output
        await pty.close()
        assert not pty.is_alive()
    asyncio.run(_run())



def test_transcript_parsing_with_args_and_output(tmp_path):
    import json
    from backend.sessions import get_session_changes, get_file_diff

    brain_dir = tmp_path / "brain" / "sess-real-001" / ".system_generated" / "logs"
    brain_dir.mkdir(parents=True)
    transcript_file = brain_dir / "transcript.jsonl"

    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("line 1\nline 2\n")

    entries = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Update the file"},
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "thinking": "Applying change",
            "tool_calls": [
                {"name": "write_to_file", "args": {"TargetFile": str(dummy_file), "CodeContent": "new content"}}
            ]
        },
        {"step_index": 2, "source": "MODEL", "type": "GENERIC", "content": "File written successfully."}
    ]
    with open(transcript_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    details = get_session_details("sess-real-001", base_dir=str(tmp_path))
    assistant_msg = details["messages"][1]
    assert len(assistant_msg["tool_calls"]) == 1
    tc = assistant_msg["tool_calls"][0]
    # Check that both args and arguments are populated
    assert "args" in tc and "arguments" in tc
    assert tc["output"] == "File written successfully."

    # Verify session changes tracking
    changes = get_session_changes("sess-real-001", base_dir=str(tmp_path))
    assert len(changes) == 1
    assert changes[0]["filename"] == "dummy.txt"
    assert changes[0]["path"] == str(dummy_file)

    # Verify get_file_diff safety
    diff = get_file_diff(str(dummy_file))
    assert "lines" in diff
    assert len(diff["lines"]) == 2

    # Verify get_file_diff rejects arbitrary paths outside allowed directories
    bad_diff = get_file_diff("/etc/shadow")
    assert "error" in bad_diff


def test_sessions_sorting_order(tmp_path):
    import sqlite3
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
    conn.execute("INSERT INTO conversation_summaries VALUES ('s1', 'Older', 'p', 1, '2026-10-01 10:00:00', 'IDLE')")
    conn.execute("INSERT INTO conversation_summaries VALUES ('s2', 'Newer', 'p', 1, '2026-10-04 12:00:00', 'IDLE')")
    conn.execute("INSERT INTO conversation_summaries VALUES ('s3', 'Pinned Old', 'p', 1, '2026-09-01 10:00:00', 'IDLE')")
    conn.commit()
    conn.close()

    from backend.sessions import toggle_pin_session
    toggle_pin_session("s3", pinned=True, base_dir=str(tmp_path))

    sessions = get_sessions(base_dir=str(tmp_path))
    assert len(sessions) == 3
    # Pinned session s3 must be first
    assert sessions[0]["conversation_id"] == "s3"
    assert sessions[0]["pinned"] is True
    # s2 (newer) must be before s1 (older)
    assert sessions[1]["conversation_id"] == "s2"
    assert sessions[2]["conversation_id"] == "s1"


def test_sessions_filter_excludes_subagents_and_empty(tmp_path):
    import sqlite3
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
            status TEXT,
            parent_conversation_id TEXT,
            nesting_depth INTEGER
        )
        """
    )
    # Real session 1
    conn.execute("INSERT INTO conversation_summaries VALUES ('real-1', 'Main Task', 'Doing task', 5, '2026-10-06 12:00:00', 'IDLE', '', 0)")
    # Real session 2
    conn.execute("INSERT INTO conversation_summaries VALUES ('real-2', 'Second Task', 'Other task', 2, '2026-10-06 11:00:00', 'IDLE', NULL, 0)")
    # Subagent session (parent is real-1, nesting_depth 1)
    conn.execute("INSERT INTO conversation_summaries VALUES ('subagent-1', '', '', 15, '2026-10-06 11:30:00', 'IDLE', 'real-1', 1)")
    # Empty session (step_count 0)
    conn.execute("INSERT INTO conversation_summaries VALUES ('empty-1', '', '', 0, '2026-10-06 10:00:00', 'IDLE', '', 0)")
    conn.commit()
    conn.close()

    sessions = get_sessions(base_dir=str(tmp_path))
    assert len(sessions) == 2
    ids = [s["conversation_id"] for s in sessions]
    assert "real-1" in ids
    assert "real-2" in ids
    assert "subagent-1" not in ids
    assert "empty-1" not in ids


def test_sessions_does_not_scan_brain_dir(tmp_path):
    # Create empty DB
    import sqlite3
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
    conn.commit()
    conn.close()

    # Create dummy subagent folder in brain
    brain_dir = tmp_path / "brain" / "subagent-disk-folder"
    brain_dir.mkdir(parents=True)

    sessions = get_sessions(base_dir=str(tmp_path))
    # Must NOT fabricate a session from brain directory
    assert len(sessions) == 0


def test_fork_session_unit(tmp_path):
    import json
    import sqlite3
    from backend.sessions import fork_session, get_session_details

    # Setup database with a source session
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
    conn.execute("INSERT INTO conversation_summaries VALUES ('orig-session-1', 'Zadanie główne', 'Podgląd zadania', 3, '2026-10-06 12:00:00', 'IDLE')")
    conn.commit()
    conn.close()

    # Setup brain transcripts
    brain_dir = tmp_path / "brain" / "orig-session-1" / ".system_generated" / "logs"
    brain_dir.mkdir(parents=True)
    transcript_file = brain_dir / "transcript.jsonl"
    transcript_file.write_text(
        json.dumps({"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Wiadomość źródłowa"}) + "\n" +
        json.dumps({"step_index": 1, "source": "MODEL", "type": "GENERIC", "content": "Odpowiedź asystenta"}) + "\n",
        encoding="utf-8"
    )

    # Setup conversations DB
    convs_dir = tmp_path / "conversations"
    convs_dir.mkdir(parents=True)
    c_db_path = convs_dir / "orig-session-1.db"
    c_conn = sqlite3.connect(str(c_db_path))
    c_conn.execute("CREATE TABLE trajectory_meta (trajectory_id TEXT, cascade_id TEXT)")
    c_conn.execute("INSERT INTO trajectory_meta VALUES ('traj-1', 'orig-session-1')")
    c_conn.commit()
    c_conn.close()

    # Execute fork
    res = fork_session("orig-session-1", base_dir=str(tmp_path))
    assert res["success"] is True
    new_id = res["conversation_id"]
    assert new_id != "orig-session-1"
    assert "Fork" in res["title"]

    # Verify new session exists in database
    conn2 = sqlite3.connect(str(db_path))
    row = conn2.execute("SELECT conversation_id, title, step_count FROM conversation_summaries WHERE conversation_id = ?", (new_id,)).fetchone()
    conn2.close()
    assert row is not None
    assert row[0] == new_id
    assert row[2] == 3

    # Verify transcripts copied to new brain folder
    new_details = get_session_details(new_id, base_dir=str(tmp_path))
    assert len(new_details["messages"]) == 2
    assert new_details["messages"][0]["content"] == "Wiadomość źródłowa"

    # Verify conversations DB copied
    new_cdb_path = convs_dir / f"{new_id}.db"
    assert new_cdb_path.exists()


