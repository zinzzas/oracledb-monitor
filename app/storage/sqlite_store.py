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

CREATE TABLE IF NOT EXISTS alert_log (
    ts             INTEGER NOT NULL,
    instance_name  TEXT,
    name           TEXT NOT NULL,
    value          REAL,
    level          TEXT NOT NULL,   -- Critical | Warning | Info
    log_message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert_log(ts);

CREATE TABLE IF NOT EXISTS long_session_snapshot (
    ts        INTEGER NOT NULL,
    cnt_lt3   INTEGER,   -- elapsed < 3s
    cnt_lt10  INTEGER,   -- 3s <= elapsed < 10s
    cnt_lt15  INTEGER,   -- 10s <= elapsed < 15s
    cnt_ge15  INTEGER    -- elapsed >= 15s
);
CREATE INDEX IF NOT EXISTS idx_longsess_ts ON long_session_snapshot(ts);

CREATE TABLE IF NOT EXISTS long_query_log (
    ts           INTEGER NOT NULL,
    sql_id       TEXT,
    elapsed_sec  REAL,
    tier         TEXT,     -- lt10 | lt15 | ge15  (3초 미만은 저장하지 않음)
    username     TEXT,
    module       TEXT,
    sql_text     TEXT,     -- PL/SQL 패키지 호출은 SQL_ID가 NULL이라 이 텍스트로만 식별 가능
    is_plsql_call INTEGER  -- 0/1 - SQL_ID 없는 패키지.프로시저 호출인지 플래그
);
CREATE INDEX IF NOT EXISTS idx_longquery_ts ON long_query_log(ts);

CREATE TABLE IF NOT EXISTS plsql_call_snapshot (
    ts               INTEGER NOT NULL,
    proc_name        TEXT NOT NULL,   -- 파싱된 패키지.프로시저명 (또는 파싱 실패 시 sql_text 앞부분)
    calls            INTEGER,         -- 이 폴링 구간의 호출 횟수 델타 (V$SQL.EXECUTIONS 기반, 폴링 손실 없음)
    avg_elapsed_ms   REAL,
    total_elapsed_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_plsqlcall_ts ON plsql_call_snapshot(ts);
"""


def _ensure_dir():
    d = os.path.dirname(settings.sqlite_path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


@contextmanager
def get_conn():
    _ensure_dir()
    conn = sqlite3.connect(settings.sqlite_path)
    # synchronous는 커넥션당 설정(DB 파일에 영구 저장되지 않음)이라 매 connect마다 설정 필요.
    # WAL 모드에서는 NORMAL로 낮춰도 크래시만 안 나면 안전하며(SQLite 공식 권장),
    # 쓰기마다 fsync하던 기본값(FULL) 대비 쓰기 성능이 크게 좋아진다.
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # journal_mode는 DB 파일 헤더에 영구 저장되므로 한 번만 설정하면 된다.
        # WAL(Write-Ahead Log)로 바꾸면 읽기/쓰기가 서로 블록하지 않고, 커밋당 비용도 작아진다
        # (기본값 rollback journal은 쓰기마다 fsync해서 이 프로젝트처럼 고빈도 쓰기 워크로드에 치명적).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        # CREATE TABLE IF NOT EXISTS는 이미 있는 테이블에 새 컴럼을 추가해주지 않으므로,
        # 기존 배포본에 새로 생긴 컴럼을 안전하게 보강한다.
        _migrate_schema(conn)
        # 3일치 운영 중 발견된 문제: DELETE로 보존기간 지난 로우를 지우더라도 VACUUM 없이는
        # 파일 크기가 안 줄어든다 (빈 페이지만 재사용). 시작 시 한 번 안쓰는 공간을 회수해
        # DB 파일을 실제 데이터 크기만큼 압축한다 (수십 MB 수준이라 수초 내 완료됨).
        conn.execute("VACUUM")


def _migrate_schema(conn):
    """long_query_log에 sql_text/is_plsql_call 컴럼이 없는 기존 DB라면 ALTER로 보강한다
    (mybatis callable 패키지 호출을 Long Active Session Count 드릴다운에서도 식별하기 위해 추가)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(long_query_log)").fetchall()]
    if "sql_text" not in cols:
        conn.execute("ALTER TABLE long_query_log ADD COLUMN sql_text TEXT")
    if "is_plsql_call" not in cols:
        conn.execute("ALTER TABLE long_query_log ADD COLUMN is_plsql_call INTEGER")
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


def write_poll_batch(
    metric_snapshot: dict,
    slow_queries: list[dict],
    lock_events: list[dict],
    session_counts: dict,
    long_session_counts: dict,
    long_query_rows: list[dict],
    wait_class_rows: list[dict] | None = None,
    cpu_breakdown: dict | None = None,
    sysstat_rows: list[dict] | None = None,
    plsql_call_rows: list[dict] | None = None,
):
    """수집기 한 번의 폴링에서 나오는 모든 쓰기를 단일 커넥션/트랜잭션으로 묶는다.
    이전에는 폴링마다 7~9개의 개별 커넥션을 열고 닫았는데, 이를 하나로 합쳤다.
    커넥션 오프닝 오버헤드와 WAL 체크포인트 빈도를 줄여, 대시보드 로딩 중 읽기 요청과의
    경합 가능성도 줄인다."""
    ts = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO metric_snapshot (ts, cpu_pct, mem_used_mb, mem_total_mb, active_sessions) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                ts,
                metric_snapshot.get("cpu_pct"),
                metric_snapshot.get("mem_used_mb"),
                metric_snapshot.get("mem_total_mb"),
                metric_snapshot.get("active_sessions"),
            ),
        )

        if slow_queries:
            conn.executemany(
                "INSERT INTO slow_query_snapshot "
                "(ts, sql_id, avg_elapsed_sec, executions, parsing_schema, sql_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (ts, r.get("sql_id"), r.get("avg_elapsed_sec"), r.get("executions"),
                     r.get("parsing_schema_name"), (r.get("sql_text") or "")[:2000])
                    for r in slow_queries
                ],
            )

        if lock_events:
            conn.executemany(
                "INSERT INTO lock_event "
                "(ts, blocker_sid, blocker_username, waiter_sid, waiter_username, seconds_in_wait, event) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (ts, r.get("blocker_sid"), r.get("blocker_username"), r.get("waiter_sid"),
                     r.get("waiter_username"), r.get("seconds_in_wait"), r.get("event"))
                    for r in lock_events
                ],
            )

        conn.execute(
            "INSERT INTO session_count_snapshot (ts, total, active, inactive) VALUES (?, ?, ?, ?)",
            (ts, session_counts.get("total"), session_counts.get("active"), session_counts.get("inactive")),
        )

        conn.execute(
            "INSERT INTO long_session_snapshot (ts, cnt_lt3, cnt_lt10, cnt_lt15, cnt_ge15) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                ts, long_session_counts.get("cnt_lt3", 0), long_session_counts.get("cnt_lt10", 0),
                long_session_counts.get("cnt_lt15", 0), long_session_counts.get("cnt_ge15", 0),
            ),
        )

        if long_query_rows:
            conn.executemany(
                "INSERT INTO long_query_log (ts, sql_id, elapsed_sec, tier, username, module, sql_text, is_plsql_call) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (r["ts"], r.get("sql_id"), r.get("elapsed_sec"), r.get("tier"),
                     r.get("username"), r.get("module"), r.get("sql_text"),
                     1 if r.get("is_plsql_call") else 0)
                    for r in long_query_rows
                ],
            )

        if wait_class_rows:
            conn.executemany(
                "INSERT INTO wait_class_snapshot (ts, wait_class, wait_sec) VALUES (?, ?, ?)",
                [(ts, r["wait_class"], r["wait_sec"]) for r in wait_class_rows],
            )

        if cpu_breakdown:
            conn.execute(
                "INSERT INTO cpu_breakdown_snapshot (ts, user_pct, sys_pct, iowait_pct) VALUES (?, ?, ?, ?)",
                (ts, cpu_breakdown.get("user_pct"), cpu_breakdown.get("sys_pct"), cpu_breakdown.get("iowait_pct")),
            )

        if sysstat_rows:
            conn.executemany(
                "INSERT INTO sysstat_snapshot (ts, stat_name, rate_per_sec, delta_value) VALUES (?, ?, ?, ?)",
                [(ts, r["stat_name"], r["rate_per_sec"], r["delta_value"]) for r in sysstat_rows],
            )

        if plsql_call_rows:
            conn.executemany(
                "INSERT INTO plsql_call_snapshot (ts, proc_name, calls, avg_elapsed_ms, total_elapsed_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (ts, r["proc_name"], r["calls"], r["avg_elapsed_ms"], r["total_elapsed_ms"])
                    for r in plsql_call_rows
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


def get_recent_plsql_calls(minutes: int = 30, limit: int = 50) -> list[dict]:
    """대시보드 PL/SQL Package Calls 위젯 초기 로딩용 - 최근 N분간 패키지별 합계 호출횟수/수행시간."""
    since = int(time.time()) - minutes * 60
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT proc_name, SUM(calls) AS calls, SUM(total_elapsed_ms) AS total_elapsed_ms,
                   ROUND(SUM(total_elapsed_ms) / SUM(calls), 2) AS avg_elapsed_ms
            FROM plsql_call_snapshot
            WHERE ts >= ?
            GROUP BY proc_name
            ORDER BY total_elapsed_ms DESC
            LIMIT ?
            """,
            (since, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_plsql_call_log_range(start_ts: int, end_ts: int, limit: int = 2000) -> list[dict]:
    """PL/SQL Package Calls 상세페이지(날짜별 조회) + 엑셀 다운로드용 - 폴링 건단위
    원시 row 그대로(패키지명 집계 안 함) 시간순 정렬해 반환한다."""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT ts, proc_name, calls, avg_elapsed_ms, total_elapsed_ms
            FROM plsql_call_snapshot
            WHERE ts BETWEEN ? AND ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (start_ts, end_ts, limit),
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
        conn.execute("DELETE FROM long_session_snapshot WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM long_query_log WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM plsql_call_snapshot WHERE ts < ?", (cutoff,))
        # alert_log는 저빈도·고가치 데이터라 7배 더 오래 보관
        conn.execute("DELETE FROM alert_log WHERE ts < ?", (cutoff - retention_hours * 3600 * 6,))
        conn.commit()


def vacuum_db():
    """WAL 모드에서도 DELETE로 비운 공간은 자동 회수되지 않아 장기 운영 시 파일이 계속 커진다.
    purge_old 직후에 주기적으로 호출해 버려진 공간을 회수한다."""
    with get_conn() as conn:
        conn.execute("VACUUM")


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


def insert_alert(instance_name: str, name: str, value, level: str, log_message: str) -> dict:
    """임계치 전이 감지 시 호출 (collector). 삽입된 로우를 dict 로 돌려줘서
    바로 WebSocket broadcast 에 쓸 수 있게 한다."""
    ts = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alert_log (ts, instance_name, name, value, level, log_message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, instance_name, name, value, level, log_message),
        )
        conn.commit()
    return {
        "ts": ts, "instance_name": instance_name, "name": name,
        "value": value, "level": level, "log_message": log_message,
    }


def get_recent_alerts(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, instance_name, name, value, level, log_message "
            "FROM alert_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


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


# ---------------------------------------------------------------------------
# V2: Long Active Session Count (시간대별 장시간 실행 세션 구간 스택)
#     MaxGauge는 "인스턴스별" 스택인데 우리는 단일 인스턴스라 "시간대별"로 변형.
# ---------------------------------------------------------------------------

def insert_long_session_counts(data: dict):
    if not data:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO long_session_snapshot (ts, cnt_lt3, cnt_lt10, cnt_lt15, cnt_ge15) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                int(time.time()),
                data.get("cnt_lt3", 0), data.get("cnt_lt10", 0),
                data.get("cnt_lt15", 0), data.get("cnt_ge15", 0),
            ),
        )
        conn.commit()


def get_long_session_range(start_ts: int, end_ts: int, bucket_sec: int | None = None) -> dict:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT ts, cnt_lt3, cnt_lt10, cnt_lt15, cnt_ge15 FROM long_session_snapshot "
            "WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
            (start_ts, end_ts),
        )
        rows = [dict(r) for r in cur.fetchall()]
    bucket_sec = bucket_sec or _auto_bucket_sec(start_ts, end_ts, max_points=200)
    buckets = _bucketize(rows, ["cnt_lt3", "cnt_lt10", "cnt_lt15", "cnt_ge15"], bucket_sec)
    # bucket_sec을 함께 돌려줘야 프론트가 막대 클릭 시 [bucket.ts, bucket.ts+bucket_sec) 구간을
    # 정확히 계산해 /api/long-session/queries 로 드릴다운 조회할 수 있다.
    return {"bucket_sec": bucket_sec, "rows": buckets}


def insert_long_query_log(rows: list[dict]):
    """3초 이상 실행된 장시간 쿼리 개별 로그. Long Active Session Count
    막대를 클릭했을 때 해당 구간/티어의 SQL 목록을 드릴다운하기 위해 저장한다."""
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO long_query_log (ts, sql_id, elapsed_sec, tier, username, module) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r["ts"], r.get("sql_id"), r.get("elapsed_sec"), r.get("tier"),
                 r.get("username"), r.get("module"))
                for r in rows
            ],
        )
        conn.commit()


def get_long_query_log(start_ts: int, end_ts: int, tier: str | None = None, limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        if tier:
            cur = conn.execute(
                "SELECT ts, sql_id, elapsed_sec, tier, username, module, sql_text, is_plsql_call FROM long_query_log "
                "WHERE ts BETWEEN ? AND ? AND tier = ? ORDER BY elapsed_sec DESC LIMIT ?",
                (start_ts, end_ts, tier, limit),
            )
        else:
            cur = conn.execute(
                "SELECT ts, sql_id, elapsed_sec, tier, username, module, sql_text, is_plsql_call FROM long_query_log "
                "WHERE ts BETWEEN ? AND ? ORDER BY elapsed_sec DESC LIMIT ?",
                (start_ts, end_ts, limit),
            )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# V2: 24 Hours Trend Comparison (오늘 vs 어제/평일 겹쳐보기)
#     stat 은 metric_snapshot 컬럼(cpu_pct/active_sessions/mem_used_mb) 중 하나거나,
#     그 외에는 sysstat_snapshot.stat_name 으로 취급한다.
#     컬럼명은 고정 화이트리스트만 허용하므로 f-string 삽입이어도 SQL Injection 위험 없음.
# ---------------------------------------------------------------------------

_METRIC_COLUMNS = {"cpu_pct", "active_sessions", "mem_used_mb"}


def _get_raw_series_bucketed(stat: str, start_ts: int, end_ts: int, day_start: int, bucket_sec: int) -> list[tuple]:
    """SQL 레벨에서 day_start 기준 상대 버켓(tod_sec)으로 이미 AVG 집계해서 반환한다.
    이전에는 원시 row를 전부 Python으로 끌어와 루프로 버켓했었는데, 24시간 구간이면
    최대 수만 개 로우가 오가는 문제가 있어 SQL이 직접 GROUP BY 하도록 바꿔 전송량/CPU 부담을 크게 줄였다."""
    with get_conn() as conn:
        if stat in _METRIC_COLUMNS:
            cur = conn.execute(
                f"SELECT ((ts - ?) / ?) * ? AS rel, AVG({stat}) AS v FROM metric_snapshot "
                f"WHERE ts BETWEEN ? AND ? AND {stat} IS NOT NULL GROUP BY rel ORDER BY rel",
                (day_start, bucket_sec, bucket_sec, start_ts, end_ts),
            )
        else:
            cur = conn.execute(
                "SELECT ((ts - ?) / ?) * ? AS rel, AVG(rate_per_sec) AS v FROM sysstat_snapshot "
                "WHERE stat_name = ? AND ts BETWEEN ? AND ? AND rate_per_sec IS NOT NULL "
                "GROUP BY rel ORDER BY rel",
                (day_start, bucket_sec, bucket_sec, stat, start_ts, end_ts),
            )
        return [(int(rel), round(v, 3)) for rel, v in cur.fetchall() if v is not None]


def get_trend_comparison(
    stat: str, today_start: int, today_end: int, compare_start: int, compare_end: int,
    bucket_sec: int = 300,
) -> dict:
    """각 날짜의 자정(00:00) 기준 경과초(tod_sec)로 버켓해 두 시리즈를 같은 시간대축에
    올릴 수 있게 맞춰준다 (날짜는 다르지만 시각적으로 겹쳐보기 가능)."""
    today_rows = _get_raw_series_bucketed(stat, today_start, today_end, today_start, bucket_sec)
    compare_rows = _get_raw_series_bucketed(stat, compare_start, compare_end, compare_start, bucket_sec)
    return {
        "today": [{"tod_sec": rel, "value": v} for rel, v in today_rows],
        "compare": [{"tod_sec": rel, "value": v} for rel, v in compare_rows],
    }
