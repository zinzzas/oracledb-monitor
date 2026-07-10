"""
FastAPI 엔트리포인트.

실행:
    uvicorn app.main:app --reload --port 8000
"""
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.connection import get_pool, close_pool
from app.db import queries
from app.storage import sqlite_store
from app.collectors import metrics_collector

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Oracle DB Monitor")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

_scheduler = None


@app.on_event("startup")
async def on_startup():
    global _scheduler
    get_pool()  # 커넥션 풀 초기화 (실패 시 여기서 바로 에러가 나서 원인 파악이 쉬움)
    sqlite_store.init_db()
    _scheduler = metrics_collector.start_scheduler()
    # 시작하자마자 한 번 즉시 수집해서 첫 화면이 비어있지 않도록 한다.
    await metrics_collector.collect_once()


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
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "poll_interval": settings.poll_interval_sec}
    )


@app.get("/sql/{sql_id}", response_class=HTMLResponse)
async def sql_detail_page(request: Request, sql_id: str):
    pool = get_pool()
    with pool.acquire() as conn:
        detail = await asyncio.to_thread(queries.get_sql_detail, conn, sql_id)
    return templates.TemplateResponse(
        "sql_detail.html", {"request": request, "sql_id": sql_id, "detail": detail}
    )


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
