# Workflow: Bugfix

**공통**: [feedback-loop.md](./feedback-loop.md)

## Teams (순서)

1. **@co** — 재현·영향·담당 팀 분류
2. **Dev team** (경로): `@backend` | `@frontend` | `@dba`
3. **@tester** — diff 기준 회귀 확인 (정적 → 동적) — **↔ FAIL**: dev fix → 재검증만
4. **@security** — (크리덴셜/쿼리 안전성 관련 버그면) — **↔ FAIL**: dev fix → re-security
5. **@co** — worklog·`REWORK.md`

## Rules

- 최소 diff; 원인·조치 worklog 기록.
- Windows/Mac 등 **환경 차이로 인한 버그**(예: Python 버전 문법 이슈)는 `backend.mdc`/`project-core.mdc`에도 규칙으로 반영해 재발 방지 (실제로 `X | None` PEP604 이슈가 이런 케이스였음).
