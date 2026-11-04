"""SQLite storage. Every time is an integer UTC epoch in seconds; local time only exists in the page."""

import json
import sqlite3
import threading
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    username TEXT NOT NULL,
    secret TEXT NOT NULL,
    site_timezone TEXT,
    can_unfiltered_html INTEGER,
    checked_at INTEGER,
    check_ok INTEGER,
    check_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sites_user ON sites (user_id);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    site_id TEXT,
    title TEXT NOT NULL,
    html TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    slug TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    cover_file TEXT,
    cover_alt TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    mode TEXT NOT NULL,
    publish_at INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try_at INTEGER,
    wp_post_id INTEGER,
    wp_media_id INTEGER,
    wp_status TEXT,
    wp_url TEXT,
    wp_edit_url TEXT,
    sent_at INTEGER,
    error TEXT,
    source TEXT NOT NULL,
    owui_event_id TEXT,
    owui_start INTEGER,
    owui_sig TEXT,
    media_map TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    archived_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_posts_user_time ON posts (user_id, publish_at);
CREATE INDEX IF NOT EXISTS ix_posts_state ON posts (state, publish_at);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    at INTEGER NOT NULL,
    actor TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_history_post ON history (post_id, at);

CREATE TABLE IF NOT EXISTS settings (
    user_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendars (
    user_id TEXT PRIMARY KEY,
    owui_calendar_id TEXT NOT NULL,
    slots_calendar_id TEXT,
    slots_sig TEXT
);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.COVER_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        _migrate(conn)
        for suffix in ("", "-wal", "-shm"):
            path = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
            if path.exists():
                path.chmod(0o600)  # holds encrypted application passwords and drafts
        _conn = conn
    return _conn


@contextmanager
def tx():
    """One write transaction at a time; the API and the worker share the connection."""
    with _lock:
        conn = connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def _migrate(conn: sqlite3.Connection) -> None:
    """Columns added after the first release."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
    if "media_map" not in have:
        conn.execute("ALTER TABLE posts ADD COLUMN media_map TEXT")


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
