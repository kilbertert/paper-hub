"""Tiny SQLite library for anonymous local favorites and download history."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .merge import MergedPaper


class Library:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = Lock()
        with self._db:
            self._db.executescript(
                """CREATE TABLE IF NOT EXISTS papers (
                    session_id TEXT NOT NULL, canonical_key TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY (session_id, canonical_key)
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    session_id TEXT NOT NULL, canonical_key TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY (session_id, canonical_key)
                );
                CREATE TABLE IF NOT EXISTS downloads (
                    session_id TEXT NOT NULL, canonical_key TEXT NOT NULL,
                    object_path TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, canonical_key)
                );
                CREATE TABLE IF NOT EXISTS search_cache (
                    cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL
                );"""
            )

    def save_papers(self, session_id: str, papers: Iterable[MergedPaper]) -> None:
        rows = [
            (session_id, paper.record.canonical_key, json.dumps(paper.to_dict()))
            for paper in papers
        ]
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO papers(session_id, canonical_key, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id, canonical_key) DO UPDATE SET payload=excluded.payload",
                rows,
            )

    def save_payloads(self, session_id: str, payloads: Iterable[dict]) -> None:
        rows = [(session_id, payload["canonical_key"], json.dumps(payload)) for payload in payloads]
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO papers(session_id, canonical_key, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id, canonical_key) DO UPDATE SET payload=excluded.payload",
                rows,
            )

    def get_paper(self, session_id: str, canonical_key: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM papers WHERE session_id=? AND canonical_key=?",
                (session_id, canonical_key),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_papers(self, session_id: str, table: str) -> list[dict]:
        return [
            paper
            for key in self.list_keys(session_id, table)
            if (paper := self.get_paper(session_id, key))
        ]

    def set_favorite(self, session_id: str, canonical_key: str, enabled: bool) -> None:
        with self._lock, self._db:
            if enabled:
                self._db.execute(
                    "INSERT OR IGNORE INTO favorites VALUES (?, ?, ?)",
                    (session_id, canonical_key, datetime.now(UTC).isoformat()),
                )
            else:
                self._db.execute(
                    "DELETE FROM favorites WHERE session_id=? AND canonical_key=?",
                    (session_id, canonical_key),
                )

    def list_keys(self, session_id: str, table: str) -> list[str]:
        if table not in {"favorites", "downloads"}:
            raise ValueError("unsupported library table")
        with self._lock:
            rows = self._db.execute(
                f"SELECT canonical_key FROM {table} WHERE session_id=? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [row["canonical_key"] for row in rows]

    def record_download(self, session_id: str, canonical_key: str, object_path: Path) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO downloads VALUES (?, ?, ?, ?) ON CONFLICT(session_id, canonical_key) "
                "DO UPDATE SET object_path=excluded.object_path, created_at=excluded.created_at",
                (session_id, canonical_key, str(object_path), datetime.now(UTC).isoformat()),
            )

    def get_cached_search(self, cache_key: str, *, ttl: float = 7 * 86400) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload, created_at FROM search_cache WHERE cache_key=?", (cache_key,)
            ).fetchone()
        if not row or time.time() - row["created_at"] >= ttl:
            return None
        return json.loads(row["payload"])

    def put_cached_search(self, cache_key: str, payload: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO search_cache(cache_key, payload, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at",
                (cache_key, json.dumps(payload), time.time()),
            )
