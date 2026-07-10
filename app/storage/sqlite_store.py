"""
X-log(시계열) 및 슬로우쿼리 히스토리를 저장하는 경량 SQLite 스토어.
동기 sqlite3 를 쓰되, 수집기(collector)에서만 쓰기 때문에 락 경합 걱정은 적다.
"""
from __future__ import annotations  # Python 3.9 호환 (X | None 문법을 지연 평가)
import sqlite3
import os
import time
from contextlib import contextmanager
from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_snapshot (
    ts              INTEGER NOT NULL,   -- epoch seconds
    cpu_pct         REAL,
    mem_used_mb     REAL,
    mem_total_mb    REAL,
    active_sessions INTEGER
);
CREATE INDEX IF NOT EXISTS idx_metric_ts ON metric_snapshot(ts);

CREATE TABLE IF NOT EXISTS slow_query_snapshot (
    ts               INTEGER NOT NULL,
    sql_id           TEXT,
    avg_elapsed_sec  REAL,
    executions       INTEGER,
    parsing_schema   TEXT,
    sql_text         TEXT
);
CREATE INDEX IF NOT EXISTS idx_slow_ts ON slow_query_snapshot(ts);

CREATE TABLE IF NOT EXISTS lock_event (
    ts               INTEGER NOT NULL,
    blocker_sid      INTEGER,
    blocker_username TEXT,
    waiter_sid       INTEGER,
    waiter_username  TEXT,
    seconds_in_wait  INTEGER,
    event            TEXT
);
CREATE INDEX IF NOT EXISTS idx_lock_ts ON lock_event(ts);
"""


def _ensure_dir():
    d = os.path.dirname(settings.sqlite_path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


@contextmanager
def get_conn():
    _ensure_dir()
    conn = sqlite3.connect(settings.sqlite_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def insert_metric_snapshot(snapshot: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO metric_snapshot (ts, cpu_pct, mem_used_mb, mem_total_mb, active_sessions) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                int(time.time()),
                snapshot.get("cpu_pct"),
                snapshot.get("mem_used_mb"),
                snapshot.get("mem_total_mb"),
                snapshot.get("active_sessions"),
            ),
        )
        conn.commit()


def insert_slow_queries(rows: list[dict]):
    if not rows:
        return
    ts = int(time.time())
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO slow_query_snapshot "
            "(ts, sql_id, avg_elapsed_sec, executions, parsing_schema, sql_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    ts,
                    r.get("sql_id"),
                    r.get("avg_elapsed_sec"),
                    r.get("executions"),
                    r.get("parsing_schema_name"),
                    (r.get("sql_text") or "")[:2000],
                )
                for r in rows
            ],
        )
        conn.commit()


def insert_lock_events(rows: list[dict]):
    if not rows:
        return
    ts = int(time.time())
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO lock_event "
            "(ts, blocker_sid, blocker_username, waiter_sid, waiter_username, seconds_in_wait, event) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    ts,
                    r.get("blocker_sid"),
                    r.get("blocker_username"),
                    r.get("waiter_sid"),
                    r.get("waiter_username"),
                    r.get("seconds_in_wait"),
                    r.get("event"),
                )
                for r in rows
            ],
        )
        conn.commit()


def get_xlog(minutes: int = 30) -> list[dict]:
    since = int(time.time()) - minutes * 60
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, cpu_pct, mem_used_mb, mem_total_mb, active_sessions "
            "FROM metric_snapshot WHERE ts >= ? ORDER BY ts ASC",
            (since,),
        )
        return [dict(r) for r in cur.fetchall()]


def purge_old(retention_hours: int | None = None):
    retention_hours = retention_hours or settings.retention_hours
    cutoff = int(time.time()) - retention_hours * 3600
    with get_conn() as conn:
        conn.execute("DELETE FROM metric_snapshot WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM slow_query_snapshot WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM lock_event WHERE ts < ?", (cutoff,))
        conn.commit()
