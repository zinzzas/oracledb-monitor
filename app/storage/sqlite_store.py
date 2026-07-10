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

CREATE TABLE IF NOT EXISTS wait_class_snapshot (
    ts          INTEGER NOT NULL,
    wait_class  TEXT NOT NULL,
    wait_sec    REAL
);
CREATE INDEX IF NOT EXISTS idx_waitclass_ts ON wait_class_snapshot(ts);

CREATE TABLE IF NOT EXISTS cpu_breakdown_snapshot (
    ts          INTEGER NOT NULL,
    user_pct    REAL,
    sys_pct     REAL,
    iowait_pct  REAL
);
CREATE INDEX IF NOT EXISTS idx_cpubd_ts ON cpu_breakdown_snapshot(ts);

CREATE TABLE IF NOT EXISTS sysstat_snapshot (
    ts             INTEGER NOT NULL,
    stat_name      TEXT NOT NULL,
    rate_per_sec   REAL,
    delta_value    REAL
);
CREATE INDEX IF NOT EXISTS idx_sysstat_ts ON sysstat_snapshot(ts, stat_name);

CREATE TABLE IF NOT EXISTS session_count_snapshot (
    ts        INTEGER NOT NULL,
    total     INTEGER,
    active    INTEGER,
    inactive  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sesscount_ts ON session_count_snapshot(ts);
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
        conn.execute("DELETE FROM wait_class_snapshot WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM cpu_breakdown_snapshot WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM sysstat_snapshot WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM session_count_snapshot WHERE ts < ?", (cutoff,))
        conn.commit()


# ---------------------------------------------------------------------------
# 상세화면(맥스게이지 스타일) 용 신규 저장/조회
# ---------------------------------------------------------------------------

def insert_wait_class(rows: list[dict]):
    if not rows:
        return
    ts = int(time.time())
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO wait_class_snapshot (ts, wait_class, wait_sec) VALUES (?, ?, ?)",
            [(ts, r["wait_class"], r["wait_sec"]) for r in rows],
        )
        conn.commit()


def insert_cpu_breakdown(data: dict):
    if not data:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cpu_breakdown_snapshot (ts, user_pct, sys_pct, iowait_pct) VALUES (?, ?, ?, ?)",
            (int(time.time()), data.get("user_pct"), data.get("sys_pct"), data.get("iowait_pct")),
        )
        conn.commit()


def insert_sysstat(rows: list[dict]):
    if not rows:
        return
    ts = int(time.time())
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO sysstat_snapshot (ts, stat_name, rate_per_sec, delta_value) VALUES (?, ?, ?, ?)",
            [(ts, r["stat_name"], r["rate_per_sec"], r["delta_value"]) for r in rows],
        )
        conn.commit()


def insert_session_counts(data: dict):
    if not data:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO session_count_snapshot (ts, total, active, inactive) VALUES (?, ?, ?, ?)",
            (int(time.time()), data.get("total"), data.get("active"), data.get("inactive")),
        )
        conn.commit()


def _auto_bucket_sec(start_ts: int, end_ts: int, max_points: int = 800) -> int:
    """범위가 넓으면 버킷을 키워 포인트 수를 제한 (브라우저 차트 성능 보호).
    버킷은 최소 poll_interval_sec 보다 작지 않게."""
    span = max(end_ts - start_ts, 1)
    return max(int(span / max_points) or 1, settings.poll_interval_sec)


def _bucketize(rows: list[dict], value_keys: list[str], bucket_sec: int) -> list[dict]:
    """raw 로우들을 bucket_sec 단위로 묶어 각 키별 avg/max 계산.
    ECharts markPoint(type:'max')가 현재 줌인된(zoom) 구간의 최대값을 프론트에서
    알아서 계산해 보여주므로, 서버는 단순히 충분히 촘촘한 데이터만 내려보내면 된다."""
    buckets: dict[int, dict] = {}
    for r in rows:
        b = (r["ts"] // bucket_sec) * bucket_sec
        agg = buckets.setdefault(b, {k: [] for k in value_keys})
        for k in value_keys:
            v = r.get(k)
            if v is not None:
                agg[k].append(v)
    out = []
    for b in sorted(buckets):
        agg = buckets[b]
        row = {"ts": b}
        for k in value_keys:
            vals = agg[k]
            row[f"{k}_avg"] = round(sum(vals) / len(vals), 3) if vals else None
            row[f"{k}_max"] = round(max(vals), 3) if vals else None
        out.append(row)
    return out


def get_metric_range(start_ts: int, end_ts: int, bucket_sec: int | None = None) -> list[dict]:
    """CPU%/Mem/Active Sessions - cpu-mem, active-sessions 상세화면용."""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, cpu_pct, mem_used_mb, mem_total_mb, active_sessions "
            "FROM metric_snapshot WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
            (start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts)
    return _bucketize(rows, ["cpu_pct", "mem_used_mb", "active_sessions"], bucket_sec)


def get_wait_class_range(start_ts: int, end_ts: int, bucket_sec: int | None = None) -> dict:
    """wait_class -> [{ts, wait_sec}, ...] (버켓 합계 - 스택 영역차트용)."""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, wait_class, wait_sec FROM wait_class_snapshot "
            "WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
            (start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts)
    by_class: dict[str, dict[int, float]] = {}
    for r in rows:
        b = (r["ts"] // bucket_sec) * bucket_sec
        cls = by_class.setdefault(r["wait_class"], {})
        cls[b] = cls.get(b, 0.0) + (r["wait_sec"] or 0.0)
    return {
        wc: [{"ts": b, "wait_sec": round(v, 3)} for b, v in sorted(buckets.items())]
        for wc, buckets in by_class.items()
    }


def get_cpu_breakdown_range(start_ts: int, end_ts: int, bucket_sec: int | None = None) -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, user_pct, sys_pct, iowait_pct FROM cpu_breakdown_snapshot "
            "WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
            (start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts)
    return _bucketize(rows, ["user_pct", "sys_pct", "iowait_pct"], bucket_sec)


def get_sysstat_range(stat_name: str, start_ts: int, end_ts: int, bucket_sec: int | None = None) -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, rate_per_sec FROM sysstat_snapshot "
            "WHERE stat_name = ? AND ts BETWEEN ? AND ? ORDER BY ts ASC",
            (stat_name, start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts)
    return _bucketize(rows, ["rate_per_sec"], bucket_sec)


def get_session_count_range(start_ts: int, end_ts: int, bucket_sec: int | None = None) -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, total, active, inactive FROM session_count_snapshot "
            "WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
            (start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts)
    return _bucketize(rows, ["total", "active", "inactive"], bucket_sec)


def get_lock_count_range(start_ts: int, end_ts: int, bucket_sec: int | None = None) -> list[dict]:
    """폴링 시점별 블로킹 건수 -> 버켓 max/avg (Lock Waiting Sessions 패널용)."""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, COUNT(*) as cnt FROM lock_event "
            "WHERE ts BETWEEN ? AND ? GROUP BY ts ORDER BY ts ASC",
            (start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts)
    return _bucketize(rows, ["cnt"], bucket_sec)
