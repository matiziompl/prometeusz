import pytest
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, "/workspace/prometeusz")
from backend.app import app

client = TestClient(app)


def test_get_settings():
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "model" in data or "permissions" in data


def test_get_skills():
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()
    assert isinstance(skills, list)
    assert len(skills) > 0
    first = skills[0]
    assert "name" in first
    assert "description" in first


def test_get_models():
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert "current_model" in data
    names = [m["name"] for m in data["models"]]
    assert "Gemini 3.8 Flash (High)" in names
    assert "Gemini 3.1 Pro (High)" in names
    assert "Gemini 3.7 Flash (High)" in names
    assert "Claude Sonnet 4.6 (Thinking)" in names
    assert "Auto (Zalecany)" in names
    assert "Gemini 2.5 Pro" not in names
    assert "Gemini 2.5 Flash" not in names


def test_metrics_ram_fields():
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "ram_used_gb" in data
    assert "ram_total_gb" in data
    assert "memory_used_gb" in data
    assert "memory_total_gb" in data
    assert data["ram_total_gb"] > 0


def test_get_quota_usage():
    resp = client.get("/api/quota")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_tokens" in data
    assert "sessions_count" in data


def test_chat_stream_endpoint(monkeypatch):
    async def mock_stream(prompt, conversation_id=None, model=None, agent=None, task_id=None):
        yield '{"type": "text_delta", "delta": "echo TEST_REPLY"}\n'
        yield '{"type": "done"}\n'

    monkeypatch.setattr("backend.app.stream_agy_chat", mock_stream)
    resp = client.post("/api/chat", json={"prompt": "echo TEST_REPLY"})
    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    assert len(lines) > 0
    # Headers check for streaming
    assert "no-cache" in resp.headers.get("Cache-Control", "")
    assert resp.headers.get("X-Accel-Buffering") == "no"


def test_chat_stream_sse_support(monkeypatch):
    async def mock_stream(prompt, conversation_id=None, model=None, agent=None, task_id=None):
        yield '{"type": "text_delta", "delta": "echo SSE_REPLY"}\n'
        yield '{"type": "done"}\n'

    monkeypatch.setattr("backend.app.stream_agy_chat", mock_stream)
    resp = client.post(
        "/api/chat",
        json={"prompt": "echo SSE_REPLY"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("Content-Type", "")
    assert "data:" in resp.text


def test_chat_stream_with_attachments_metadata(monkeypatch):
    captured = {}
    async def mock_stream(prompt, conversation_id=None, model=None, agent=None, task_id=None):
        captured["prompt"] = prompt
        yield '{"type": "text_delta", "delta": "ok"}\n'
        yield '{"type": "done"}\n'

    monkeypatch.setattr("backend.app.stream_agy_chat", mock_stream)
    attachments = [
        {"name": "VencordInstaller.exe", "path": "/workspace/.uploads/VencordInstaller.exe"},
        {"name": "test.py", "path": "/workspace/test.py"}
    ]
    resp = client.post(
        "/api/chat",
        json={"prompt": "Zbadaj to", "attachments": attachments},
    )
    assert resp.status_code == 200
    assert "Zbadaj to" in captured["prompt"]
    assert "/workspace/.uploads/VencordInstaller.exe" in captured["prompt"]
    assert "/workspace/test.py" in captured["prompt"]



@pytest.mark.asyncio
async def test_chat_engine_command_construction(monkeypatch):
    from backend.chat_engine import stream_agy_chat
    import asyncio

    captured_cmd = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        
        class FakeStdout:
            def __init__(self):
                self.lines = [b'{"event":"result","result":{"status":"SUCCESS","response":"ok"}}\n']
            async def readline(self):
                if self.lines:
                    return self.lines.pop(0)
                return b""
        
        class FakeStderr:
            async def read(self):
                return b""

        class FakeProc:
            def __init__(self):
                self.stdout = FakeStdout()
                self.stderr = FakeStderr()
                self.returncode = 0
                self.pid = 9999
            async def wait(self):
                return 0

        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("shutil.which", lambda x: "/fake/agy")
    monkeypatch.setattr("os.path.exists", lambda x: True)
    monkeypatch.setattr("os.access", lambda x, y: True)

    events = []
    async for ev in stream_agy_chat("my prompt", conversation_id="conv-123", model="Gemini 3.8 Flash (High)", agent="@lead"):
        events.append(ev)

    # -p and prompt MUST be at the end, options before -p
    assert "-p" in captured_cmd
    p_idx = captured_cmd.index("-p")
    assert captured_cmd[p_idx + 1] == "my prompt"
    # Options must appear before -p
    if "--conversation" in captured_cmd:
        assert captured_cmd.index("--conversation") < p_idx
    if "--model" in captured_cmd:
        assert captured_cmd.index("--model") < p_idx
    if "--agent" in captured_cmd:
        assert captured_cmd.index("--agent") < p_idx



