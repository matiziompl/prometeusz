import difflib
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_ANTIGRAVITY_DIR = os.path.expanduser("~/.gemini/antigravity-cli")
CONVERSATION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")
SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\. ]+$")


def get_antigravity_dir(base_dir: Optional[str] = None) -> Path:
    return Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()


def _parse_timestamp(val: Any) -> float:
    if not val:
        return 0.0
    val_str = str(val).strip()
    try:
        return float(val_str)
    except ValueError:
        pass
    try:
        clean_str = val_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str).timestamp()
    except Exception:
        return 0.0


def validate_conversation_id(conversation_id: str) -> str:
    """Validate conversation_id to prevent path traversal and argument injection."""
    if not conversation_id or not isinstance(conversation_id, str):
        raise ValueError("conversation_id must be a non-empty string")
    if len(conversation_id) > 128:
        raise ValueError("conversation_id exceeds maximum length (128)")
    if conversation_id.startswith("-"):
        raise ValueError("conversation_id cannot start with a hyphen")
    if not CONVERSATION_ID_REGEX.match(conversation_id):
        raise ValueError("conversation_id contains invalid characters")
    return conversation_id


def validate_filename(filename: str) -> str:
    """Validate artifact filename to prevent directory traversal."""
    if not filename or not isinstance(filename, str):
        raise ValueError("filename must be a non-empty string")
    if len(filename) > 255:
        raise ValueError("filename exceeds maximum length (255)")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("filename cannot contain path traversal sequences or directory separators")
    if not SAFE_FILENAME_REGEX.match(filename):
        raise ValueError("filename contains invalid characters")
    return filename


def clean_transcript_xml(text: Optional[str]) -> str:
    """Clean raw XML tags from transcripts, extracting pure user prompt content."""
    if not text or not isinstance(text, str):
        return ""

    # 1. If <USER_REQUEST>...</USER_REQUEST> tags exist, extract their contents
    user_requests = re.findall(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, flags=re.DOTALL | re.IGNORECASE)
    if user_requests:
        clean = "\n\n".join(req.strip() for req in user_requests if req.strip())
        return clean.strip()

    # 2. If no <USER_REQUEST> tags, remove <ADDITIONAL_METADATA> and <USER_SETTINGS_CHANGE> blocks
    clean = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<SYSTEM_MESSAGE>.*?</SYSTEM_MESSAGE>", "", clean, flags=re.DOTALL | re.IGNORECASE)

    # 3. Strip any stray opening/closing XML tags for these metadata types
    clean = re.sub(r"</?(?:USER_REQUEST|ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)[^>]*>", "", clean, flags=re.IGNORECASE)

    return clean.strip()


def _get_metadata_db_conn(base_dir: Optional[str] = None) -> sqlite3.Connection:
    """Get connection to Prometeusz session metadata SQLite DB."""
    root_dir = get_antigravity_dir(base_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    meta_db_path = root_dir / "session_metadata.db"
    conn = sqlite3.connect(str(meta_db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            conversation_id TEXT PRIMARY KEY,
            title_override TEXT DEFAULT NULL,
            pinned INTEGER DEFAULT 0,
            folder TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0
        )
        """
    )
    try:
        conn.execute("ALTER TABLE metadata ADD COLUMN deleted INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def get_sessions(base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve list of conversation sessions with metadata (pinned, folder, ordering)."""
    root_dir = get_antigravity_dir(base_dir)
    db_path = root_dir / "conversation_summaries.db"
    sessions_map: Dict[str, Dict[str, Any]] = {}

    # 1. Read from SQLite summaries DB if present
    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(conversation_summaries)")
            col_names = {row[1] for row in cursor.fetchall()}

            conditions = []
            if "parent_conversation_id" in col_names:
                conditions.append("(parent_conversation_id IS NULL OR parent_conversation_id = '')")
            if "nesting_depth" in col_names:
                conditions.append("(nesting_depth IS NULL OR nesting_depth = 0)")
            if "step_count" in col_names:
                conditions.append("step_count > 0")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""
                SELECT conversation_id, title, preview, step_count, last_modified_time, status
                FROM conversation_summaries
                {where_clause}
                ORDER BY last_modified_time DESC
            """
            cursor.execute(query)
            for row in cursor.fetchall():
                conv_id, title, preview, step_count, last_mod, status = row
                try:
                    validate_conversation_id(conv_id)
                except ValueError:
                    continue
                clean_preview = clean_transcript_xml(preview) if preview else ""
                sessions_map[conv_id] = {
                    "conversation_id": conv_id,
                    "title": title or f"Session {conv_id[:8]}",
                    "preview": clean_preview,
                    "step_count": step_count or 0,
                    "last_modified": str(last_mod),
                    "status": status or "IDLE",
                    "pinned": False,
                    "folder": "",
                    "sort_order": 0,
                }
            conn.close()
        except Exception:
            pass

    # 2. Enrich with metadata (pinned, folder, title overrides, sort_order) and exclude deleted
    deleted_ids = set()
    try:
        mconn = _get_metadata_db_conn(str(root_dir))
        mcursor = mconn.cursor()
        mcursor.execute("SELECT conversation_id, title_override, pinned, folder, sort_order, deleted FROM metadata")
        for row in mcursor.fetchall():
            cid, toverride, pinned, folder, sort_order, deleted = row
            if deleted:
                deleted_ids.add(cid)
            elif cid in sessions_map:
                if toverride:
                    sessions_map[cid]["title"] = toverride
                sessions_map[cid]["pinned"] = bool(pinned)
                sessions_map[cid]["folder"] = folder or ""
                sessions_map[cid]["sort_order"] = sort_order or 0
        mconn.close()
    except Exception:
        pass

    for did in deleted_ids:
        sessions_map.pop(did, None)

    # Sort: pinned first, then by sort_order ascending, then by last_modified descending
    sessions_list = list(sessions_map.values())
    sessions_list.sort(key=lambda s: (not s.get("pinned", False), s.get("sort_order", 0), -_parse_timestamp(s.get("last_modified"))))
    return sessions_list


def delete_session(conversation_id: str, base_dir: Optional[str] = None) -> bool:
    """Delete a session from database, metadata, and disk."""
    validate_conversation_id(conversation_id)
    root_dir = get_antigravity_dir(base_dir)

    # 1. Delete from conversation_summaries.db
    db_path = root_dir / "conversation_summaries.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (conversation_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # 2. Mark deleted in session_metadata.db
    try:
        mconn = _get_metadata_db_conn(str(root_dir))
        mconn.execute(
            """
            INSERT INTO metadata (conversation_id, deleted)
            VALUES (?, 1)
            ON CONFLICT(conversation_id) DO UPDATE SET deleted = 1
            """,
            (conversation_id,),
        )
        mconn.commit()
        mconn.close()
    except Exception:
        pass

    # 3. Remove brain folder
    brain_folder = (root_dir / "brain" / conversation_id).resolve()
    try:
        brain_folder.relative_to(root_dir / "brain")
        if brain_folder.exists() and brain_folder.is_dir():
            shutil.rmtree(str(brain_folder), ignore_errors=True)
    except ValueError:
        raise PermissionError("Path traversal detected")

    # 4. Remove alternative folder if present
    alt_folder = (root_dir / conversation_id).resolve()
    try:
        alt_folder.relative_to(root_dir)
        if alt_folder.exists() and alt_folder.is_dir() and alt_folder.name == conversation_id:
            shutil.rmtree(str(alt_folder), ignore_errors=True)
    except ValueError:
        pass

    # 5. Remove conversations folder/files (.db, .db-wal, .db-shm, etc.) if present
    convs_dir = root_dir / "conversations"
    if convs_dir.exists() and convs_dir.is_dir():
        for f in convs_dir.glob(f"{conversation_id}*"):
            try:
                if f.is_dir():
                    shutil.rmtree(str(f), ignore_errors=True)
                else:
                    f.unlink()
            except Exception:
                pass

    return True


def fork_session(conversation_id: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Fork an existing conversation session into a new conversation with a new ID."""
    validate_conversation_id(conversation_id)
    root_dir = get_antigravity_dir(base_dir)

    # 1. Verify existence of source session
    db_path = root_dir / "conversation_summaries.db"
    orig_row = None
    col_names: List[str] = []
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(conversation_summaries)")
            col_info = cursor.fetchall()
            col_names = [col[1] for col in col_info]
            cursor.execute("SELECT * FROM conversation_summaries WHERE conversation_id = ?", (conversation_id,))
            orig_row = cursor.fetchone()
            conn.close()
        except Exception:
            pass

    brain_dir = (root_dir / "brain" / conversation_id).resolve()
    conv_db_file = (root_dir / "conversations" / f"{conversation_id}.db").resolve()

    if orig_row is None and not brain_dir.exists() and not conv_db_file.exists():
        raise FileNotFoundError(f"Session {conversation_id} not found")

    new_conversation_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    # 2. Insert new row in conversation_summaries.db
    new_title = f"Session {new_conversation_id[:8]} (Fork)"
    if orig_row is not None and col_names:
        row_dict = dict(zip(col_names, orig_row))
        old_title = row_dict.get("title") or ""
        new_title = f"{old_title} (Fork)" if old_title else f"Session {new_conversation_id[:8]} (Fork)"
        row_dict["conversation_id"] = new_conversation_id
        row_dict["title"] = new_title
        row_dict["last_modified_time"] = now_iso
        if "parent_conversation_id" in row_dict:
            row_dict["parent_conversation_id"] = ""
        if "nesting_depth" in row_dict:
            row_dict["nesting_depth"] = 0

        try:
            conn = sqlite3.connect(str(db_path))
            cols = list(row_dict.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [row_dict[c] for c in cols]
            conn.execute(f"INSERT INTO conversation_summaries ({col_str}) VALUES ({placeholders})", vals)
            conn.commit()
            conn.close()
        except Exception:
            pass
    elif db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "INSERT INTO conversation_summaries (conversation_id, title, preview, step_count, last_modified_time, status) VALUES (?, ?, ?, ?, ?, ?)",
                (new_conversation_id, new_title, "Sforkowana rozmowa", 0, now_iso, "IDLE"),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    # 3. Copy conversations DB file if present
    if conv_db_file.exists():
        new_conv_db = root_dir / "conversations" / f"{new_conversation_id}.db"
        new_conv_db.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(conv_db_file), str(new_conv_db))
            try:
                cconn = sqlite3.connect(str(new_conv_db))
                cconn.execute("UPDATE trajectory_meta SET cascade_id = ?", (new_conversation_id,))
                cconn.commit()
                cconn.close()
            except Exception:
                pass
        except Exception:
            pass

    # 4. Copy brain folder if present
    if brain_dir.exists() and brain_dir.is_dir():
        new_brain_dir = root_dir / "brain" / new_conversation_id
        new_brain_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(str(brain_dir), str(new_brain_dir))
        except Exception:
            pass

    # 5. Copy metadata in session_metadata.db
    try:
        mconn = _get_metadata_db_conn(str(root_dir))
        cursor = mconn.cursor()
        cursor.execute("SELECT folder FROM metadata WHERE conversation_id = ?", (conversation_id,))
        mrow = cursor.fetchone()
        folder = mrow[0] if mrow else ""
        mconn.execute(
            """
            INSERT INTO metadata (conversation_id, title_override, folder, sort_order, deleted)
            VALUES (?, ?, ?, 0, 0)
            """,
            (new_conversation_id, new_title, folder),
        )
        mconn.commit()
        mconn.close()
    except Exception:
        pass

    return {
        "success": True,
        "conversation_id": new_conversation_id,
        "title": new_title,
        "parent_conversation_id": conversation_id,
    }


def rename_session(conversation_id: str, new_title: str, base_dir: Optional[str] = None) -> bool:
    """Rename a session title in summaries and metadata DB."""
    validate_conversation_id(conversation_id)
    clean_title = (new_title or "").strip()
    if not clean_title:
        raise ValueError("Tytuł sesji nie może być pusty")

    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()

    # Update in conversation_summaries.db
    db_path = root_dir / "conversation_summaries.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("UPDATE conversation_summaries SET title = ? WHERE conversation_id = ?", (clean_title, conversation_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # Record in session_metadata.db
    try:
        mconn = _get_metadata_db_conn(str(root_dir))
        mconn.execute(
            """
            INSERT INTO metadata (conversation_id, title_override)
            VALUES (?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET title_override = excluded.title_override
            """,
            (conversation_id, clean_title),
        )
        mconn.commit()
        mconn.close()
    except Exception:
        pass

    return True


def toggle_pin_session(conversation_id: str, pinned: Optional[bool] = None, base_dir: Optional[str] = None) -> bool:
    """Pin or unpin a session."""
    validate_conversation_id(conversation_id)
    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()
    mconn = _get_metadata_db_conn(str(root_dir))
    cursor = mconn.cursor()

    if pinned is None:
        cursor.execute("SELECT pinned FROM metadata WHERE conversation_id = ?", (conversation_id,))
        row = cursor.fetchone()
        new_val = 0 if (row and row[0]) else 1
    else:
        new_val = 1 if pinned else 0

    cursor.execute(
        """
        INSERT INTO metadata (conversation_id, pinned)
        VALUES (?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET pinned = excluded.pinned
        """,
        (conversation_id, new_val),
    )
    mconn.commit()
    mconn.close()
    return bool(new_val)


def set_session_folder(conversation_id: str, folder: str, base_dir: Optional[str] = None) -> bool:
    """Assign a session to a folder."""
    validate_conversation_id(conversation_id)
    clean_folder = (folder or "").strip()
    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()
    mconn = _get_metadata_db_conn(str(root_dir))
    mconn.execute(
        """
        INSERT INTO metadata (conversation_id, folder)
        VALUES (?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET folder = excluded.folder
        """,
        (conversation_id, clean_folder),
    )
    mconn.commit()
    mconn.close()
    return True


def update_sessions_order(order_list: List[str], base_dir: Optional[str] = None) -> bool:
    """Save user manual drag-and-drop sort order for sessions."""
    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()
    mconn = _get_metadata_db_conn(str(root_dir))
    for idx, cid in enumerate(order_list):
        try:
            validate_conversation_id(cid)
            mconn.execute(
                """
                INSERT INTO metadata (conversation_id, sort_order)
                VALUES (?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET sort_order = excluded.sort_order
                """,
                (cid, idx),
            )
        except ValueError:
            continue
    mconn.commit()
    mconn.close()
    return True


def get_folders(base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve list of user-created folders."""
    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()
    mconn = _get_metadata_db_conn(str(root_dir))
    cursor = mconn.cursor()
    cursor.execute("SELECT id, name, created_at FROM folders ORDER BY name ASC")
    folders = [{"id": row[0], "name": row[1], "created_at": str(row[2])} for row in cursor.fetchall()]
    mconn.close()
    return folders


def create_folder(folder_name: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Create a new session folder."""
    clean_name = (folder_name or "").strip()
    if not clean_name:
        raise ValueError("Nazwa folderu nie może być pusta")
    folder_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", clean_name.lower())
    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()
    mconn = _get_metadata_db_conn(str(root_dir))
    mconn.execute("INSERT OR REPLACE INTO folders (id, name) VALUES (?, ?)", (folder_id, clean_name))
    mconn.commit()
    mconn.close()
    return {"id": folder_id, "name": clean_name}


def delete_folder(folder_id: str, base_dir: Optional[str] = None) -> bool:
    """Delete a folder and unassign associated sessions."""
    root_dir = Path(base_dir or os.getenv("ANTIGRAVITY_CLI_DIR", DEFAULT_ANTIGRAVITY_DIR)).resolve()
    mconn = _get_metadata_db_conn(str(root_dir))
    mconn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
    mconn.execute("UPDATE metadata SET folder = '' WHERE folder = ?", (folder_id,))
    mconn.commit()
    mconn.close()
    return True


def get_session_details(conversation_id: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Parse transcript log for a given conversation into structured messages."""
    validate_conversation_id(conversation_id)
    root_dir = get_antigravity_dir(base_dir)
    brain_dir = (root_dir / "brain").resolve()
    conv_brain_dir = (brain_dir / conversation_id).resolve()

    try:
        conv_brain_dir.relative_to(brain_dir)
    except ValueError:
        raise PermissionError("Path traversal detected")

    if not conv_brain_dir.exists() and (root_dir / conversation_id).resolve().exists():
        alt_dir = (root_dir / conversation_id).resolve()
        try:
            alt_dir.relative_to(root_dir)
            conv_brain_dir = alt_dir
        except ValueError:
            raise PermissionError("Path traversal detected")

    transcript_file = conv_brain_dir / ".system_generated" / "logs" / "transcript.jsonl"
    if not transcript_file.exists():
        transcript_file = conv_brain_dir / ".system_generated" / "logs" / "transcript_full.jsonl"

    messages: List[Dict[str, Any]] = []

    if transcript_file.exists():
        try:
            with open(transcript_file, "r", encoding="utf-8") as f:
                current_assistant_msg: Optional[Dict[str, Any]] = None

                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    rec_type = record.get("type")
                    source = record.get("source")
                    step_index = record.get("step_index", len(messages))

                    if rec_type == "USER_INPUT" or source == "USER_EXPLICIT":
                        if current_assistant_msg is not None:
                            messages.append(current_assistant_msg)
                            current_assistant_msg = None

                        raw_content = record.get("content", "")
                        clean_content = clean_transcript_xml(raw_content)

                        messages.append({
                            "step_index": step_index,
                            "role": "user",
                            "content": clean_content,
                            "timestamp": record.get("created_at", ""),
                        })

                    elif source == "MODEL" or rec_type in ("PLANNER_RESPONSE", "GENERIC"):
                        raw_tools = record.get("tool_calls", []) or []
                        normalized_tools = []
                        for t in raw_tools:
                            tc = dict(t)
                            if "args" in tc and "arguments" not in tc:
                                tc["arguments"] = tc["args"]
                            elif "arguments" in tc and "args" not in tc:
                                tc["args"] = tc["arguments"]
                            normalized_tools.append(tc)

                        if current_assistant_msg is None:
                            current_assistant_msg = {
                                "step_index": step_index,
                                "role": "assistant",
                                "thinking": record.get("thinking", ""),
                                "tool_calls": normalized_tools,
                                "content": record.get("content", ""),
                                "timestamp": record.get("created_at", ""),
                            }
                        else:
                            if record.get("thinking"):
                                current_assistant_msg["thinking"] = (
                                    (current_assistant_msg["thinking"] + "\n" + record["thinking"])
                                    if current_assistant_msg["thinking"]
                                    else record["thinking"]
                                )
                            if normalized_tools:
                                current_assistant_msg["tool_calls"].extend(normalized_tools)

                            rec_content = record.get("content")
                            if rec_content:
                                if rec_type == "GENERIC" and current_assistant_msg["tool_calls"]:
                                    last_tc = current_assistant_msg["tool_calls"][-1]
                                    if "output" not in last_tc:
                                        last_tc["output"] = rec_content
                                    else:
                                        current_assistant_msg["content"] = (
                                            (current_assistant_msg["content"] + "\n\n" + rec_content)
                                            if current_assistant_msg["content"]
                                            else rec_content
                                        )
                                else:
                                    current_assistant_msg["content"] = (
                                        (current_assistant_msg["content"] + "\n\n" + rec_content)
                                        if current_assistant_msg["content"]
                                        else rec_content
                                    )

                if current_assistant_msg is not None:
                    messages.append(current_assistant_msg)
        except Exception:
            pass

    return {
        "conversation_id": conversation_id,
        "messages": messages,
    }


def search_sessions(query: str, base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Perform full-text search across session summaries, messages, and code transcripts."""
    clean_query = (query or "").strip().lower()
    if not clean_query:
        return get_sessions(base_dir)

    all_sessions = get_sessions(base_dir)
    matched_results: List[Dict[str, Any]] = []

    for s in all_sessions:
        cid = s["conversation_id"]
        title = s.get("title", "")
        preview = s.get("preview", "")

        # Direct match in title or preview
        if clean_query in title.lower() or clean_query in preview.lower():
            s_copy = dict(s)
            s_copy["match_snippet"] = preview[:160] if clean_query in preview.lower() else title
            matched_results.append(s_copy)
            continue

        # Deep search in transcript logs
        try:
            details = get_session_details(cid, base_dir=base_dir)
            found_snippet = None
            for msg in details.get("messages", []):
                content = msg.get("content", "")
                thinking = msg.get("thinking", "")

                if clean_query in content.lower():
                    idx = content.lower().find(clean_query)
                    start = max(0, idx - 40)
                    end = min(len(content), idx + len(clean_query) + 80)
                    found_snippet = ("..." if start > 0 else "") + content[start:end].replace("\n", " ") + ("..." if end < len(content) else "")
                    break

                if clean_query in thinking.lower():
                    idx = thinking.lower().find(clean_query)
                    start = max(0, idx - 40)
                    end = min(len(thinking), idx + len(clean_query) + 80)
                    found_snippet = ("..." if start > 0 else "") + thinking[start:end].replace("\n", " ") + ("..." if end < len(thinking) else "")
                    break

                for tc in msg.get("tool_calls", []):
                    tc_str = (str(tc.get("name", "")) + " " + str(tc.get("args", tc.get("arguments", "")))).lower()
                    if clean_query in tc_str:
                        found_snippet = f"Tool: {tc.get('name', 'tool')} ({clean_query})"
                        break
                if found_snippet:
                    break

            if found_snippet:
                s_copy = dict(s)
                s_copy["match_snippet"] = found_snippet
                matched_results.append(s_copy)
        except Exception:
            pass

    return matched_results


def export_session(conversation_id: str, format_type: str = "markdown", base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Export conversation session to Markdown or JSON."""
    details = get_session_details(conversation_id, base_dir=base_dir)
    messages = details.get("messages", [])

    if format_type.lower() == "json":
        return {
            "filename": f"session-{conversation_id}.json",
            "media_type": "application/json",
            "content": json.dumps(details, indent=2, ensure_ascii=False),
        }

    # Markdown export
    lines = [
        f"# Prometeusz Session Export",
        f"- **Session ID:** `{conversation_id}`",
        f"- **Total Messages:** {len(messages)}",
        f"\n---\n",
    ]

    for msg in messages:
        role = msg.get("role", "unknown").upper()
        ts = msg.get("timestamp", "")
        content = msg.get("content", "")
        thinking = msg.get("thinking", "")
        tool_calls = msg.get("tool_calls", [])

        lines.append(f"### {role} {f'({ts})' if ts else ''}\n")
        if thinking:
            lines.append(f"> **Thought:**\n> {thinking.replace(chr(10), chr(10) + '> ')}\n")

        if tool_calls:
            lines.append("**Tool Executions:**")
            for t in tool_calls:
                t_name = t.get("toolSummary") or t.get("name", "Tool")
                args = t.get("args") or t.get("arguments", {})
                t_args = json.dumps(args, indent=2)
                lines.append(f"```json\n// {t_name}\n{t_args}\n```")

        if content:
            lines.append(content)
        lines.append("\n---\n")

    return {
        "filename": f"session-{conversation_id}.md",
        "media_type": "text/markdown",
        "content": "\n".join(lines),
    }


def get_session_changes(conversation_id: str, base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Extract files modified strictly in THIS session from transcript tool calls."""
    validate_conversation_id(conversation_id)
    details = get_session_details(conversation_id, base_dir=base_dir)
    modified_files: Dict[str, Dict[str, Any]] = {}

    for msg in details.get("messages", []):
        for tool in msg.get("tool_calls", []):
            name = tool.get("name") or tool.get("toolAction") or ""
            args = tool.get("args") or tool.get("arguments", {})
            target_file = None

            if isinstance(args, dict):
                target_file = (
                    args.get("TargetFile")
                    or args.get("target_file")
                    or args.get("file_path")
                    or args.get("path")
                    or args.get("AbsolutePath")
                    or args.get("absolute_path")
                )

            if target_file and isinstance(target_file, str):
                p = Path(target_file)
                filename = p.name
                exists = p.exists()
                size = p.stat().st_size if exists else 0
                lines_count = 0
                if exists and p.is_file():
                    try:
                        lines_count = len(p.read_text(errors="ignore").splitlines())
                    except Exception:
                        pass
                modified_files[target_file] = {
                    "path": target_file,
                    "filename": filename,
                    "action": name,
                    "exists": exists,
                    "size": size,
                    "lines_count": lines_count,
                }

    return list(modified_files.values())


def get_file_diff(file_path: str) -> Dict[str, Any]:
    """Generate inline and side-by-side diff representation for a modified file."""
    p = Path(file_path).resolve()

    # Validate file path is within allowed directories
    allowed_roots = [
        Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve(),
        get_antigravity_dir(),
        Path("/tmp").resolve(),
    ]
    is_allowed = any(p == root or root in p.parents for root in allowed_roots if root.exists())
    if not is_allowed:
        return {"error": "Access denied: file outside permitted directories"}

    if not (p.exists() and p.is_file()):
        return {"error": "File does not exist on disk"}

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Failed to read file: {e}"}

    lines = content.splitlines(keepends=True)

    return {
        "path": str(p),
        "filename": p.name,
        "content": content,
        "lines": [
            {"num": i + 1, "text": line.rstrip("\n\r"), "type": "neutral"}
            for i, line in enumerate(lines[:500])
        ],
    }


def get_session_artifacts(conversation_id: str, base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """List generated artifacts in a conversation directory."""
    validate_conversation_id(conversation_id)
    root_dir = get_antigravity_dir(base_dir)
    brain_dir = (root_dir / "brain").resolve()
    conv_brain_dir = (brain_dir / conversation_id).resolve()

    try:
        conv_brain_dir.relative_to(brain_dir)
    except ValueError:
        raise PermissionError("Path traversal detected")

    if not conv_brain_dir.exists() and (root_dir / conversation_id).resolve().exists():
        alt_dir = (root_dir / conversation_id).resolve()
        try:
            alt_dir.relative_to(root_dir)
            conv_brain_dir = alt_dir
        except ValueError:
            raise PermissionError("Path traversal detected")

    artifacts: List[Dict[str, Any]] = []

    if conv_brain_dir.exists() and conv_brain_dir.is_dir():
        for item in conv_brain_dir.iterdir():
            if item.is_file() and not item.name.startswith("."):
                stat = item.stat()
                is_previewable = item.suffix.lower() in {".html", ".htm", ".svg", ".md", ".txt", ".json", ".js", ".css"}
                is_html_or_svg = item.suffix.lower() in {".html", ".htm", ".svg"}
                artifacts.append({
                    "name": item.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "path": str(item.relative_to(conv_brain_dir)),
                    "previewable": is_previewable,
                    "is_live_render": is_html_or_svg,
                })

    return artifacts


def get_artifact_content(conversation_id: str, filename: str, base_dir: Optional[str] = None) -> Optional[str]:
    """Safely read content of an artifact file preventing directory traversal."""
    validate_conversation_id(conversation_id)
    validate_filename(filename)

    root_dir = get_antigravity_dir(base_dir)
    brain_dir = (root_dir / "brain").resolve()
    conv_brain_dir = (brain_dir / conversation_id).resolve()

    try:
        conv_brain_dir.relative_to(brain_dir)
    except ValueError:
        raise PermissionError("Path traversal detected")

    if not conv_brain_dir.exists() and (root_dir / conversation_id).resolve().exists():
        alt_dir = (root_dir / conversation_id).resolve()
        try:
            alt_dir.relative_to(root_dir)
            conv_brain_dir = alt_dir
        except ValueError:
            raise PermissionError("Path traversal detected")

    target_file = (conv_brain_dir / filename).resolve()

    try:
        target_file.relative_to(conv_brain_dir)
    except ValueError:
        raise PermissionError("Path traversal detected")

    if target_file.exists() and target_file.is_file():
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return None
