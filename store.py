"""Tiny SQLite-backed room store so several browsers share one game state."""

from __future__ import annotations

import json
import os
import random
import sqlite3
import string
import time
from typing import Any, Dict, Optional

def _default_db() -> str:
    """Next to the app normally; fall back to temp if the dir is read-only
    (some hosted platforms mount the repo read-only)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if os.access(here, os.W_OK):
        return os.path.join(here, "uno_rooms.db")
    import tempfile
    return os.path.join(tempfile.gettempdir(), "uno_rooms.db")


DB_PATH = os.environ.get("UNO_DB") or _default_db()
ROOM_TTL_SECONDS = 12 * 3600          # rooms older than this are pruned


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL;")
    return c


def init() -> None:
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            updated REAL NOT NULL
        )""")


def new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I/O/0/1 confusion
    with _conn() as c:
        for _ in range(50):
            code = "".join(random.choice(alphabet) for _ in range(4))
            row = c.execute("SELECT 1 FROM rooms WHERE code=?", (code,)).fetchone()
            if not row:
                return code
    return "".join(random.choice(string.ascii_uppercase) for _ in range(6))


def save(state: Dict[str, Any]) -> None:
    state["version"] = int(state.get("version", 0)) + 1
    with _conn() as c:
        c.execute("INSERT INTO rooms(code, state, updated) VALUES(?,?,?) "
                  "ON CONFLICT(code) DO UPDATE SET state=excluded.state, updated=excluded.updated",
                  (state["room"], json.dumps(state), time.time()))


def load(code: str) -> Optional[Dict[str, Any]]:
    if not code:
        return None
    with _conn() as c:
        row = c.execute("SELECT state FROM rooms WHERE code=?", (code.upper(),)).fetchone()
    return json.loads(row[0]) if row else None


def delete(code: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM rooms WHERE code=?", (code.upper(),))


def prune() -> None:
    with _conn() as c:
        c.execute("DELETE FROM rooms WHERE updated < ?", (time.time() - ROOM_TTL_SECONDS,))
