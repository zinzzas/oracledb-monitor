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
    GRANT SELECT ON V_$SYSTEM_EVENT  TO monitor_user;
    GRANT SELECT ON V_$SYSSTAT       TO monitor_user;
    GRANT SELECT ON V_$PROCESS       TO monitor_user;
    GRANT SELECT ON V_$SQLCOMMAND    TO monitor_user;
    -- ALL_OBJECTS / ALL_PROCEDURES는 보통 PUBLIC에 기본 GRANT되어 있어 별도 조치 불필요하지만,
    -- 보안 강화된 인스턴스라면 PUBLIC 권한이 회수되어 있을 수 있으니 get_active_sessions()의
    -- PL/SQL 패키지 호출 식별(fallback 라벨링)이 안 되면 이 둘 권한부터 확인할 것.

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
    """
    호스트의 CPU 코어 수, CPU 사용율 및 물리/가용 메모리 통계를 조회합니다.
    오류 처리를 위해 try-except 블록을 사용하고, 리눅스 환경의 캐시/버퍼 특성을 고려하여
    완전 유휴 메모리(FREE_MEMORY_BYTES)와 필요시 즉각 회수 가능한 비활성 메모리(INACTIVE_MEMORY_BYTES)를
    모두 가용 메모리(Available Memory)로 판단하여 정확한 메모리 사용율을 산출합니다.
    """
    try:
        # 1) v$osstat 에서 CPU 코어 및 메모리 메트릭 조회
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT stat_name, value FROM v$osstat
                WHERE stat_name IN (
                    'NUM_CPUS', 'PHYSICAL_MEMORY_BYTES', 'FREE_MEMORY_BYTES',
                    'INACTIVE_MEMORY_BYTES', 'BUSY_TIME', 'IDLE_TIME'
                )
                """
            )
            osstat = {name.lower(): val for name, val in cur.fetchall()}

            # 2) v$sysmetric 에서 15초/60초 주기 호스트 CPU 사용율 조회
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

        # 3) 메모리 사용량 계산
        # - total_mem: 전체 물리 메모리 크기 (Bytes)
        # - inactive_mem: 비활성 메모리 (필요시 버퍼/캐시 해제를 통해 즉각 사용 가능한 공간)
        # - real_free_mem: 단순 free 메모리 + 비활성 가용 메모리 합산
        total_mem = osstat.get("physical_memory_bytes") or 0
        free_mem_raw = osstat.get("free_memory_bytes") or 0
        inactive_mem = osstat.get("inactive_memory_bytes") or 0
        
        # 실제 운영체제 수준에서 즉시 가용한 가용 메모리를 정의
        real_free_mem = free_mem_raw + inactive_mem
        used_mem = max(total_mem - real_free_mem, 0)

        return {
            "num_cpus": osstat.get("num_cpus"),
            "cpu_pct": cpu_pct,
            "mem_total_mb": round(total_mem / 1024 / 1024, 1),
            "mem_used_mb": round(used_mem / 1024 / 1024, 1),
            "mem_free_mb": round(real_free_mem / 1024 / 1024, 1),
        }
    except Exception as e:
        # 에러 발생 시 로그를 남기고 빈 데이터 반환 (시스템 중단 방지)
        import logging
        logging.getLogger("queries").error(f"get_host_cpu_mem 조회 오류: {str(e)}")
        return {
            "num_cpus": None,
            "cpu_pct": None,
            "mem_total_mb": 0.0,
            "mem_used_mb": 0.0,
            "mem_free_mb": 0.0,
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
                s.module,
                s.program,
                s.p1,
                s.p2,
                s.p3,
                ROUND(p.pga_alloc_mem / 1024 / 1024, 1) AS pga_mb,
                sc.command_name      AS command_text,
                sq.sql_text,
                peo.owner            AS plsql_owner,
                peo.object_name      AS plsql_package_name,
                pep.procedure_name   AS plsql_procedure_name
            FROM v$session s
            LEFT JOIN v$sql sq ON s.sql_id = sq.sql_id AND sq.child_number = 0
            LEFT JOIN v$process p ON s.paddr = p.addr
            LEFT JOIN v$sqlcommand sc ON s.command = sc.command_type
            LEFT JOIN all_objects peo ON peo.object_id = s.plsql_entry_object_id
            LEFT JOIN all_procedures pep
                   ON pep.object_id = s.plsql_entry_object_id
                  AND pep.subprogram_id = s.plsql_entry_subprogram_id
            WHERE s.username IS NOT NULL
              AND s.status = 'ACTIVE'
              AND s.type = 'USER'
            ORDER BY s.last_call_et DESC
            """
        )
        return _apply_plsql_fallback_label(_rows_as_dicts(cur))


def _apply_plsql_fallback_label(rows: list[dict]) -> list[dict]:
    """MyBatis의 CallableStatement로 패키지 프로시저를 호출하는 경우(RPC성 PL/SQL 호출)
    Oracle 10.2+ 부터 V$SESSION.SQL_ID 가 NULL로 나온다 (top-level SQL이 없는 구조적 특성).
    이 경우 SQL_ID/SQL_TEXT 대신 PLSQL_ENTRY_OBJECT_ID/SUBPROGRAM_ID로 실행 중인
    패키지.프로시저를 식별해 sql_text 자리에 대체 표시한다."""
    for r in rows:
        is_plsql = False
        if not r.get("sql_text") and r.get("plsql_package_name"):
            owner = r.get("plsql_owner")
            pkg = r["plsql_package_name"]
            proc = r.get("plsql_procedure_name")
            label = f"{owner}.{pkg}" if owner else pkg
            if proc:
                label += f".{proc}"
            r["sql_text"] = f"[PL/SQL] {label}"
            is_plsql = True
        # 원시 컴럼은 페이로드에서 제거 (WebSocket으로 5초마다 나가는 데이터라 가벼게 유지)
        r.pop("plsql_owner", None)
        r.pop("plsql_package_name", None)
        r.pop("plsql_procedure_name", None)
        r["is_plsql_call"] = is_plsql
    return rows


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
        # child_number=0으로 고정하면 패키지 호출처럼 바인드 타입이 매번 달라지는 케이스에서
        # 자식 커서 0이 이미 사라지고(aged out) 다른 번호만 남아 있을 수 있어,
        # 실제로 존재하는 가장 작은 child_number를 대신 사용한다.
        cur.execute(
            """
            SELECT * FROM (
                SELECT sql_id, child_number, executions, elapsed_time, cpu_time, buffer_gets,
                       disk_reads, rows_processed, parsing_schema_name, sql_fulltext
                FROM v$sql
                WHERE sql_id = :sql_id
                ORDER BY child_number
            )
            WHERE ROWNUM = 1
            """,
            sql_id=sql_id,
        )
        row = cur.fetchone()
        if not row:
            return {}
        cols = [c[0].lower() for c in cur.description]
        detail = {col: _clob_to_str(val) for col, val in zip(cols, row)}
        child_number = detail.pop("child_number")  # 실행계획 조회용으로만 쓰고 응답에는 미포함

        cur.execute(
            """
            SELECT id, parent_id, depth, operation, options, object_name,
                   cost, cardinality, LPAD(' ', depth*2) || operation AS indented_op
            FROM v$sql_plan
            WHERE sql_id = :sql_id AND child_number = :child_number
            ORDER BY id
            """,
            sql_id=sql_id, child_number=child_number,
        )
        plan_rows = _rows_as_dicts(cur)
        detail["plan"] = _flag_high_impact_steps(plan_rows)

    return detail


def _flag_high_impact_steps(plan_rows: list[dict], cost_ratio_threshold: float = 0.5) -> list[dict]:
    """실행계획에서 성능에 영향을 줄 수 있는 단계를 표시하기 위해 각 row에 high_impact 플래그를 붙인다.
    기준: (1) TABLE ACCESS FULL (인덱스 미사용 전체 스캔 - 가장 흔한 성능 저하 원인),
    또는 (2) 해당 단계의 cost가 플랜 전체 최대 cost의 cost_ratio_threshold(기본 50%) 이상인 경우."""
    costs = [r["cost"] for r in plan_rows if r.get("cost") is not None]
    max_cost = max(costs) if costs else 0
    for r in plan_rows:
        operation = (r.get("operation") or "").upper()
        options = (r.get("options") or "").upper()
        is_full_table_scan = operation == "TABLE ACCESS" and options == "FULL"
        is_high_cost = (
            max_cost > 0 and r.get("cost") is not None
            and r["cost"] >= max_cost * cost_ratio_threshold
        )
        r["high_impact"] = bool(is_full_table_scan or is_high_cost)
    return plan_rows


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


# ---------------------------------------------------------------------------
# 7) Wait Class (V$SYSTEM_EVENT 누적치 - AWR 아님, 인스턴스 시작 이후 누적이라
#    수집기가 폴링마다 델타를 계산해서 "구간 동안 대기한 초"로 환산한다)
# ---------------------------------------------------------------------------

def get_system_wait_events(conn) -> dict:
    """wait_class -> 누적 time_waited_micro. Idle 클래스는 제외(무의미한 대기)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT wait_class, SUM(time_waited_micro)
            FROM v$system_event
            WHERE wait_class != 'Idle'
            GROUP BY wait_class
            """
        )
        return {wc: val for wc, val in cur.fetchall()}


# ---------------------------------------------------------------------------
# 8) OS CPU 시간 분해 (V$OSSTAT 누적치 - Sys/User/IOWait 델타 계산용)
#    플랫폼에 따라 IOWAIT_TIME 등 일부 stat 이 없을 수 있음 (예: Windows) -
#    없으면 결과 dict 에 키가 아예 빠지므로 호출부에서 .get() 으로 방어.
# ---------------------------------------------------------------------------

def get_os_cpu_times(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT stat_name, value FROM v$osstat
            WHERE stat_name IN ('USER_TIME', 'SYS_TIME', 'IOWAIT_TIME', 'NUM_CPUS')
            """
        )
        return {name.upper(): val for name, val in cur.fetchall()}


# ---------------------------------------------------------------------------
# 9) V$SYSSTAT 누적 지표 (IO/Exec/Redo/Select Stat 탭 - 라이선스 무관 베이스 뷰)
# ---------------------------------------------------------------------------

TRACKED_SYSSTAT_NAMES = [
    "session logical reads",
    "physical reads",
    "physical reads direct",
    "physical writes direct",
    "execute count",
    "parse count (total)",
    "redo size",
    "redo writes",
    "user commits",
    "user rollbacks",
]


def get_sysstat_metrics(conn, names: list[str] | None = None) -> dict:
    """names 에 있는 V$SYSSTAT.NAME 들의 현재 누적값. 이름은 코드에 고정된
    상수 목록만 사용하므로(사용자 입력 아님) bind 변수로 안전하게 IN 절 구성."""
    names = names or TRACKED_SYSSTAT_NAMES
    placeholders = {f"n{i}": name for i, name in enumerate(names)}
    in_clause = ", ".join(f":{k}" for k in placeholders)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT name, value FROM v$sysstat WHERE name IN ({in_clause})",
            placeholders,
        )
        return {name: val for name, val in cur.fetchall()}


def get_available_sysstat_names(conn) -> list[str]:
    """'Select Stat' 드롭다운용 - 조회 전용, 전체 지표명 목록."""
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM v$sysstat ORDER BY name")
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# 10) 세션 카운트 (Total Sessions 탭 - 시점 스냅샷, 델타 아님)
# ---------------------------------------------------------------------------

def get_session_counts(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) FROM v$session WHERE type = 'USER' GROUP BY status"
        )
        counts = {status.lower(): cnt for status, cnt in cur.fetchall()}
    active = counts.get("active", 0)
    inactive = counts.get("inactive", 0)
    return {"total": active + inactive, "active": active, "inactive": inactive}
