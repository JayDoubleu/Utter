"""Dictation history in SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    id: int
    created_at: float
    text: str
    raw_text: str
    model: str
    duration: float


class History:
    def __init__(self, path: Path | str) -> None:
        self._lock = threading.Lock()
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                text TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                model TEXT NOT NULL,
                duration REAL NOT NULL
            )
            """
        )
        self._db.commit()

    def add(
        self, text: str, raw_text: str, model: str, duration: float, *, limit: int = 0
    ) -> Entry:
        created_at = time.time()
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO entries (created_at, text, raw_text, model, duration) "
                "VALUES (?, ?, ?, ?, ?)",
                (created_at, text, raw_text, model, duration),
            )
            entry_id = int(cursor.lastrowid)
            if limit > 0:
                self._db.execute(
                    "DELETE FROM entries WHERE id NOT IN "
                    "(SELECT id FROM entries ORDER BY id DESC LIMIT ?)",
                    (limit,),
                )
            self._db.commit()
        return Entry(entry_id, created_at, text, raw_text, model, duration)

    def recent(self, limit: int = 50) -> list[Entry]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, created_at, text, raw_text, model, duration FROM entries "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Entry(*row) for row in rows]

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries")
            self._db.commit()

    def count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._db.close()
