import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

import psutil
from fastapi import (
    Body,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.chat_engine import abort_all_chat_processes, abort_chat_process, stream_agy_chat
from backend.metrics import get_system_metrics
from backend.pty_manager import PTYSession
from backend.sessions import (
    create_folder,
    delete_folder,
    delete_session,
    export_session,
    fork_session,
    get_artifact_content,
    get_file_diff,
    get_folders,
    get_session_artifacts,
    get_session_changes,
    get_session_details,
    get_sessions,
    rename_session,
    search_sessions,
    set_session_folder,
    toggle_pin_session,
    update_sessions_order,
    validate_conversation_id,
    validate_filename,
)
from backend.settings_manager import (
    get_antigravity_settings,
    get_installed_agents,
    get_installed_skills,
    get_models_info,
    get_quota_statistics,
    save_antigravity_settings,
    set_active_model,
)


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
            except Exception:
                pass


# Run setup immediately on module load
setup_developer_environment()

app = FastAPI(title="Prometeusz Web UI API", version="2.0.0")

MAX_CONCURRENT_PTY = 5
MAX_WS_MESSAGE_SIZE = 64 * 1024  # 64 KB
active_pty_sessions: Set[PTYSession] = set()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|testserver|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.\d+\.\d+\.\d+)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SLASH_COMMANDS = [
    {"command": "/goal", "description": "Uruchom długotrwałe zadanie autonomiczne"},
    {"command": "/plan", "description": "Stwórz plan inżynieryjny krok po kroku"},
    {"command": "/browser", "description": "Automatyzacja i inspekcja stron w Playwright"},
    {"command": "/grill-me", "description": "Wywiad i analiza decyzji architektonicznych"},
    {"command": "/teamwork-preview", "description": "Koordynacja podagentów wieloaspektowych"},
    {"command": "/skills", "description": "Przeglądaj i załaduj zainstalowane skillsy"},
    {"command": "/model", "description": "Przełącz aktywny model rozumowania"},
    {"command": "/boost", "description": "Aktywuj głębokie wnioskowanie i weryfikację"},
    {"command": "/learn", "description": "Zapisz trwałe wnioski inżynieryjne"},
    {"command": "/settings", "description": "Otwórz panel ustawień i konfiguracji"},
    {"command": "/help", "description": "Wyświetl pomoc i listę skrótów"},
]


# ─── METRYKI I KOMENDY ──────────────────────────────────────────────────

@app.get("/api/metrics")
def api_metrics():
    """Returns real-time CPU, RAM, and Disk metrics."""
    return get_system_metrics()


@app.get("/api/slash-commands")
def api_slash_commands():
    """Returns list of supported slash commands for autocomplete."""
    return SLASH_COMMANDS


# ─── ZARZĄDZANIE SESJAMI ────────────────────────────────────────────────

@app.get("/api/sessions")
def api_sessions():
    """Returns list of all conversation sessions with metadata."""
    return get_sessions()


@app.get("/api/sessions/search")
def api_sessions_search(q: str = Query("", description="Fraza do wyszukania")):
    """Full-text search across session summaries, messages, and code transcripts."""
    return search_sessions(q)


@app.get("/api/sessions/{session_id}")
def api_session_details(session_id: str):
    """Returns full transcript for a specific session."""
    try:
        validate_conversation_id(session_id)
        return get_session_details(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    """Permanently deletes a conversation session from DB and filesystem."""
    try:
        validate_conversation_id(session_id)
        delete_session(session_id)
        return {"success": True, "conversation_id": session_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.patch("/api/sessions/{session_id}")
async def api_rename_session(session_id: str, payload: Dict[str, Any] = Body(...)):
    """Renames conversation session."""
    try:
        validate_conversation_id(session_id)
        new_title = payload.get("title", "")
        rename_session(session_id, new_title)
        return {"success": True, "conversation_id": session_id, "title": new_title}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sessions/{session_id}/pin")
async def api_pin_session(session_id: str, payload: Dict[str, Any] = Body(default={})):
    """Pins or unpins a session to the top."""
    try:
        validate_conversation_id(session_id)
        pinned = payload.get("pinned")
        new_state = toggle_pin_session(session_id, pinned)
        return {"success": True, "conversation_id": session_id, "pinned": new_state}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sessions/{session_id}/folder")
async def api_set_folder(session_id: str, payload: Dict[str, Any] = Body(...)):
    """Assigns session to a folder."""
    try:
        validate_conversation_id(session_id)
        folder = payload.get("folder", "")
        set_session_folder(session_id, folder)
        return {"success": True, "conversation_id": session_id, "folder": folder}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sessions/order")
async def api_save_sessions_order(payload: Dict[str, Any] = Body(...)):
    """Saves manual sort order for sessions."""
    order_list = payload.get("order", [])
    if isinstance(order_list, list):
        update_sessions_order(order_list)
    return {"success": True}


@app.get("/api/sessions/{session_id}/export")
def api_export_session(session_id: str, format: str = Query("markdown")):
    """Exports conversation session to Markdown or JSON."""
    try:
        validate_conversation_id(session_id)
        exported = export_session(session_id, format_type=format)
        return Response(
            content=exported["content"],
            media_type=exported["media_type"],
            headers={"Content-Disposition": f"attachment; filename=\"{exported['filename']}\""},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sessions/{session_id}/fork")
def api_fork_session(session_id: str):
    """Forks an existing conversation session into a new one with unique ID."""
    try:
        validate_conversation_id(session_id)
        result = fork_session(session_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")



# ─── FOLDERY ─────────────────────────────────────────────────────────────

@app.get("/api/folders")
def api_get_folders():
    """Lists user-created session folders."""
    return get_folders()


@app.post("/api/folders")
async def api_create_folder(payload: Dict[str, Any] = Body(...)):
    """Creates a new folder."""
    name = payload.get("name", "")
    try:
        return create_folder(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/folders/{folder_id}")
def api_delete_folder(folder_id: str):
    """Deletes a folder."""
    delete_folder(folder_id)
    return {"success": True, "id": folder_id}


# ─── ARTEFAKTY I ZMIANY W TEJ SESJI ──────────────────────────────────────

@app.get("/api/sessions/{session_id}/artifacts")
def api_session_artifacts(session_id: str):
    """Returns list of artifacts for a session."""
    try:
        validate_conversation_id(session_id)
        return get_session_artifacts(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/api/sessions/{session_id}/artifacts/{filename}")
def api_artifact_content(session_id: str, filename: str):
    """Returns content of a specific artifact file."""
    try:
        validate_conversation_id(session_id)
        validate_filename(filename)
        content = get_artifact_content(session_id, filename)
        if content is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if filename.endswith(".html"):
            media_type = "text/html"
        elif filename.endswith(".svg"):
            media_type = "image/svg+xml"
        elif filename.endswith((".md", ".markdown")):
            media_type = "text/markdown"
        elif filename.endswith(".json"):
            media_type = "application/json"
        else:
            media_type = "text/plain"
        return Response(content=content, media_type=media_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/api/sessions/{session_id}/changes")
def api_session_changes(session_id: str):
    """Returns files modified strictly during THIS session."""
    try:
        validate_conversation_id(session_id)
        return get_session_changes(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/sessions/{session_id}/changes/diff")
def api_session_change_diff(session_id: str, file: str = Query(...)):
    """Returns unified lines diff for a file modified in this session."""
    try:
        validate_conversation_id(session_id)
        return get_file_diff(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── USTAWIENIA, SKILLSY, MODELE, QUOTA ──────────────────────────────────

@app.get("/api/settings")
def api_get_settings():
    """Returns contents of settings.json."""
    return get_antigravity_settings()


@app.post("/api/settings")
async def api_save_settings(request: Request):
    """Saves updated settings.json."""
    try:
        data = await request.json()
        return save_antigravity_settings(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Błąd zapisu ustawień: {str(e)}")


@app.get("/api/agents")
def api_get_agents():
    """Returns dynamically discovered subagents."""
    return get_installed_agents()


@app.get("/api/skills")
def api_get_skills():
    """Returns list of installed skills."""
    return get_installed_skills()


@app.get("/api/models")
def api_get_models():
    """Returns available models list and active model."""
    return get_models_info()


@app.post("/api/models/select")
async def api_select_model(request: Request):
    """Switches active model in settings."""
    try:
        data = await request.json()
        model_name = data.get("model")
        if not model_name:
            raise HTTPException(status_code=400, detail="Brak nazwy modelu")
        return set_active_model(model_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/quota")
def api_get_quota():
    """Returns calculated token usage and session statistics."""
    return get_quota_statistics()


# ─── STRUMIENIOWANIE CZATU I ABORT ───────────────────────────────────────

@app.post("/api/chat")
async def api_chat_stream(request: Request):
    """Executes agy CLI in real time and streams NDJSON or SSE events."""
    data = await request.json()
    prompt = data.get("prompt")
    conversation_id = data.get("conversation_id")
    model = data.get("model")
    agent = data.get("agent")
    task_id = data.get("task_id")
    attachments = data.get("attachments") or []

    if not prompt and attachments:
        prompt = "Przeanalizuj załączone pliki."
    elif not prompt:
        raise HTTPException(status_code=400, detail="Prompt nie może być pusty")

    effective_prompt = prompt
    if attachments:
        paths = []
        for att in attachments:
            if isinstance(att, dict):
                p = att.get("path") or att.get("name")
                if p:
                    paths.append(str(p))
            elif isinstance(att, str):
                paths.append(att)
        if paths:
            files_str = "\n".join(f"- file://{p}" for p in paths)
            effective_prompt = f"{prompt}\n\n[Załączniki:\n{files_str}]"

    # Forward prompt directly to active PTY sessions (/ws/pty)
    for pty in list(active_pty_sessions):
        if hasattr(pty, "is_alive") and pty.is_alive() and hasattr(pty, "write"):
            try:
                pty.write(effective_prompt + "\n")
            except Exception:
                pass

    accept_header = request.headers.get("accept", "")
    use_sse = "text/event-stream" in accept_header or request.query_params.get("format") == "sse"

    async def event_generator():
        generator = stream_agy_chat(
            effective_prompt,
            conversation_id=conversation_id,
            model=model,
            agent=agent,
            task_id=task_id,
        )
        async for chunk in generator:
            if use_sse:
                raw_line = chunk.strip()
                if raw_line:
                    yield f"data: {raw_line}\n\n"
            else:
                yield chunk
        if use_sse:
            yield "data: [DONE]\n\n"

    media_type = "text/event-stream" if use_sse else "application/x-ndjson"
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Content-Type": f"{media_type}; charset=utf-8",
    }

    return StreamingResponse(
        event_generator(),
        media_type=media_type,
        headers=headers,
    )


@app.post("/api/chat/abort")
async def api_chat_abort(request: Request):
    """Aborts active agy process by task_id or conversation_id."""
    data = await request.json()
    task_id = data.get("task_id") or data.get("conversation_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="Wymagane task_id lub conversation_id")

    success = abort_chat_process(task_id)
    return {"aborted": success, "task_id": task_id}


# ─── DRAG & DROP UPLOAD I PANIC BUTTON ────────────────────────────────────

def _get_upload_dir() -> Path:
    ws = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()
    upload_dir = ws / ".uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _is_safe_fs_path(p: Path) -> bool:
    allowed_roots = [
        Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve(),
        Path(os.getenv("ANTIGRAVITY_CLI_DIR", os.path.expanduser("~/.gemini/antigravity-cli"))).resolve(),
        Path("/tmp").resolve(),
        Path("/home/developer").resolve(),
        Path("/app").resolve(),
    ]
    return any(p == root or root in p.parents for root in allowed_roots if root.exists())


@app.post("/api/upload")
async def api_upload_file(request: Request):
    """Accepts uploaded file from drag-and-drop and saves into workspace .uploads/."""
    upload_dir = _get_upload_dir()

    content_type = request.headers.get("content-type", "")
    filename = request.headers.get("x-filename", "uploaded_file")

    if "application/json" in content_type:
        import base64
        data = await request.json()
        filename = data.get("filename") or filename
        file_bytes = base64.b64decode(data.get("content_base64", ""))
    else:
        file_bytes = await request.body()

    clean_name = Path(filename).name
    safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean_name).lstrip(".")
    if not safe_name:
        safe_name = "uploaded_file"

    target_path = (upload_dir / safe_name).resolve()
    try:
        target_path.relative_to(upload_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Nieprawidłowa nazwa pliku")

    target_path.write_bytes(file_bytes)

    return {
        "success": True,
        "filename": safe_name,
        "path": str(target_path),
        "size": len(file_bytes),
    }


@app.get("/api/uploads")
def api_list_uploads():
    """Lists uploaded files with metadata."""
    upload_dir = _get_upload_dir()
    files = []
    for item in sorted(upload_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if item.is_file() and not item.name.startswith("."):
            stat = item.stat()
            files.append({
                "filename": item.name,
                "path": str(item),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
    return files


@app.delete("/api/uploads/{filename}")
def api_delete_upload(filename: str):
    """Deletes an uploaded file."""
    validate_filename(filename)
    upload_dir = _get_upload_dir()
    target = (upload_dir / filename).resolve()
    try:
        target.relative_to(upload_dir)
        if target.exists() and target.is_file():
            target.unlink()
            return {"success": True, "filename": filename}
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    raise HTTPException(status_code=404, detail="File not found")


# ─── PRZEGLĄDARKA PLIKÓW NA MASZYNIE (FILE EXPLORER) ─────────────────────

@app.get("/api/fs/list")
def api_fs_list(path: str = Query("/workspace", description="Katalog do wylistowania")):
    """Safely browses filesystem directories starting from /workspace or allowed paths."""
    target_dir = Path(path).resolve()
    if not _is_safe_fs_path(target_dir):
        raise HTTPException(status_code=403, detail="Brak uprawnień do przeglądania tej ścieżki")
    if not (target_dir.exists() and target_dir.is_dir()):
        raise HTTPException(status_code=404, detail="Katalog nie istnieje")

    items = []
    try:
        for entry in sorted(target_dir.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            # Pomiń foldery .git/node_modules/cache dla czytelności, chyba że użytkownik celowo w nie wejdzie
            if entry.name in {".git", "__pycache__", ".pytest_cache"}:
                continue
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else None,
                    "modified": stat.st_mtime,
                    "extension": entry.suffix.lower() if entry.is_file() else "",
                })
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Brak uprawnień do odczytu katalogu")

    parent_path = str(target_dir.parent) if target_dir != Path("/") else None
    return {
        "current_path": str(target_dir),
        "parent_path": parent_path,
        "items": items,
    }


@app.get("/api/fs/read")
def api_fs_read(path: str = Query(..., description="Ścieżka do pliku")):
    """Safely reads file content for viewing in the browser."""
    target_file = Path(path).resolve()
    if not _is_safe_fs_path(target_file):
        raise HTTPException(status_code=403, detail="Brak uprawnień do odczytu tej ścieżki")
    if not (target_file.exists() and target_file.is_file()):
        raise HTTPException(status_code=404, detail="Plik nie istnieje")

    # Limit file size for viewing (max 2 MB)
    if target_file.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Plik jest zbyt duży do podglądu (max 2MB)")

    try:
        content = target_file.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(target_file),
            "filename": target_file.name,
            "content": content,
            "size": target_file.stat().st_size,
            "extension": target_file.suffix.lower(),
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="Brak uprawnień do odczytu pliku")


@app.post("/api/panic")
async def api_panic_kill():
    """Emergency kill of any hanging processes in workspace and clear active PTYs."""
    killed_count = 0

    # 1. Kill active PTY sessions
    for pty in list(active_pty_sessions):
        try:
            await pty.close()
            killed_count += 1
        except Exception:
            pass
    active_pty_sessions.clear()

    # 2. Kill active chat processes
    try:
        killed_count += abort_all_chat_processes()
    except Exception:
        pass

    # 3. Kill any stray agy processes
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline)
            if "agy" in proc.info.get("name", "").lower() or ("agy" in cmd_str and "--print" in cmd_str):
                proc.kill()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return {"success": True, "processes_killed": killed_count}


# ─── PTY WEBSOCKET ────────────────────────────────────────────────────────

@app.websocket("/ws/pty")
async def websocket_pty(websocket: WebSocket, session_id: Optional[str] = None):
    """Bidirectional WebSocket connection forwarding I/O to a pseudo-terminal (PTY)."""
    # 1. Cross-Site WebSocket Hijacking (CSWSH) protection
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin:
        parsed_origin = urlparse(origin)
        parsed_host = host.split(":")[0] if host else ""
        origin_hostname = parsed_origin.hostname or ""

        is_same_host = bool(parsed_host and (origin_hostname == parsed_host))
        is_local = origin_hostname in {"localhost", "127.0.0.1", "testserver"}
        is_private_ip = (
            origin_hostname.startswith("192.168.")
            or origin_hostname.startswith("10.")
            or origin_hostname.startswith("172.")
        )

        if not (is_same_host or is_local or is_private_ip):
            await websocket.close(code=1008, reason="Forbidden origin")
            return

    # 2. Concurrency limit check
    if len(active_pty_sessions) >= MAX_CONCURRENT_PTY:
        await websocket.close(code=1008, reason="Max PTY sessions limit reached")
        return

    # 3. Sanitize session_id to prevent CLI argument injection
    if session_id:
        try:
            validate_conversation_id(session_id)
        except ValueError as e:
            await websocket.close(code=1008, reason=f"Invalid session_id: {e}")
            return

    await websocket.accept()

    # Determine command to run in PTY: default to agy CLI
    agy_bin = os.getenv("AGY_BIN", "/home/developer/.local/bin/agy")
    if not (agy_bin and os.path.exists(agy_bin) and os.access(agy_bin, os.X_OK)):
        agy_bin = shutil.which("agy") or agy_bin

    if agy_bin and os.path.exists(agy_bin) and os.access(agy_bin, os.X_OK):
        if session_id:
            cmd = [agy_bin, "--conversation", session_id]
        else:
            cmd = [agy_bin]
    elif os.getenv("PROMETEUSZ_CMD"):
        cmd = [os.getenv("PROMETEUSZ_CMD")]
    else:
        cmd = ["/bin/bash"]

    workspace_dir = os.getenv("WORKSPACE_DIR", "/workspace")
    pty_env = os.environ.copy()
    pty_env["HOME"] = "/home/developer"
    pty_env["USER"] = "developer"
    pty = PTYSession(command=cmd, cwd=workspace_dir, env=pty_env)
    try:
        await pty.start()
        active_pty_sessions.add(pty)
    except Exception:
        await websocket.send_text(json.dumps({"type": "error", "message": "Failed to start PTY process"}))
        await websocket.close(code=1011)
        return

    async def forward_pty_output():
        loop = asyncio.get_running_loop()
        while pty.is_alive():
            try:
                data = await loop.run_in_executor(None, pty._nonblocking_read)
                if data:
                    text = data.decode("utf-8", errors="replace")
                    await websocket.send_text(json.dumps({"type": "stdout", "data": text}))
                else:
                    await asyncio.sleep(0.02)
            except Exception:
                break

    output_task = asyncio.create_task(forward_pty_output())

    try:
        while True:
            msg_text = await websocket.receive_text()
            if len(msg_text) > MAX_WS_MESSAGE_SIZE:
                await websocket.send_text(json.dumps({"type": "error", "message": "Payload size exceeds limit"}))
                await websocket.close(code=1009, reason="Message too large")
                break

            try:
                msg = json.loads(msg_text)
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type")
                if msg_type == "stdin":
                    data = msg.get("data", "")
                    if isinstance(data, str):
                        pty.write(data)
                elif msg_type == "resize":
                    try:
                        rows = int(msg.get("rows", 24))
                        cols = int(msg.get("cols", 80))
                        pty.resize(rows, cols)
                    except (ValueError, TypeError):
                        pass
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        active_pty_sessions.discard(pty)
        output_task.cancel()
        try:
            await output_task
        except asyncio.CancelledError:
            pass
        await pty.close()


# Mount frontend dist if built
possible_dist_dirs = [
    Path(os.environ["FRONTEND_DIST_DIR"]) if os.getenv("FRONTEND_DIST_DIR") else None,
    Path(__file__).resolve().parent.parent / "frontend" / "dist",
    Path("/app/frontend/dist"),
    Path("/workspace/prometeusz/frontend/dist"),
]
dist_dir = next((d for d in possible_dist_dirs if d and d.exists() and d.is_dir() and (d / "index.html").is_file()), None)
if dist_dir:
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "6767"))
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=False)
