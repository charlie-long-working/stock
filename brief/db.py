"""SQLite (var/brief.db). Không commit. Một kết nối mỗi lời gọi để an toàn đa luồng."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from brief.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  url TEXT, title TEXT, summary TEXT,
  published_at TEXT, fetched_at TEXT NOT NULL,
  UNIQUE(source_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS ix_items_pub ON items(published_at);
CREATE TABLE IF NOT EXISTS fetch_log(
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL, started_at TEXT NOT NULL,
  status TEXT NOT NULL, http INTEGER, n_items INTEGER, n_new INTEGER,
  elapsed_s REAL, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_fetch_src ON fetch_log(source_id, started_at);
CREATE TABLE IF NOT EXISTS briefs(
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL, kind TEXT NOT NULL, mode TEXT NOT NULL,
  window_start TEXT, window_end TEXT, n_items INTEGER,
  text_html TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'built', meta TEXT
);
CREATE TABLE IF NOT EXISTS brief_refs(
  brief_id INTEGER NOT NULL, canonical_url TEXT NOT NULL,
  PRIMARY KEY(brief_id, canonical_url)
);
CREATE TABLE IF NOT EXISTS deliveries(
  id INTEGER PRIMARY KEY,
  brief_id INTEGER, chunk_idx INTEGER NOT NULL, text_sha256 TEXT NOT NULL,
  status TEXT NOT NULL, tg_message_id INTEGER, sent_at TEXT, error TEXT,
  UNIQUE(brief_id, chunk_idx)
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, level TEXT NOT NULL,
  component TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv(
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


@contextmanager
def connect(path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def log_event(level: str, component: str, message: str, path: Path = DB_PATH) -> None:
    with connect(path) as con:
        con.execute(
            "INSERT INTO events(at, level, component, message) VALUES(?,?,?,?)",
            (iso(now_utc()), level, component, message[:500]),
        )


def kv_get(key: str, path: Path = DB_PATH) -> Optional[Any]:
    with connect(path) as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def kv_set(key: str, value: Any, path: Path = DB_PATH) -> None:
    with connect(path) as con:
        con.execute(
            "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False, default=str), iso(now_utc())),
        )


def prune(path: Path = DB_PATH, item_days: int = 30, log_days: int = 30) -> None:
    cut_items = iso(now_utc() - timedelta(days=item_days))
    cut_log = iso(now_utc() - timedelta(days=log_days))
    with connect(path) as con:
        con.execute("DELETE FROM items WHERE fetched_at < ?", (cut_items,))
        con.execute("DELETE FROM fetch_log WHERE started_at < ?", (cut_log,))
        con.execute("DELETE FROM events WHERE at < ?", (cut_log,))
