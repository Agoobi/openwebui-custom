"""SQLite storage for Săn lead. Times are integer UTC epoch seconds; lists are JSON text."""

import json
import sqlite3
import threading
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL,
    industry TEXT NOT NULL,
    kind TEXT NOT NULL,
    plant_status TEXT NOT NULL DEFAULT 'chua_ro',
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    province TEXT NOT NULL DEFAULT '',
    province_old TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    equipment TEXT NOT NULL DEFAULT '[]',
    equipment_inferred INTEGER NOT NULL DEFAULT 0,
    deadline TEXT,
    progress TEXT NOT NULL DEFAULT '',
    value_text TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '{}',
    sales_note TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    published_at INTEGER,
    score INTEGER NOT NULL DEFAULT 0,
    score_reasons TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL DEFAULT 'moi',
    state_by TEXT,
    state_at INTEGER,
    note TEXT NOT NULL DEFAULT '',
    run_id TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_opp_score ON opportunities (state, score DESC);
CREATE INDEX IF NOT EXISTS ix_opp_seen ON opportunities (first_seen DESC);

CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    plant_status TEXT NOT NULL DEFAULT 'chua_ro',
    role_group TEXT NOT NULL DEFAULT 'khac',
    province TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    linkedin_url TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    sales_note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    opportunity_id TEXT,
    state TEXT NOT NULL DEFAULT 'moi',
    state_by TEXT,
    state_at INTEGER,
    note TEXT NOT NULL DEFAULT '',
    run_id TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_people_opp ON people (opportunity_id);
CREATE INDEX IF NOT EXISTS ix_people_seen ON people (first_seen DESC);

CREATE TABLE IF NOT EXISTS seen (
    url_key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    verdict TEXT NOT NULL DEFAULT '',
    at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    trigger TEXT NOT NULL DEFAULT '',
    stats TEXT NOT NULL DEFAULT '{}',
    cost_usd REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_runs_time ON runs (started_at DESC);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        for suffix in ("", "-wal", "-shm"):
            path = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
            if path.exists():
                path.chmod(0o600)  # holds the encrypted Apify key and contact details
        _conn = conn
    return _conn


@contextmanager
def tx():
    with _lock:
        conn = connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, params).fetchall()


def one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except ValueError:
        return fallback


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def get_kv(key: str, fallback=None):
    row = one("SELECT value FROM kv WHERE key=?", (key,))
    return loads(row["value"], fallback) if row else fallback


def set_kv(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, dumps(value)))
