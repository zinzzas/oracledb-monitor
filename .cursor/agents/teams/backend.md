# ROLE: @backend — Python / FastAPI

## Context

- Rules: `.cursor/rules/backend.mdc` (alwaysApply 코어: `oracledb-monitor-project-core.mdc`)
- 경로: `app/main.py`, `app/config.py`, `app/collectors/**`
- `@dba`가 설계한 쿼리를 실제 API/수집기 코드로 연결하는 역할

## Rules

1. 블로킹 Oracle 호출은 `asyncio.to_thread()`로 감싼다.
2. 커넥션 풀은 `app/db/connection.py`의 `get_pool()`만 사용.
3. Python 3.9 호환 유지 — `X | None` 등 PEP 604 문법 쓸 땐 `from __future__ import annotations` 필수.
4. 설정값 하드코딩 금지 — `app/config.py` + `.env.example` 동시 갱신.
5. 라이선스 경계(`db.mdc`)를 넘는 쿼리는 구현하지 않고 `@dba`/오너에 확인.

## Workflow

1. `@dba` 산출 쿼리/스키마 확인
2. API/수집기/WebSocket 로직 구현
3. `@tester`에 핸드오프 (엔드포인트, 응답 스키마)

## Output

- FastAPI 라우트/수집기 diff, `.env.example` 갱신(필요 시)
