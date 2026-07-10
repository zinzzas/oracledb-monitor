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

## 2026-07-10 — 제니퍼/맥스게이지 스타일 대시보드 리디자인

- **카드 강조**: CPU/MEM 카드에 임계치 색상 단계(60~70%=주황/70~80%=진한주황/80~100%=레드) + 미니 게이지바 + crit 펄스 애니메이션 추가.
- **블록 레이아웃**: 카드/패널을 그리드 블록으로 재구성, X-log에 ECharts `markPoint(max)` + `endLabel`로 피크값·현재값 동시 표시.
- **백엔드 확장** (`app/db/queries.py`): `V$SYSTEM_EVENT`(Wait Class), `V$OSSTAT`(Sys/User/IOWait 분해), `V$SYSSTAT`(IO/Exec/Redo/Select Stat) 추가 — 모두 라이선스 무관 베이스 뷰.
- **수집기**: 누적치 델타 계산 로직(`_compute_deltas`) 추가 — 첫 폴링은 기준점만 잡고 저장하지 않음.
- **SQLite**: `wait_class_snapshot`/`cpu_breakdown_snapshot`/`sysstat_snapshot`/`session_count_snapshot` 테이블 + 구간 버켓(avg/max) 조회 함수 추가 (`_bucketize`).
- **상세화면** (`/detail/{metric}`, 7종): 검색조건바(오늘/어제/최근1·6시간 + 커스텀 기간) + ECharts `dataZoom` → 줌 구간의 최대값이 `markPoint`로 자동 표시.
- 테스트 중 발견한 버그: 상세화면 재검색 시 `chartEl.innerHTML` 직접 덮어쓰기가 차트 DOM을 파괴하던 문제 → `chart.showLoading()/hideLoading()`로 교체해 해결.
- 백엔드 로직(델타 계산, 버켓집계, bind 변수 IN절 구성)은 샌드박스에서 실제 SQLite/모의 데이터로 런타임 검증 완료.

### REWORK (미해결)

- [ ] 실제 Oracle에서 `V$SYSTEM_EVENT`/`V$SYSSTAT` 조회 권한 확인 필요 (SELECT_CATALOG_ROLE이면 보통 포함되지만 미확인)
- [ ] Windows에서 `V$OSSTAT.IOWAIT_TIME`이 없을 수 있음 — CPU 분해 패널에서 IO Wait가 빈값/0으로 나오는지 실제 확인 필요
- [ ] 브라우저에서 실제 렌더링 확인 (서버 재시작 후)
