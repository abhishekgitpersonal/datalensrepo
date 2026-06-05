"""SQLite helpers for sessions, files, chat messages."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from .config import settings

_lock = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    col_count INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, table_name)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    question TEXT,            -- for user role
    sql TEXT,                 -- generated SQL (assistant)
    text TEXT,                -- narration (assistant)
    chart_spec TEXT,          -- JSON Plotly spec
    result_preview TEXT,      -- JSON {columns, rows[:50]}
    row_count INTEGER,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    column_name TEXT,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('ERROR','WARN','INFO')),
    count INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL,
    sample TEXT,                       -- JSON array of sample values
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dq_session ON data_quality_issues(session_id);
CREATE INDEX IF NOT EXISTS idx_dq_session_table ON data_quality_issues(session_id, table_name);

CREATE TABLE IF NOT EXISTS semantic_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    column_name TEXT,
    data_type TEXT,
    role TEXT NOT NULL,                 -- dimension | metric | date | identifier
    tags TEXT,                          -- JSON array of planner/search tags
    dq_severity TEXT,                   -- max severity seen for this table/column
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_semantic_session ON semantic_index(session_id);
CREATE INDEX IF NOT EXISTS idx_semantic_session_table ON semantic_index(session_id, table_name);

CREATE TABLE IF NOT EXISTS nl_sql_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_signature TEXT NOT NULL,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    tables_json TEXT,                   -- JSON array of referenced table names
    success_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(dataset_signature, question, sql)
);

CREATE INDEX IF NOT EXISTS idx_nl_sql_signature ON nl_sql_memory(dataset_signature);
CREATE INDEX IF NOT EXISTS idx_nl_sql_last_used ON nl_sql_memory(last_used_at DESC);
"""


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = sqlite3.connect(settings.sqlite_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()


def get_conn() -> sqlite3.Connection:
    """Caller is responsible for closing. Use only in dependency-injection contexts."""
    conn = sqlite3.connect(settings.sqlite_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    with _conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid or 0
