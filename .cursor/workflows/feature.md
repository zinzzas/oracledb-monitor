# Workflow: 새 지표/페이지 추가

**공통**: [feedback-loop.md](./feedback-loop.md)

## Teams (순서)

1. **@co** — 요구사항 분해, 라이선스 경계 해당 여부 사전 체크
2. **@aa** — (설계 변경 규모가 크면) `docs/plan.md` 반영
3. **@dba** — 필요 V$ 뷰/컬럼 조사, `db.mdc` 라이선스 경계 확인, 쿼리 함수 초안
4. **[병렬]** **@backend**(API/수집기 반영) + **@frontend**(템플릿/차트, 스키마 확정 후 시작 가능하면 병렬)
5. **@tester** — 정적(스코프·컨벤션·경계) → 동적(`test_connection.py`/pytest) — **↔ FAIL**: 담당 팀 fix → 재검증
6. **@security** — 크리덴셜/쓰기 작업 영향 있을 때만 — **↔ FAIL**: fix → re-security
7. **@co** — worklog (`docs/worklog/REWORK.md`)

## Rules

- 최소 diff. 새 V$ 쿼리는 반드시 `db.mdc` 허용 목록 안에서만.
- SQLite 스키마 변경 시 기존 데이터 마이그레이션 여부 확인 (없으면 `DROP`/재생성 전 오너 확인).
