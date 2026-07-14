"""
FastAPI 엔트리포인트.

실행:
    uvicorn app.main:app --reload --port 8000
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.connection import get_pool, close_pool
from app.db import queries
from app.storage import sqlite_store
from app.collectors import metrics_collector
from app.export import excel_export

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Oracle Monitor")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

_scheduler = None


@app.on_event("startup")
async def on_startup():
    global _scheduler
    get_pool()  # 커넥션 풀 초기화 (실패 시 여기서 바로 에러가 나서 원인 파악이 쉬움)
    sqlite_store.init_db()
    _scheduler = metrics_collector.start_scheduler()
    # 시작하자마자 백그라운드로 첫 수집을 돌려 첫 화면이 비어있지 않도록 한다.
    # await로 막으면 Oracle V$ 뷰 10개 순차 조회가 끝날 때까지 uvicorn이 어떤 HTTP 요청도
    # 받지 못해(ASGI startup 이벤트가 끝나야 서빙 시작) 최초 새로고침이 9~10초까지 걸렸던 원인이다.
    # 대시보드는 이미 로딩 상태를 보여주니까 몇 초 뒤 WebSocket broadcast로 실제 데이터가 도착해도 괜찮다.
    asyncio.create_task(metrics_collector.collect_once())


@app.on_event("shutdown")
async def on_shutdown():
    if _scheduler:
        _scheduler.shutdown(wait=False)
    close_pool()


# ---------------------------------------------------------------------------
# 페이지 (HTML)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    comparable_stats = [
        ("cpu_pct", "CPU %"),
        ("active_sessions", "Active Sessions"),
        ("mem_used_mb", "Memory Used (MB)"),
    ] + [(name, name) for name in queries.TRACKED_SYSSTAT_NAMES]
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "poll_interval": settings.poll_interval_sec,
            "instance_label": settings.instance_label,
            "comparable_stats": comparable_stats,
        },
    )


@app.get("/sql/{sql_id}", response_class=HTMLResponse)
async def sql_detail_page(request: Request, sql_id: str):
    pool = get_pool()
    with pool.acquire() as conn:
        detail = await asyncio.to_thread(queries.get_sql_detail, conn, sql_id)
    return templates.TemplateResponse(
        "sql_detail.html", {"request": request, "sql_id": sql_id, "detail": detail}
    )


# 맥스게이지 스타일 상세화면. metric 값: cpu-mem, active-sessions, lock-waiting,
# wait-class, cpu-breakdown, sysstat, total-sessions
DETAIL_METRICS = {
    "cpu-mem": "CPU / Memory",
    "active-sessions": "Active Sessions",
    "lock-waiting": "Lock Waiting Sessions",
    "wait-class": "Wait Class",
    "cpu-breakdown": "CPU (Sys/User/IO Wait)",
    "sysstat": "Select Stat (IO/Exec/Redo 포함)",
    "total-sessions": "Total Sessions",
    "long-session": "Long Active Session Count",
}


@app.get("/detail/{metric}", response_class=HTMLResponse)
async def detail_page(request: Request, metric: str):
    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "metric": metric,
            "title": DETAIL_METRICS.get(metric, metric),
            "is_sysstat": metric == "sysstat",
            "tracked_stats": queries.TRACKED_SYSSTAT_NAMES,
        },
    )


@app.get("/detail/plsql-calls/page", response_class=HTMLResponse)
async def plsql_calls_detail_page(request: Request):
    """PL/SQL Package Calls 전용 상세페이지. 차트가 아니라 날짜별 조회 테이블 + 엑셀
    다운로드라 구조가 다른 detail.html 대신 전용 템플릿을 쓴다."""
    return templates.TemplateResponse("plsql_calls_detail.html", {"request": request})


# ---------------------------------------------------------------------------
# REST API (HTMX 부분 갱신 / 초기 로딩용)
# ---------------------------------------------------------------------------

@app.get("/api/overview")
async def api_overview():
    return metrics_collector.LATEST["overview"] or {}


@app.get("/api/sessions")
async def api_sessions():
    return metrics_collector.LATEST["sessions"]


@app.get("/api/locks")
async def api_locks():
    return metrics_collector.LATEST["locks"]


@app.get("/api/slow-queries")
async def api_slow_queries():
    return metrics_collector.LATEST["slow_queries"]


@app.get("/api/xlog")
async def api_xlog(minutes: int = 30):
    return await asyncio.to_thread(sqlite_store.get_xlog, minutes)


@app.get("/api/alerts")
async def api_alerts(limit: int = 50):
    """Alert Log 패널 초기 로딩용 (이후는 WebSocket으로 신규 건만 push 된다)."""
    return await asyncio.to_thread(sqlite_store.get_recent_alerts, limit)


@app.get("/api/plsql-calls")
async def api_plsql_calls(minutes: int = 30, limit: int = 50):
    """PL/SQL Package Calls 위젯 초기 로딩용 - 최근 N분간 패키지별 합계 호출횟수/수행시간.
    V$SQL 누적 카운터 기반이라 V$SESSION 폴링 손실과 무관하게 집계된다."""
    return await asyncio.to_thread(sqlite_store.get_recent_plsql_calls, minutes, limit)


@app.get("/api/plsql-calls/range")
async def api_plsql_calls_range(start: int, end: int):
    """PL/SQL Package Calls 상세페이지 날짜별 조회 - 폴링 건단위 원시 row 목록."""
    rows = await asyncio.to_thread(sqlite_store.get_plsql_call_log_range, start, end)
    return {"rows": rows}


@app.get("/api/plsql-calls/export")
async def api_plsql_calls_export(start: int, end: int):
    """PL/SQL Package Calls 날짜별 조회 결과를 엑셀로 다운로드."""
    rows = await asyncio.to_thread(sqlite_store.get_plsql_call_log_range, start, end)
    xlsx_bytes = excel_export.build_plsql_calls_excel(rows, start, end)
    filename = f"plsql_package_calls_{start}_{end}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sysstat-names")
async def api_sysstat_names():
    """'Select Stat' 드롭다운용 - V$SYSSTAT 전체 지표명 + 실제 추적 중인 목록."""
    pool = get_pool()
    with pool.acquire() as conn:
        names = await asyncio.to_thread(queries.get_available_sysstat_names, conn)
    return {"names": names, "tracked": queries.TRACKED_SYSSTAT_NAMES}


@app.get("/api/detail/{metric}")
async def api_detail(metric: str, start: int, end: int, stat: Optional[str] = None):
    """상세화면용 구간 조회. start/end 는 epoch 초."""
    if metric == "cpu-mem" or metric == "active-sessions":
        buckets = await asyncio.to_thread(sqlite_store.get_metric_range, start, end)
        return {"buckets": buckets}

    if metric == "lock-waiting":
        buckets = await asyncio.to_thread(sqlite_store.get_lock_count_range, start, end)
        return {"buckets": buckets}

    if metric == "wait-class":
        series = await asyncio.to_thread(sqlite_store.get_wait_class_range, start, end)
        return {"series": series}

    if metric == "cpu-breakdown":
        buckets = await asyncio.to_thread(sqlite_store.get_cpu_breakdown_range, start, end)
        return {"buckets": buckets}

    if metric == "sysstat":
        name = stat or queries.TRACKED_SYSSTAT_NAMES[0]
        buckets = await asyncio.to_thread(sqlite_store.get_sysstat_range, name, start, end)
        return {"stat": name, "buckets": buckets}

    if metric == "total-sessions":
        buckets = await asyncio.to_thread(sqlite_store.get_session_count_range, start, end)
        return {"buckets": buckets}

    if metric == "long-session":
        result = await asyncio.to_thread(sqlite_store.get_long_session_range, start, end)
        return {"buckets": result["rows"], "bucket_sec": result["bucket_sec"]}

    return {"error": f"unknown metric: {metric}"}


@app.get("/api/long-session/queries")
async def api_long_session_queries(start: int, end: int, tier: Optional[str] = None):
    """Long Active Session Count 막대 클릭 드릴다운 - 해당 구간/티어의 3초 이상 실행 스냅샷 목록."""
    rows = await asyncio.to_thread(sqlite_store.get_long_query_log, start, end, tier)
    return {"rows": rows}


@app.get("/api/long-session/queries/export")
async def api_long_session_queries_export(start: int, end: int, tier: Optional[str] = None):
    """Long Active Session Count 드릴다운 결과를 엑셀로 다운로드. SQL_ID가 있는 로우에 한해
    V$SQL_BIND_CAPTURE 최선노력 바인드값을 함께 담는다 (REF CURSOR/OUT 파라미터는 상당수
    빈 란으로 남을 수 있음 - 안내 시트에 한계 명시)."""
    rows = await asyncio.to_thread(sqlite_store.get_long_query_log, start, end, tier, 5000)

    sql_ids = [r["sql_id"] for r in rows if r.get("sql_id")]
    bind_map: dict[str, str] = {}
    if sql_ids:
        try:
            pool = get_pool()
            with pool.acquire() as conn:
                bind_map = await asyncio.to_thread(queries.get_bind_capture_for_sql_ids, conn, sql_ids)
        except Exception as e:
            logging.getLogger("main").warning("bind capture 조회 실패(무시하고 계속): %s", e)

    for r in rows:
        r["bind_params_text"] = bind_map.get(r.get("sql_id"), "")

    xlsx_bytes = excel_export.build_long_session_excel(rows, start, end)
    filename = f"long_active_sessions_{start}_{end}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/trend-comparison")
async def api_trend_comparison(stat: str = "cpu_pct", skip_weekend: bool = True):
    """24 Hours Trend Comparison - 오늘(자정~현재) vs 전 영업일(또는 단순 어제) 같은 시간대 겹쳐보기.
    skip_weekend=True 면 비교일이 토/일이면 직전 평일까지 거슬러 올라간다."""
    now = datetime.now()
    today_start_dt = datetime(now.year, now.month, now.day)
    today_start = int(today_start_dt.timestamp())
    today_end = int(now.timestamp())
    elapsed_today = today_end - today_start

    compare_day = today_start_dt - timedelta(days=1)
    if skip_weekend:
        while compare_day.weekday() >= 5:  # 5=Sat, 6=Sun
            compare_day -= timedelta(days=1)
    compare_start = int(compare_day.timestamp())
    compare_end = compare_start + elapsed_today

    data = await asyncio.to_thread(
        sqlite_store.get_trend_comparison, stat, today_start, today_end, compare_start, compare_end
    )
    data["compare_date"] = compare_day.strftime("%Y-%m-%d")
    return data


# ---------------------------------------------------------------------------
# WebSocket (실시간 push - X-log, 대시보드 자동 갱신)
# ---------------------------------------------------------------------------

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    metrics_collector.register_subscriber(websocket)
    try:
        # 접속 직후 최신값 1회 전송
        await websocket.send_json({"type": "update", **metrics_collector.LATEST})
        while True:
            # 클라이언트로부터의 메시지는 사용하지 않지만, 연결 유지를 위해 대기
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        metrics_collector.unregister_subscriber(websocket)
