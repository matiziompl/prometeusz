import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional

DEFAULT_ANTIGRAVITY_DIR = os.getenv("ANTIGRAVITY_CLI_DIR", os.path.expanduser("~/.gemini/antigravity-cli"))

AVAILABLE_MODELS = [
    {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)", "provider": "Google", "speed": "Ultra-Fast", "context": "1M tokens"},
    {"id": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)", "provider": "Google", "speed": "Fast", "context": "1M tokens"},
    {"id": "gemini-3.7-flash-high", "name": "Gemini 3.7 Flash (High)", "provider": "Google", "speed": "Ultra-Fast", "context": "1M tokens"},
    {"id": "gemini-3.1-pro-high", "name": "Gemini 3.1 Pro (High)", "provider": "Google", "speed": "Deep Reasoning", "context": "2M tokens"},
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)", "provider": "Anthropic", "speed": "Deep Reasoning", "context": "200k tokens"},
    {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)", "provider": "Anthropic", "speed": "High Reasoning", "context": "200k tokens"},
    {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)", "provider": "OpenAI", "speed": "Balanced", "context": "128k tokens"},
    {"id": "auto", "name": "Auto (Zalecany)", "provider": "Google", "speed": "Automatyczny", "context": "Dynamiczny"},
]



def get_antigravity_dir() -> Path:
    return Path(os.getenv("ANTIGRAVITY_CLI_DIR", os.path.expanduser("~/.gemini/antigravity-cli"))).resolve()


def get_settings_file_path() -> Path:
    return get_antigravity_dir() / "settings.json"


def get_antigravity_settings() -> Dict[str, Any]:
    path = get_settings_file_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "model": "Gemini 3.8 Flash (High)",
        "toolPermission": "always-proceed",
        "permissions": {"allow": ["command(*)", "read_file(*)", "write_file(*)"]},
        "trustedWorkspaces": ["/workspace"],
    }


def save_antigravity_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    path = get_settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def get_installed_skills() -> List[Dict[str, Any]]:
    skills = []
    seen = set()

    search_dirs = [
        get_antigravity_dir() / "skills",
        get_antigravity_dir() / "builtin" / "skills",
        Path(os.getenv("WORKSPACE_DIR", "/workspace")) / ".agents" / "skills",
    ]

    for base in search_dirs:
        if not base.exists():
            continue
        for entry in base.iterdir():
            if entry.is_dir() and entry.name not in seen:
                skill_file = entry / "SKILL.md"
                description = "Brak opisu"
                name = entry.name
                if skill_file.exists():
                    try:
                        content = skill_file.read_text(encoding="utf-8", errors="replace")
                        for line in content.splitlines():
                            if line.startswith("name:"):
                                name = line.split("name:", 1)[1].strip().strip('"').strip("'")
                            elif line.startswith("description:"):
                                description = line.split("description:", 1)[1].strip().strip('"').strip("'")
                    except Exception:
                        pass
                seen.add(entry.name)
                skills.append({
                    "id": entry.name,
                    "name": name,
                    "description": description,
                    "path": str(entry),
                    "enabled": True,
                })

    skills.sort(key=lambda s: s["name"])
    return skills


def get_models_info() -> Dict[str, Any]:
    settings = get_antigravity_settings()
    current_model = settings.get("model", "Gemini 3.8 Flash (High)")
    return {
        "current_model": current_model,
        "active_model": current_model,
        "models": AVAILABLE_MODELS,
        "available_models": [m["name"] for m in AVAILABLE_MODELS],
    }


def set_active_model(model_name: str) -> Dict[str, Any]:
    settings = get_antigravity_settings()
    settings["model"] = model_name
    save_antigravity_settings(settings)
    return settings


def get_quota_statistics() -> Dict[str, Any]:
    db_path = get_antigravity_dir() / "conversation_summaries.db"
    total_steps = 0
    sessions_count = 0

    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(step_count) FROM conversation_summaries")
            row = cursor.fetchone()
            if row:
                sessions_count = row[0] or 0
                total_steps = row[1] or 0
            conn.close()
        except Exception:
            pass

    # Approximate token calculation based on steps
    if total_steps == 0 and sessions_count == 0:
        est_input_tokens = 0
        est_output_tokens = 0
        est_thinking_tokens = 0
    else:
        est_input_tokens = total_steps * 14500 + 42000
        est_output_tokens = total_steps * 620 + 3800
        est_thinking_tokens = total_steps * 410 + 2100

    return {
        "sessions_count": sessions_count,
        "total_steps": total_steps,
        "input_tokens": est_input_tokens,
        "output_tokens": est_output_tokens,
        "thinking_tokens": est_thinking_tokens,
        "total_tokens": est_input_tokens + est_output_tokens + est_thinking_tokens,
        "quota_limit": 10000000,
        "quota_percentage": round(((est_input_tokens + est_output_tokens) / 10000000) * 100, 2),
    }


def get_installed_agents(agents_dir_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List subagents dynamically discovered from /home/developer/.gemini/config/agents/."""
    agents = []
    configured_dir = agents_dir_path or os.getenv("AGENTS_DIR", "/home/developer/.gemini/config/agents")
    base = Path(configured_dir).resolve()
    if not base.exists():
        fallback = Path(os.path.expanduser("~/.gemini/config/agents")).resolve()
        if fallback.exists():
            base = fallback

    if not base.exists() or not base.is_dir():
        return agents

    for entry in sorted(base.iterdir(), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        agent_id = entry.name
        name = agent_id
        description = ""
        agent_file = entry / "agent.md"
        if agent_file.is_file():
            try:
                content = agent_file.read_text(encoding="utf-8", errors="replace")
                in_frontmatter = False
                for line in content.splitlines():
                    sline = line.strip()
                    if sline == "---":
                        if not in_frontmatter:
                            in_frontmatter = True
                            continue
                        else:
                            break
                    if in_frontmatter or not description:
                        if sline.startswith("name:"):
                            name = sline.split("name:", 1)[1].strip().strip('"').strip("'")
                        elif sline.startswith("description:"):
                            description = sline.split("description:", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass

        agents.append({
            "id": agent_id,
            "name": name,
            "handle": f"@{agent_id}",
            "description": description,
            "path": str(entry),
        })

    return agents

