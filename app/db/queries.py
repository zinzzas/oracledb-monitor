"""
V$ 동적 성능 뷰 조회 모음.

전제: 접속 계정에 아래 권한이 필요하다 (서버 접속 없이 DBA가 원격으로 GRANT 가능).

    GRANT SELECT_CATALOG_ROLE TO monitor_user;
    -- 또는 최소권한으로:
    GRANT SELECT ON V_$SESSION       TO monitor_user;
    GRANT SELECT ON V_$SQL           TO monitor_user;
    GRANT SELECT ON V_$SQL_PLAN      TO monitor_user;
    GRANT SELECT ON V_$LOCK          TO monitor_user;
    GRANT SELECT ON V_$OSSTAT        TO monitor_user;
    GRANT SELECT ON V_$SYSMETRIC     TO monitor_user;
    GRANT SELECT ON V_$SGAINFO       TO monitor_user;
    GRANT SELECT ON V_$PGASTAT       TO monitor_user;

주의: V$ACTIVE_SESSION_HISTORY / DBA_HIST_* / AWR 관련 뷰는 여기서 의도적으로
사용하지 않는다 (Diagnostics Pack 라이선스 대상이라 조회만 해도 라이선스 이슈 발생).
"""
from __future__ import annotations
import oracledb


def _clob_to_str(v):
    """python-oracledb 는 CLOB 컬럼을 LOB 객체로 반환하므로 문자열로 변환."""
    if isinstance(v, oracledb.LOB):
        return v.read()
    return v


def _rows_as_dicts(cursor) -> list[dict]:
    cols = [c[0].lower() for c in cursor.description]
    return [
        {col: _clob_to_str(val) for col, val in zip(cols, row)}
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# 1) 호스트 / 인스턴스 CPU, 메모리
# ---------------------------------------------------------------------------

def get_host_cpu_mem(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT stat_name, value FROM v$osstat
            WHERE stat_name IN (
                'NUM_CPUS', 'PHYSICAL_MEMORY_BYTES', 'FREE_MEMORY_BYTES',
                'BUSY_TIME', 'IDLE_TIME'
            )
            """
        )
        osstat = {name.lower(): val for name, val in cur.fetchall()}

        cur.execute(
            """
            SELECT value FROM v$sysmetric
            WHERE metric_name = 'Host CPU Utilization (%)'
            AND group_id = 2
            ORDER BY end_time DESC FETCH FIRST 1 ROW ONLY
            """
        )
        row = cur.fetchone()
        cpu_pct = round(row[0], 1) if row else None

    total_mem = osstat.get("physical_memory_bytes") or 0
    free_mem = osstat.get("free_memory_bytes") or 0
    used_mem = max(total_mem - free_mem, 0)

    return {
        "num_cpus": osstat.get("num_cpus"),
        "cpu_pct": cpu_pct,
        "mem_total_mb": round(total_mem / 1024 / 1024, 1),
        "mem_used_mb": round(used_mem / 1024 / 1024, 1),
        "mem_free_mb": round(free_mem / 1024 / 1024, 1),
    }


def get_sga_pga(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT name, bytes FROM v$sgainfo")
        sga = {name.strip().lower(): b for name, b in cur.fetchall()}

        cur.execute(
            "SELECT name, value FROM v$pgastat WHERE name IN "
            "('total PGA allocated', 'total PGA inuse', 'maximum PGA allocated')"
        )
        pga = {name.lower(): val for name, val in cur.fetchall()}

    return {
        "sga_total_mb": round(sga.get("total sga size", 0) / 1024 / 1024, 1),
        "pga_allocated_mb": round(pga.get("total pga allocated", 0) / 1024 / 1024, 1),
        "pga_inuse_mb": round(pga.get("total pga inuse", 0) / 1024 / 1024, 1),
    }


# ---------------------------------------------------------------------------
# 2) 실행 중인 세션 / 쿼리
# ---------------------------------------------------------------------------

def get_active_sessions(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                s.sid,
                s.serial#            AS serial_num,
                s.username,
                s.status,
                s.event,
                s.wait_class,
                s.seconds_in_wait,
                s.last_call_et       AS elapsed_sec,
                s.blocking_session,
                s.sql_id,
                sq.sql_text
            FROM v$session s
            LEFT JOIN v$sql sq ON s.sql_id = sq.sql_id AND sq.child_number = 0
            WHERE s.username IS NOT NULL
              AND s.status = 'ACTIVE'
              AND s.type = 'USER'
            ORDER BY s.last_call_et DESC
            """
        )
        return _rows_as_dicts(cur)


# ---------------------------------------------------------------------------
# 3) Lock / Blocking 체인
#    12c+ 는 v$session.blocking_session 이 이미 계산되어 있어 별도 조인이 필요 없다.
# ---------------------------------------------------------------------------

def get_blocking_chains(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                blocker.sid           AS blocker_sid,
                blocker.username      AS blocker_username,
                blocker.sql_id        AS blocker_sql_id,
                waiter.sid            AS waiter_sid,
                waiter.username       AS waiter_username,
                waiter.sql_id         AS waiter_sql_id,
                waiter.seconds_in_wait,
                waiter.event
            FROM v$session waiter
            JOIN v$session blocker ON waiter.blocking_session = blocker.sid
            WHERE waiter.blocking_session IS NOT NULL
            ORDER BY waiter.seconds_in_wait DESC
            """
        )
        return _rows_as_dicts(cur)


# ---------------------------------------------------------------------------
# 4) 슬로우 쿼리 (V$SQL 누적 통계 기반 - 평균 elapsed/execution 기준 정렬)
# ---------------------------------------------------------------------------

def get_slow_queries(conn, min_avg_elapsed_sec: float = 5.0, limit: int = 30) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM (
                SELECT
                    sql_id,
                    executions,
                    ROUND(elapsed_time / 1e6, 2)                          AS total_elapsed_sec,
                    ROUND(elapsed_time / GREATEST(executions, 1) / 1e6, 3) AS avg_elapsed_sec,
                    ROUND(buffer_gets / GREATEST(executions, 1), 0)       AS avg_buffer_gets,
                    ROUND(disk_reads / GREATEST(executions, 1), 0)        AS avg_disk_reads,
                    parsing_schema_name,
                    sql_text
                FROM v$sql
                WHERE executions > 0
                  AND parsing_schema_name NOT IN ('SYS', 'SYSTEM')
                ORDER BY avg_elapsed_sec DESC
            )
            WHERE avg_elapsed_sec >= :min_sec
            FETCH FIRST :lim ROWS ONLY
            """,
            min_sec=min_avg_elapsed_sec,
            lim=limit,
        )
        return _rows_as_dicts(cur)


# ---------------------------------------------------------------------------
# 5) SQL 상세 (실행계획 포함)
# ---------------------------------------------------------------------------

def get_sql_detail(conn, sql_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sql_id, executions, elapsed_time, cpu_time, buffer_gets,
                   disk_reads, rows_processed, parsing_schema_name, sql_fulltext
            FROM v$sql
            WHERE sql_id = :sql_id AND child_number = 0
            """,
            sql_id=sql_id,
        )
        row = cur.fetchone()
        if not row:
            return {}
        cols = [c[0].lower() for c in cur.description]
        detail = {col: _clob_to_str(val) for col, val in zip(cols, row)}

        cur.execute(
            """
            SELECT id, parent_id, operation, options, object_name,
                   cost, cardinality, LPAD(' ', depth*2) || operation AS indented_op
            FROM v$sql_plan
            WHERE sql_id = :sql_id AND child_number = 0
            ORDER BY id
            """,
            sql_id=sql_id,
        )
        detail["plan"] = _rows_as_dicts(cur)

    return detail


# ---------------------------------------------------------------------------
# 6) X-log 용 실시간 지표 스냅샷 (수집기가 주기적으로 호출)
# ---------------------------------------------------------------------------

def get_snapshot(conn) -> dict:
    cpu_mem = get_host_cpu_mem(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM v$session WHERE status = 'ACTIVE' AND type = 'USER'"
        )
        active_sessions = cur.fetchone()[0]

    return {
        "cpu_pct": cpu_mem["cpu_pct"],
        "mem_used_mb": cpu_mem["mem_used_mb"],
        "mem_total_mb": cpu_mem["mem_total_mb"],
        "active_sessions": active_sessions,
    }
