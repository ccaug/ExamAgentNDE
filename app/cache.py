"""Caché persistente de decisiones del LLM (SQLite). Memoiza juicios, no sustituye al modelo."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, hits INTEGER DEFAULT 0, created REAL)')
        self.db.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()
            if not row:
                return None
            self.db.execute('UPDATE kv SET hits=hits+1 WHERE k=?', (key,))
            self.db.commit()
        return json.loads(row[0])

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO kv (k, v, hits, created) VALUES (?,?,COALESCE((SELECT hits FROM kv WHERE k=?),0),?)',
                            (key, json.dumps(value, ensure_ascii=False), key, time.time()))
            self.db.commit()

    def count(self) -> int:
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM kv').fetchone()[0]

    def clear(self) -> None:
        with self.lock:
            self.db.execute('DELETE FROM kv')
            self.db.commit()
