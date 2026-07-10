"""
백그라운드 수집기.
POLL_INTERVAL_SEC 마다 Oracle에서 스냅샷을 뽑아 SQLite에 적재하고,
현재 상태를 in-memory 캐시(app.state 대체용 LATEST)에 올려 WebSocket/REST가
Oracle을 매번 다시 조회하지 않고 바로 응답할 수 있게 한다.
"""
import asyncio
import logging
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

    sqlite_store.insert_metric_snapshot(snapshot)
    sqlite_store.insert_slow_queries(slow)
    sqlite_store.insert_lock_events(locks)

    return {
        "overview": {**overview, "active_sessions": snapshot["active_sessions"]},
        "sessions": sessions,
        "locks": locks,
        "slow_queries": slow,
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
