import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from backend.app import app
from tests.mock_pty import MockPTYSession

client = TestClient(app)


def test_environment_setup_sets_home_and_user():
    from backend.app import setup_developer_environment
    setup_developer_environment()
    assert os.environ.get("HOME") == "/home/developer"
    assert os.environ.get("USER") == "developer"


def test_environment_setup_creates_symlinks_when_root(monkeypatch):
    from backend.app import setup_developer_environment
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    setup_developer_environment()

    expected_links = [
        ["ln", "-sfn", "/home/developer/.gemini", "/root/.gemini"],
        ["ln", "-sfn", "/home/developer/.config", "/root/.config"],
        ["ln", "-sfn", "/home/developer/.local", "/root/.local"],
    ]
    for expected in expected_links:
        assert expected in calls


def test_pty_defaults_to_agy(monkeypatch):
    launched_cmd = []

    class CapturingPTY(MockPTYSession):
        def __init__(self, command=None, cwd="/workspace", env=None, on_output=None):
            super().__init__(command=command, cwd=cwd, env=env, on_output=on_output)
            launched_cmd.extend(self.command)

    monkeypatch.setattr("backend.app.PTYSession", CapturingPTY)
    monkeypatch.setattr("os.path.exists", lambda p: True)
    monkeypatch.setattr("os.access", lambda p, m: True)

    with client.websocket_connect("/ws/pty") as ws:
        ws.send_json({"type": "stdin", "data": "exit\n"})

    assert len(launched_cmd) > 0
    assert launched_cmd[0].endswith("agy")
    assert "/bin/bash" not in launched_cmd


def test_api_agents_endpoint():
    response = client.get("/api/agents")
    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    assert len(agents) > 0
    agent_ids = [a["id"] for a in agents]
    assert "lead-engineer" in agent_ids
    assert "frontend-artisan" in agent_ids


def test_get_installed_agents_parser(tmp_path):
    from backend.settings_manager import get_installed_agents

    agent_dir = tmp_path / "custom-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.md").write_text(
        "---\nname: custom-agent\ndescription: Custom test agent description.\n---\n# Agent Info",
        encoding="utf-8"
    )

    agents = get_installed_agents(str(tmp_path))
    assert len(agents) == 1
    assert agents[0]["id"] == "custom-agent"
    assert agents[0]["name"] == "custom-agent"
    assert agents[0]["description"] == "Custom test agent description."
