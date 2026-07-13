"""
백그라운드 수집기.
POLL_INTERVAL_SEC 마다 Oracle에서 스냅샷을 뽑아 SQLite에 적재하고,
현재 상태를 in-memory 캐시(app.state 대체용 LATEST)에 올려 WebSocket/REST가
Oracle을 매번 다시 조회하지 않고 바로 응답할 수 있게 한다.
"""
import asyncio
import logging
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db.connection import get_pool
from app.db import queries
from app.storage import sqlite_store

logger = logging.getLogger("collector")

# 최신 스냅샷 캐시 (WebSocket broadcast, REST 즉시응답용)
LATEST: dict = {
    "overview": None,
    "sessions": [],
    "locks": [],
    "slow_queries": [],
    "cpu_breakdown": None,
    "wait_class": [],
    "session_counts": None,
    "sysstat_live": {},
    "alerts": [],
    "long_session_counts": None,
}

# 임계치 전이(None/warn/high/crit) 추적 - 상태가 바뀌는 순간에만 alert_log 에 기록해
# 폴링(5초)마다 알림이 쓸리는 것을 방지한다 (edge-triggered).
_alert_state: dict = {"cpu": None, "mem": None, "lock": None, "slow": None}

# 이전 폴링의 누적치 스냅샷 (Wait Class/CPU 분해/V$SYSSTAT는 누적 카운터라
# 두 폴링 간 차이를 계산해야 구간치가 나온다. 첫 폴링은 기준점만 잡고 저장하지 않는다.)
_prev_cumulative: dict = {
    "ts": None,
    "wait_events": {},
    "os_times": {},
    "sysstat": {},
}

# 현재 연결된 WebSocket 클라이언트들
_subscribers: set = set()


def register_subscriber(ws):
    _subscribers.add(ws)


def unregister_subscriber(ws):
    _subscribers.discard(ws)


async def _broadcast(payload: dict):
    dead = []
    for ws in _subscribers:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _subscribers.discard(ws)


def _compute_deltas(now_ts: float, wait_events: dict, os_times: dict, sysstat: dict):
    """이전 폴링 대비 누적치 델타를 계산해 구간치로 바꾸고, 현재치를 다음 번 기준으로 저장한다.
    첫 폴링(기준점 없음)이면 None 반환."""
    prev = _prev_cumulative
    result = None

    if prev["ts"] is not None:
        delta_t = max(now_ts - prev["ts"], 1)

        # Wait Class: micro seconds -> 구간 대기 초
        wait_class_rows = []
        for wc, val in wait_events.items():
            prev_val = prev["wait_events"].get(wc, val)
            delta_micro = max(val - prev_val, 0)
            wait_class_rows.append({"wait_class": wc, "wait_sec": round(delta_micro / 1_000_000, 3)})

        # CPU 분해 (%) - centisecond 누적치 델타 / (구간초 * CPU개수)
        num_cpus = os_times.get("NUM_CPUS") or 1

        def _cpu_pct(key: str):
            cur_v = os_times.get(key)
            prev_v = prev["os_times"].get(key)
            if cur_v is None or prev_v is None:
                return None
            delta = max(cur_v - prev_v, 0)
            return round(delta / (delta_t * num_cpus), 2)

        cpu_breakdown = {
            "user_pct": _cpu_pct("USER_TIME"),
            "sys_pct": _cpu_pct("SYS_TIME"),
            "iowait_pct": _cpu_pct("IOWAIT_TIME"),
        }

        # V$SYSSTAT: 누적치 델타 -> 초당 레이트
        sysstat_rows = []
        for name, val in sysstat.items():
            prev_val = prev["sysstat"].get(name, val)
            delta = max(val - prev_val, 0)
            sysstat_rows.append({
                "stat_name": name,
                "delta_value": delta,
                "rate_per_sec": round(delta / delta_t, 3),
            })

        result = {
            "wait_class": wait_class_rows,
            "cpu_breakdown": cpu_breakdown,
            "sysstat": sysstat_rows,
        }

    prev["ts"] = now_ts
    prev["wait_events"] = wait_events
    prev["os_times"] = os_times
    prev["sysstat"] = sysstat
    return result


_LEVEL_LABEL = {"warn": "Warning", "high": "Warning", "crit": "Critical"}


def _level_for_pct(pct):
    if pct is None:
        return None
    if pct >= settings.alert_crit_pct:
        return "crit"
    if pct >= settings.alert_high_pct:
        return "high"
    if pct >= settings.alert_warn_pct:
        return "warn"
    return None


def _check_alert_transitions(overview: dict, locks: list, slow: list) -> list:
    """MaxGauge의 Alert Log 위젯 대응. 상태가 바뀌는 순간에만(edge-triggered)
    alert_log 에 기록하고, 그 순간 새로 생긴 알림들만 반환해 broadcast에 포함한다."""
    instance = settings.instance_label
    new_alerts = []

    def _transition(key, new_level, name, value, log_msg):
        if new_level != _alert_state.get(key):
            if new_level is not None:
                level_label = _LEVEL_LABEL[new_level]
                row = sqlite_store.insert_alert(instance, name, value, level_label, log_msg)
                new_alerts.append(row)
            _alert_state[key] = new_level

    cpu_pct = overview.get("cpu_pct")
    _transition("cpu", _level_for_pct(cpu_pct), "CPU USAGE", cpu_pct, f"CPU {cpu_pct}%")

    mem_pct = None
    if overview.get("mem_total_mb"):
        mem_pct = round(overview["mem_used_mb"] / overview["mem_total_mb"] * 100, 1)
    _transition("mem", _level_for_pct(mem_pct), "MEMORY USAGE", mem_pct, f"Memory {mem_pct}%")

    lock_level = "warn" if locks else None
    _transition(
        "lock", lock_level, "LOCK WAITING", len(locks),
        f"{len(locks)} blocking session(s) detected",
    )

    slow_level = "warn" if slow else None
    _transition(
        "slow", slow_level, "SLOW QUERY", (slow[0]["avg_elapsed_sec"] if slow else 0),
        f"{len(slow)} slow quer{'y' if len(slow) == 1 else 'ies'} "
        f"(threshold {settings.slow_query_threshold_sec}s)",
    )

    return new_alerts


def _bucket_session_durations(sessions: list) -> dict:
    """Long Active Session Count 위젯용 - elapsed_sec 기준 4단계 티어로 카운트."""
    counts = {"cnt_lt3": 0, "cnt_lt10": 0, "cnt_lt15": 0, "cnt_ge15": 0}
    for s in sessions:
        el = s.get("elapsed_sec")
        if el is None:
            continue
        if el < 3:
            counts["cnt_lt3"] += 1
        elif el < 10:
            counts["cnt_lt10"] += 1
        elif el < 15:
            counts["cnt_lt15"] += 1
        else:
            counts["cnt_ge15"] += 1
    return counts


def _log_long_queries(sessions: list) -> list[dict]:
    """3초 이상 실행 중인 개별 세션을 저장해 Long Active Session Count 막대
    클릭 시 SQL/실행계획으로 드릴다운할 수 있게 한다. 3초 미만은 노이즈라 저장하지 않는다."""
    ts = int(time.time())
    rows = []
    for s in sessions:
        el = s.get("elapsed_sec")
        if el is None or el < 3:
            continue
        if el < 10:
            tier = "lt10"
        elif el < 15:
            tier = "lt15"
        else:
            tier = "ge15"
        rows.append({
            "ts": ts, "sql_id": s.get("sql_id"), "elapsed_sec": el, "tier": tier,
            "username": s.get("username"), "module": s.get("module"),
            "sql_text": s.get("sql_text"), "is_plsql_call": s.get("is_plsql_call", False),
        })
    return rows


def _collect_once_sync():
    """동기 Oracle 조회 (블로킹) - asyncio.to_thread 로 실행됨."""
    pool = get_pool()
    with pool.acquire() as conn:
        overview = queries.get_host_cpu_mem(conn)
        overview.update(queries.get_sga_pga(conn))

        snapshot = queries.get_snapshot(conn)
        sessions = queries.get_active_sessions(conn)
        locks = queries.get_blocking_chains(conn)
        slow = queries.get_slow_queries(
            conn, min_avg_elapsed_sec=settings.slow_query_threshold_sec
        )

        wait_events = queries.get_system_wait_events(conn)
        os_times = queries.get_os_cpu_times(conn)
        sysstat = queries.get_sysstat_metrics(conn)
        session_counts = queries.get_session_counts(conn)

    long_session_counts = _bucket_session_durations(sessions)
    long_query_rows = _log_long_queries(sessions)

    deltas = _compute_deltas(time.time(), wait_events, os_times, sysstat)
    cpu_breakdown = None
    wait_class_rows: list = []
    sysstat_live: dict = {}
    sysstat_rows_for_write = None
    if deltas:
        cpu_breakdown = deltas["cpu_breakdown"]
        wait_class_rows = deltas["wait_class"]
        sysstat_rows_for_write = deltas["sysstat"]
        sysstat_live = {r["stat_name"]: r for r in deltas["sysstat"]}

    # 폴링 한 번의 모든 쓰기를 단일 커넥션/트랜잭션으로 묶는다
    # (이전에는 폴링마다 7~9개의 개별 커넥션을 열고 닫았음 — 대시보드 로딩 속도 개선 재검토 항목).
    sqlite_store.write_poll_batch(
        metric_snapshot=snapshot,
        slow_queries=slow,
        lock_events=locks,
        session_counts=session_counts,
        long_session_counts=long_session_counts,
        long_query_rows=long_query_rows,
        wait_class_rows=wait_class_rows or None,
        cpu_breakdown=cpu_breakdown,
        sysstat_rows=sysstat_rows_for_write,
    )

    overview_full = {**overview, "active_sessions": snapshot["active_sessions"]}
    new_alerts = _check_alert_transitions(overview_full, locks, slow)

    return {
        "overview": overview_full,
        "sessions": sessions,
        "locks": locks,
        "slow_queries": slow,
        "cpu_breakdown": cpu_breakdown,
        "wait_class": wait_class_rows,
        "session_counts": session_counts,
        "sysstat_live": sysstat_live,
        "alerts": new_alerts,
        "long_session_counts": long_session_counts,
    }


async def collect_once():
    try:
        result = await asyncio.to_thread(_collect_once_sync)
        LATEST.update(result)
        await _broadcast({"type": "update", **result})
    except Exception as e:
        logger.exception("collector 실패: %s", e)


async def _maintenance():
    """보존기간 지난 로우 삭제 + VACUUM. sqlite3는 동기 API라 to_thread로 돌려 이벤트루프를 막지 않게 한다."""
    await asyncio.to_thread(sqlite_store.purge_old)
    await asyncio.to_thread(sqlite_store.vacuum_db)


def start_scheduler() -> AsyncIOScheduler:
    sqlite_store.init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        collect_once,
        "interval",
        seconds=settings.poll_interval_sec,
        id="metrics_collector",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _maintenance,
        "interval",
        hours=6,
        id="retention_purge_and_vacuum",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
