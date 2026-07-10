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
}

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

    sqlite_store.insert_metric_snapshot(snapshot)
    sqlite_store.insert_slow_queries(slow)
    sqlite_store.insert_lock_events(locks)
    sqlite_store.insert_session_counts(session_counts)

    deltas = _compute_deltas(time.time(), wait_events, os_times, sysstat)
    cpu_breakdown = None
    wait_class_rows: list = []
    if deltas:
        cpu_breakdown = deltas["cpu_breakdown"]
        wait_class_rows = deltas["wait_class"]
        sqlite_store.insert_wait_class(wait_class_rows)
        sqlite_store.insert_cpu_breakdown(cpu_breakdown)
        sqlite_store.insert_sysstat(deltas["sysstat"])

    return {
        "overview": {**overview, "active_sessions": snapshot["active_sessions"]},
        "sessions": sessions,
        "locks": locks,
        "slow_queries": slow,
        "cpu_breakdown": cpu_breakdown,
        "wait_class": wait_class_rows,
        "session_counts": session_counts,
    }


async def collect_once():
    try:
        result = await asyncio.to_thread(_collect_once_sync)
        LATEST.update(result)
        await _broadcast({"type": "update", **result})
    except Exception as e:
        logger.exception("collector 실패: %s", e)


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
        sqlite_store.purge_old,
        "interval",
        hours=1,
        id="retention_purge",
    )
    scheduler.start()
    return scheduler
