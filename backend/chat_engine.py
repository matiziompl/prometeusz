import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
from typing import AsyncGenerator, Dict, Optional

logger = logging.getLogger(__name__)


def setup_developer_environment():
    """Ensure developer environment variables and root symlinks for agy authentication."""
    os.environ["HOME"] = "/home/developer"
    os.environ["USER"] = "developer"

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        links = [
            ("/home/developer/.gemini", "/root/.gemini"),
            ("/home/developer/.config", "/root/.config"),
            ("/home/developer/.local", "/root/.local"),
        ]
        for src, dst in links:
            try:
                subprocess.run(["ln", "-sfn", src, dst], check=False)
            except Exception as e:
                logger.warning(f"Failed to symlink {dst} -> {src}: {e}")


# Run setup immediately on module load
setup_developer_environment()

# Registry of active streaming subprocesses by task_id / conversation_id
active_chat_processes: Dict[str, asyncio.subprocess.Process] = {}


MODEL_ALIASES = {
    "gemini 3.8 flash (high)": "gemini-3.8-flash-high",
    "gemini-3.8-flash-high": "gemini-3.8-flash-high",
    "gemini 3.8 flash (medium)": "gemini-3.8-flash-medium",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-medium",
    "gemini 3.8 flash (low)": "gemini-3.8-flash-low",
    "gemini-3.8-flash-low": "gemini-3.8-flash-low",
    "gemini 3.7 flash (high)": "gemini-3.7-flash-high",
    "gemini-3.7-flash-high": "gemini-3.7-flash-high",
    "gemini 3.7 flash (medium)": "gemini-3.7-flash-medium",
    "gemini-3.7-flash-medium": "gemini-3.7-flash-medium",
    "gemini 3.7 flash (low)": "gemini-3.7-flash-low",
    "gemini-3.7-flash-low": "gemini-3.7-flash-low",
    "gemini 3.6 flash (high)": "gemini-3.6-flash-high",
    "gemini-3.6-flash-high": "gemini-3.6-flash-high",
    "gemini 3.6 flash (medium)": "gemini-3.6-flash-medium",
    "gemini-3.6-flash-medium": "gemini-3.6-flash-medium",
    "gemini 3.6 flash (low)": "gemini-3.6-flash-low",
    "gemini-3.6-flash-low": "gemini-3.6-flash-low",
    "gemini 3.1 pro (high)": "gemini-3.1-pro-high",
    "gemini-3.1-pro-high": "gemini-3.1-pro-high",
    "gemini 3.1 pro (low)": "gemini-3.1-pro-low",
    "gemini-3.1-pro-low": "gemini-3.1-pro-low",
    "claude sonnet 4.6 (thinking)": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude opus 4.6 (thinking)": "claude-opus-4-6-thinking",
    "claude-opus-4-6-thinking": "claude-opus-4-6-thinking",
    "gpt-oss 120b (medium)": "gpt-oss-120b-medium",
    "gpt-oss-120b-medium": "gpt-oss-120b-medium",
    "auto (zalecany)": None,
    "auto": None,
    "default": None,
}


def conversation_exists(conv_id: Optional[str]) -> bool:
    """Check if conversation_id exists in conversation_summaries.db."""
    if not conv_id or not isinstance(conv_id, str):
        return False
    from backend.sessions import get_antigravity_dir
    db_path = get_antigravity_dir() / "conversation_summaries.db"
    if not db_path.exists():
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM conversation_summaries WHERE conversation_id = ?", (conv_id,))
        row = cursor.fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def abort_chat_process(identifier: str) -> bool:
    """Terminates active agy subprocess by task_id or conversation_id."""
    proc = active_chat_processes.get(identifier)
    if proc and proc.returncode is None:
        try:
            if hasattr(os, "killpg") and proc.pid:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGINT)
                except (ProcessLookupError, OSError):
                    proc.send_signal(signal.SIGINT)
            else:
                proc.send_signal(signal.SIGINT)
            return True
        except ProcessLookupError:
            active_chat_processes.pop(identifier, None)
            return False
        except Exception as e:
            logger.warning(f"Error terminating chat process {identifier}: {e}")
            try:
                proc.kill()
            except Exception:
                pass
            active_chat_processes.pop(identifier, None)
            return True
    return False


def abort_all_chat_processes() -> int:
    """Emergency abort for all active chat subprocesses."""
    killed = 0
    seen_procs = set()
    for key, proc in list(active_chat_processes.items()):
        if proc not in seen_procs:
            seen_procs.add(proc)
            if proc.returncode is None:
                try:
                    if hasattr(os, "killpg") and proc.pid:
                        try:
                            pgid = os.getpgid(proc.pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            proc.kill()
                    else:
                        proc.kill()
                    killed += 1
                except Exception:
                    pass
    active_chat_processes.clear()
    return killed


def forward_prompt_to_pty(prompt: str) -> bool:
    """Forward prompt directly to active PTY sessions (/ws/pty) if available."""
    try:
        from backend.app import active_pty_sessions
        forwarded = False
        for pty in list(active_pty_sessions):
            if hasattr(pty, "is_alive") and pty.is_alive() and hasattr(pty, "write"):
                pty.write(prompt + "\n")
                forwarded = True
        return forwarded
    except Exception:
        return False


async def stream_agy_chat(
    prompt: str,
    conversation_id: Optional[str] = None,
    model: Optional[str] = None,
    agent: Optional[str] = None,
    task_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Execute agy CLI in real time, forward to PTY if active, and yield stream events."""
    forward_prompt_to_pty(prompt)

    agy_bin = os.getenv("AGY_BIN", "/home/developer/.local/bin/agy")
    if not (os.path.exists(agy_bin) and os.access(agy_bin, os.X_OK)):
        agy_bin = shutil.which("agy")

    if not agy_bin:
        # Fallback simulation if agy is not installed
        assigned_id = conversation_id or "sess-local"
        yield json.dumps({"type": "init", "conversation_id": assigned_id}) + "\n"
        yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"
        yield json.dumps({"type": "thought", "text": "Brak zainstalowanego silnika agy na maszynie. Symulacja odpowiedzi."}) + "\n"
        delta_msg = f"Odpowiedź na: **{prompt}**\n\n(Tryb symulacyjny: zainstaluj silnik `agy`, aby korzystać z pełnych modeli)."
        yield json.dumps({"type": "text_delta", "delta": delta_msg}) + "\n"
        yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"
        yield json.dumps({
            "type": "done",
            "conversation_id": assigned_id,
            "status": "SUCCESS",
            "duration": 0.5,
            "usage": {"total_tokens": 120},
            "response": delta_msg,
        }) + "\n"
        return

    # Build clean agy command line: options first, then -p <prompt> at the end
    cmd = [
        agy_bin,
        "--dangerously-skip-permissions",
    ]

    valid_conv_id = conversation_id if conversation_exists(conversation_id) else None
    if valid_conv_id:
        cmd.extend(["--conversation", valid_conv_id])

    if model:
        clean_model = MODEL_ALIASES.get(model.strip().lower(), model.strip())
        if clean_model and clean_model.lower() not in ("auto", "auto (zalecany)", "default"):
            cmd.extend(["--model", clean_model])

    if agent:
        agent_clean = agent.lstrip("@").strip()
        role_map = {
            "lead": "lead-engineer",
            "frontend": "frontend-artisan",
            "security": "security-auditor",
            "qa": "qa-engineer",
            "data": "data-analyst",
        }
        agent_name = role_map.get(agent_clean, agent_clean)
        cmd.extend(["--agent", agent_name])

    # -p and prompt MUST be placed at the end of cmd arguments
    cmd.extend(["-p", prompt])

    tracking_keys = [k for k in (task_id, conversation_id) if k]
    if not tracking_keys:
        tracking_keys = [f"proc-{id(cmd)}"]

    proc_env = os.environ.copy()
    proc_env["HOME"] = "/home/developer"
    proc_env["USER"] = "developer"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getenv("WORKSPACE_DIR", "/workspace"),
            env=proc_env,
            start_new_session=True,
        )
        for k in tracking_keys:
            active_chat_processes[k] = proc
    except Exception as e:
        yield json.dumps({"type": "error", "message": f"Nie udało się uruchomić procesu agy: {str(e)}"}) + "\n"
        return

    accumulated_text = ""
    assigned_conv_id = valid_conv_id or conversation_id or "session-live"
    done_emitted = False

    # Emit init and immediately set command status to ready
    yield json.dumps({"type": "init", "conversation_id": assigned_conv_id}) + "\n"
    yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"

    # Drain stderr concurrently in background to prevent pipe buffer deadlocks
    async def _drain_stderr() -> str:
        try:
            err = await proc.stderr.read()
            return err.decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    stderr_task = asyncio.create_task(_drain_stderr())

    try:
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace")
            stripped = line.strip()
            if not stripped:
                continue

            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                # Direct raw text output from agy CLI: stream immediately to chat
                accumulated_text += line
                yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"
                yield json.dumps({"type": "text_delta", "delta": line}) + "\n"
                continue

            event = data.get("event")
            if event == "init":
                assigned_conv_id = data.get("conversation_id") or assigned_conv_id
                yield json.dumps({"type": "init", "conversation_id": assigned_conv_id}) + "\n"
                yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"

            elif event == "step_update":
                update = data.get("step_update", {})
                step_type = update.get("step_type")

                # Handle tool executions
                if step_type in ("tool", "tool_call") or "tool_name" in update or "tool_info" in update:
                    tool_info = update.get("tool_info")
                    tool_name = update.get("tool_name")
                    if not tool_name and isinstance(tool_info, dict):
                        tool_name = tool_info.get("name")
                    yield json.dumps({
                        "type": "tool_update",
                        "tool_name": tool_name or "tool",
                        "state": update.get("state", "ready"),
                        "tool_info": tool_info,
                        "duration": update.get("duration_seconds"),
                    }) + "\n"

                # Handle model thoughts
                thought = update.get("thought") or update.get("raw_thought")
                if not thought and step_type == "thought":
                    thought = update.get("text_delta")
                if thought:
                    yield json.dumps({"type": "thought", "text": thought}) + "\n"

                # Handle text deltas
                text_delta = update.get("text_delta")
                if text_delta and step_type != "thought":
                    accumulated_text += text_delta
                    yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"
                    yield json.dumps({"type": "text_delta", "delta": text_delta}) + "\n"

            elif event == "result":
                res = data.get("result", {})
                final_resp = res.get("response", accumulated_text)
                if not accumulated_text and final_resp:
                    accumulated_text = final_resp
                    yield json.dumps({"type": "text_delta", "delta": final_resp}) + "\n"
                done_emitted = True
                yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"
                yield json.dumps({
                    "type": "done",
                    "conversation_id": assigned_conv_id,
                    "status": res.get("status", "SUCCESS"),
                    "duration": res.get("duration_seconds", 0.0),
                    "usage": res.get("usage", {}),
                    "response": final_resp,
                }) + "\n"

        await proc.wait()
        stderr_msg = await stderr_task

        # Check if process exited with error and produced no output
        if proc.returncode != 0 and not accumulated_text:
            yield json.dumps({
                "type": "error",
                "message": f"Silnik agy zwrócił kod {proc.returncode}: {stderr_msg or 'Nieznany błąd wykonania'}",
            }) + "\n"
        elif not done_emitted:
            done_emitted = True
            yield json.dumps({"type": "tool_update", "tool_name": "Bash Execution", "state": "ready"}) + "\n"
            yield json.dumps({
                "type": "done",
                "conversation_id": assigned_conv_id,
                "status": "SUCCESS" if proc.returncode == 0 else "ERROR",
                "duration": 0.0,
                "usage": {},
                "response": accumulated_text,
            }) + "\n"

    finally:
        if not stderr_task.done():
            stderr_task.cancel()
        for k in tracking_keys:
            active_chat_processes.pop(k, None)
