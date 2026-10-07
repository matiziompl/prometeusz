import os
import shutil
import sqlite3
import sys
from pathlib import Path
import pytest

sys.path.insert(0, "/workspace/prometeusz")
TEST_DIR = Path("/tmp/test_prometeusz")


@pytest.fixture(scope="session", autouse=True)
def isolate_test_environment():
    """
    KRYTYCZNA IZOLACJA ŚRODOWISKA TESTOWEGO (AGENTS.md Item 2):
    Gwarantuje, że testy pytest operują wyłącznie w /tmp/test_prometeusz/
    i NIGDY nie dotykają ani nie zanieczyszczają produkcyjnej bazy ~/.gemini/antigravity-cli/.
    """
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    brain_dir = TEST_DIR / "brain"
    brain_dir.mkdir(parents=True, exist_ok=True)

    # Inicjalizacja izolowanej bazy SQLite dla sesji testowych
    db_path = TEST_DIR / "conversation_summaries.db"
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
    conn.execute(
        """
        INSERT INTO conversation_summaries VALUES
        ('test-session-001', 'Testowa Sesja Izolowana', 'Podgląd izolowanej sesji testowej', 2, '2026-10-05 00:00:00', 'COMPLETED')
        """
    )
    conn.commit()
    conn.close()

    # Tworzenie transkryptu testowego
    sess_brain = brain_dir / "test-session-001"
    logs_dir = sess_brain / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    transcript_file = logs_dir / "transcript.jsonl"
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write('{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","content":"Weryfikacja automatyczna Playwright E2E","created_at":"2026-10-05T00:00:00Z"}\n')
        f.write('{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","thinking":"Inicjalizacja testowa.","tool_calls":[{"name":"Bash Execution","toolAction":"run_command","arguments":{"cmd":"echo TEST_OK"}}],"content":"Otrzymano i przekazano polecenie: Weryfikacja automatyczna Playwright E2E","created_at":"2026-10-05T00:00:01Z"}\n')

    # Tworzenie przykładowego artefaktu
    with open(sess_brain / "test-artifact.md", "w", encoding="utf-8") as f:
        f.write("# Test Artifact\nZawartość artefaktu testowego.")

    # Ustawienie zmiennej środowiskowej na izolowany katalog
    old_env = os.environ.get("ANTIGRAVITY_CLI_DIR")
    os.environ["ANTIGRAVITY_CLI_DIR"] = str(TEST_DIR)

    yield TEST_DIR

    # Przywrócenie i czyszczenie
    if old_env is not None:
        os.environ["ANTIGRAVITY_CLI_DIR"] = old_env
    else:
        os.environ.pop("ANTIGRAVITY_CLI_DIR", None)
    shutil.rmtree(TEST_DIR, ignore_errors=True)
