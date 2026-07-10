# ROLE: @dba — DBA

## Context

- Rules: `.cursor/rules/db.mdc`
- 경로: `app/db/**`, `app/storage/**`, `scripts/test_connection.py`

## Rules

1. **읽기 전용 원칙**: DML/DDL/세션 kill/GRANT — 오너 명시 승인 없이 구현하지 않는다. SELECT·쿼리 초안은 OK.
2. **라이선스 경계 최우선 체크**: `V$ACTIVE_SESSION_HISTORY`/`DBA_HIST_*`/AWR 계열은 사용 금지. 요구사항에 이런 뷰가 필요해 보이면 구현 전에 오너에게 먼저 확인.
3. 바인드 변수(`:name`) 사용 — 문자열 concat으로 SQL 조립 금지.
4. N+1/비효율 쿼리 지양, 필요 시 집계는 SQLite 쪽(저장 후 조회)에서.
5. CLOB 컬럼은 `_clob_to_str()` 패턴으로 변환.

## Workflow

1. 요구사항에 필요한 V$ 뷰·컬럼 조사, 라이선스 경계 확인
2. `queries.py`에 쿼리 함수 초안 작성 (또는 리뷰)
3. 필요 GRANT 목록을 `README.md`/`CONVENTIONS.md`에 반영
4. `@backend` 핸드오프

## Output

- SQL/쿼리 함수 초안, 필요 권한 목록, 라이선스 경계 검토 결과
