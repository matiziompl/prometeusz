# 🔥 Prometeusz

<div align="center">

<img src="./logo.png" alt="Prometeusz Logo" width="180" style="border-radius: 16px; margin-bottom: 16px;" />

**A modern, lightweight Web UI and autonomous cockpit for Google Antigravity CLI (`agy`).**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Vite](https://img.shields.io/badge/Vite-6.2+-646CFF.svg?logo=vite&logoColor=white)](https://vitejs.dev/)
[![TailwindCSS](https://img.shields.io/badge/TailwindCSS-4.3+-06B6D4.svg?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-Passing%20(pytest)-brightgreen.svg)](tests/)

</div>

---

## 📖 Overview

**Prometeusz** is a standalone web control panel and companion interface for the **Google Antigravity CLI (`agy`)**. It bridges the gap between terminal-based autonomous agents and interactive web workflows, providing developers with real-time streaming chat, interactive pseudo-terminals (PTY), full session history, visual code diffs, artifact management, and deep system telemetry.

Prometeusz runs as a single lightweight container or local server, giving you complete visibility and control over your AI coding assistants across your local machine, homelab, or developer workstation.

---

## ✨ Features

### 💬 Interactive AI Chat & Streaming Engine
- **Server-Sent Events (SSE) Streaming:** Ultra-low latency token streaming directly from `agy` background runs.
- **Thought Process Inspector:** Collapsible chain-of-thought blocks displaying agent internal reasoning time and rationale.
- **Tool Execution Tracker:** Live feedback on agent actions (file creation, edits, shell commands, web browser automation).
- **Clean Reasoning Formatting:** Automatic XML filtering and rendering for seamless presentation of agent thoughts.
- **Rich Markdown Support:** Code syntax highlighting with one-click copy buttons and sanitized HTML via DOMPurify.

### ⚡ Interactive Web Terminal (PTY)
- **Real-time Terminal via WebSockets:** Powered by `xterm.js` and `@xterm/addon-fit`.
- **Bi-directional Streaming:** Full interactive console support for shell sessions and direct `agy` interaction.
- **Process Lifecycle Management:** Cancel/interrupt (`Ctrl+C`) active agent executions on demand with graceful cleanup.

### 📂 Comprehensive Session Management
- **Session Switcher & Status Badges:** Live indicators for active, completed, or running tasks.
- **Full-Text Search:** Search instantly across conversation histories, summaries, prompts, and code transcripts.
- **Organization & Pinning:** Group sessions into custom folders, pin critical threads, or reorder tasks.
- **Visual Git Diff Viewer:** Inspect exact file modifications and diffs generated during any session.
- **Artifacts Explorer:** View, inspect, and export generated plans, code snippets, and research documents.
- **Session Forking & Export:** Clone existing sessions from any checkpoint or export transcripts to JSON/Markdown.

### ⚙️ Antigravity Model & Quota Control
- **Dynamic Model Switcher:** Switch seamlessly between supported reasoning models:
  - Gemini 3.8 Flash (High / Medium)
  - Gemini 3.7 Flash
  - Gemini 3.1 Pro (Deep Reasoning)
  - Claude Sonnet 4.6 & Claude Opus 4.6
  - GPT-OSS 120B
  - Auto-routing mode
- **Quota & Limits Monitor:** Visual indicators for Gemini API usage, rate limits, and remaining credits.
- **Skills & Subagents Catalog:** Browse installed skills (`.agents/skills`) and configured subagents with descriptions.

### 📊 Real-Time System Telemetry
- **Hardware Telemetry Gauges:** Live CPU load, RAM allocation (Used / Available / Total), and Disk storage percentages polled via `psutil`.

### 📁 Workspace & File Management
- **File Upload Manager:** Drag-and-drop file upload interface supporting documents, images, and project data.
- **File System Explorer:** In-browser file inspector for exploring generated artifacts and workspace files.

### ⌨️ Slash Commands Engine
Built-in slash command autocompletion in the chat input:
| Command | Description |
| :--- | :--- |
| `/goal` | Launch a long-running autonomous task |
| `/plan` | Generate a structured, step-by-step engineering plan |
| `/browser` | Web automation and inspection with Playwright |
| `/grill-me` | Interactive architectural decision interview |
| `/teamwork-preview` | Multi-agent coordination and preview |
| `/skills` | Browse and activate installed agent skills |
| `/model` | Switch the active AI reasoning model |
| `/boost` | Enable deep reasoning and strict verification mode |
| `/learn` | Persist learned engineering guidelines and project rules |
| `/settings` | Open configuration and preferences panel |
| `/help` | Display shortcuts and command help |

---

## 🏗️ Architecture

```
                                  ┌───────────────────────────────┐
                                  │      Prometeusz Web UI        │
                                  │  (Vite + Vanilla JS + xterm)  │
                                  └───────────────┬───────────────┘
                                                  │
                                      HTTP / SSE / WebSocket
                                                  │
                                  ┌───────────────▼───────────────┐
                                  │       FastAPI Backend         │
                                  │      (Python 3.12-slim)       │
                                  └───────┬───────────────┬───────┘
                                          │               │
                     ┌────────────────────┴─────┐   ┌─────┴──────────────────┐
                     │ PTY Manager & WebSocket  │   │ Session & Chat Engine  │
                     │  (pty.fork / termios)    │   │  (agy resume / stream) │
                     └─────────────┬────────────┘   └─────┬──────────────────┘
                                   │                      │
                                   ▼                      ▼
                     ┌────────────────────────────────────────────┐
                     │          Google Antigravity CLI            │
                     │      (/home/developer/.gemini/...)         │
                     └────────────────────────────────────────────┘
```

- **Frontend:** Pure ES modules, Vite 6, Tailwind CSS v4, xterm.js. Zero frontend framework overhead (no React/Vue runtime penalty) ensuring instant load times and minimal memory footprint.
- **Backend:** FastAPI (Python 3.12), Uvicorn ASGI server, asynchronous WebSockets, SSE streams, `psutil` system metrics, and robust security sanitizers.

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

Prometeusz is pre-configured for Docker. A multi-stage build creates a tiny, production-ready image.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/prometeusz.git
   cd prometeusz
   ```

2. **Configure your environment:**
   Copy the `.env.example` template:
   ```bash
   cp .env.example .env
   ```
   Adjust the host paths in `.env` if necessary:
   ```env
   PORT=6767
   ANTIGRAVITY_CLI_HOST_DIR=~/.gemini/antigravity-cli
   AGY_BIN_HOST_PATH=~/.local/bin/agy
   WORKSPACE_HOST_DIR=~/workspace
   ```

3. **Start the container:**
   ```bash
   docker compose up --build -d
   ```

4. **Access the Web UI:**
   Open your browser at `http://localhost:6767` (or `http://<server-ip>:6767`).

---

### Option 2: Local Development Setup

#### 1. Backend Setup
Ensure you have Python 3.12+ installed:
```bash
# Optional: create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install fastapi "uvicorn[standard]" websockets psutil
```

#### 2. Frontend Setup
Ensure you have Node.js 20+ installed:
```bash
cd frontend
npm install
npm run build
cd ..
```

#### 3. Run the Application
```bash
# Run backend with compiled static frontend
python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 6767
```

For live frontend hot-reloading during UI development:
```bash
# Terminal 1: Backend
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Vite Dev Server
cd frontend
npm run dev
# Vite will proxy API and WS requests to http://127.0.0.1:8000
```

---

## ⚙️ Configuration & Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PORT` | HTTP port exposed by the backend | `6767` |
| `WORKSPACE_DIR` | Absolute path to the active coding workspace | `/workspace` |
| `ANTIGRAVITY_CLI_DIR` | Directory containing Antigravity metadata & `brain/` | `~/.gemini/antigravity-cli` |
| `AGY_BIN` | Path to the `agy` CLI executable | `/usr/local/bin/agy` |
| `PYTHONUNBUFFERED` | Flushes Python standard output immediately | `1` |

---

## 🔒 Security Architecture

Prometeusz incorporates defensive security controls to protect the host and developer environment:

- **Path Traversal Mitigation:** Strict UUID regex validation (`/^[a-f0-9-]{36}$/i`) on all session and conversation IDs before accessing disk paths.
- **Cross-Site WebSocket Hijacking (CSWSH) Defense:** Origin header enforcement validating loopback, local subnet CIDRs (`192.168.x.x`, `10.x.x.x`, `172.x.x.x`), and authorized hostnames.
- **WebSocket Protection:** Frame payload limits (64 KB ceiling) and concurrent PTY session throttling (`MAX_CONCURRENT_PTY = 5`) to prevent resource exhaustion.
- **Repository Hygiene:** Built-in `.gitignore` and `.dockerignore` prevent committing personal paths, cache directories, virtual environments, session databases, or `.env` credential files.

---

## 🧪 Testing

Prometeusz includes a comprehensive test suite covering API endpoints, WebSocket lifecycles, chat streaming, XML sanitization, and security boundaries.

Run tests using `pytest`:
```bash
pytest
```

Run tests with verbose output:
```bash
pytest -v
```

---

## 📂 Directory Structure

```
prometeusz/
├── backend/
│   ├── app.py                   # FastAPI main entrypoint, endpoints & WebSocket handlers
│   ├── chat_engine.py           # Background agy process manager & SSE stream adapter
│   ├── metrics.py               # Hardware & system metrics provider (psutil)
│   ├── pty_manager.py           # Interactive PTY session and terminal lifecycle
│   ├── sessions.py              # Session database parser, diff engine & artifact reader
│   └── settings_manager.py      # Antigravity settings, skills, and model management
├── frontend/
│   ├── src/
│   │   ├── main.js              # Application state, UI controllers, and WebSocket client
│   │   └── style.css            # Custom CSS & Tailwind styles
│   ├── index.html               # Main single-page application interface
│   ├── package.json             # NPM dependencies & build scripts
│   └── vite.config.js           # Vite configuration & backend proxy rules
├── tests/                       # Pytest unit, integration, and security test suite
├── Dockerfile                   # Multi-stage production container definition
├── docker-compose.yml           # Compose specification with environment interpolation
├── .env.example                 # Environment configuration template
├── .gitignore                   # Version control ignore rules
├── .dockerignore                 # Docker context ignore rules
├── logo.png                     # Prometeusz brand logo
└── README.md                    # Project documentation
```

---

## 📄 License

This project is open-source. Refer to the project repository for licensing terms.
