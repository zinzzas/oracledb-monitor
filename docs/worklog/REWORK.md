# Worklog / REWORK

`canalframe-harness` 패턴을 따르는 작업 이력 기록. 완료된 주요 작업과 **미해결 항목(REWORK)**을 여기에 남깁니다.

---

## 2026-07-10 — 하네스 이식

- `canalframe-harness`(멀티레포·Java/Gradle·React|Vue 전제)를 `oracledb-monitor`(단일 레포·Python/FastAPI·Jinja2)에 맞게 축약 이식.
- 팀 통합: `planner+architect+aa` → `@aa`, `fe-react/fe-vue` → `@frontend`, `be-core/be-service` → `@backend`. reviewer 서브롤은 `@tester`가 겸임.
- 테스트 피라미드: SonarQube/Gradle/JUnit/Playwright → lint(선택)/`pytest`/`scripts/test_connection.py`로 대체.
- Oracle 라이선스 경계(`V$ACTIVE_SESSION_HISTORY`/`DBA_HIST_*`/AWR 금지)를 `db.mdc` + `CONVENTIONS.md` + `security.mdc`에 이 프로젝트 고유 규칙으로 반영.

### REWORK (미해결)

- [ ] 실제 Oracle DB 접속 테스트 미완료 (`Connection refused` — DSN/방화벽/VPN 확인 필요, `scripts/test_connection.py`로 재확인 예정)
- [ ] `activeTeams`가 실제로 잘 동작하는지 (Cursor에서 `.mdc` alwaysApply/globs 인식 여부) 첫 실사용 세션에서 검증 필요
