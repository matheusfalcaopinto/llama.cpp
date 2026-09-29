from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "studio.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results (job_id TEXT NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(job_id,seq));
        """)
        self.db.commit()

    def get(self, table: str, key: str | int) -> dict | None:
        assert table in {"settings", "media", "jobs"}
        with self.lock:
            row = self.db.execute(f"SELECT body FROM {table} WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, table: str, key: str | int, value: Any):
        assert table in {"settings", "media", "jobs"}
        with self.lock, self.db:
            self.db.execute(f"INSERT OR REPLACE INTO {table}(id,body) VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def all(self, table: str) -> list[dict]:
        assert table in {"media", "jobs"}
        with self.lock:
            rows = self.db.execute(f"SELECT body FROM {table} ORDER BY rowid DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    def add_result(self, job_id: str, seq: int, result: dict):
        with self.lock, self.db:
            self.db.execute("INSERT INTO results(job_id,seq,body) VALUES (?,?,?)", (job_id, seq, json.dumps(result, ensure_ascii=False, allow_nan=False)))

    def results(self, job_id: str, offset=0, limit=100) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT body FROM results WHERE job_id=? ORDER BY seq LIMIT ? OFFSET ?", (job_id, limit, offset)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self):
        with self.lock:
            self.db.close()
