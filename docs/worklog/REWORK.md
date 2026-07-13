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

## 2026-07-10 — DESIGN.md(스타벅스 시스템) 적용 + UX 개선

- **DESIGN.md 분석 후 전 템플릿 재디자인**: 웈크림 캔버스(`#f2f0eb`) + 화이트카드 + 그린 브랜드시스템(Green Accent/House Green) + 50px 필버튼 + 위스퍼샤도로 통일. Gift Card/Frap 플로팅버튼/PDP 클러스터는 이 앱에 대응 컴포넌트가 없어 제외.
- 임계치 색상을 DESIGN.md 팔레트에 맞게 재매핑 (Yellow→Amber→Red 단계, Gold는 그들의 자체 규칙대로 범용 액센트로 쓰지 않음).
- **좌측 아이콘 사이드바**: 상단 우측 메뉴 → House Green 좌측 레일로 이동, 각 섹션별 인라인 SVG 아이콘(대시보드/실행쿼리/Lock/슬로우쿼리) + hover 툴팀.
- X-log/미니차트 grid에 `containLabel:true` 적용해 세로축 라벨 잘림 해결, 차트 높이 증가.
- 모든 "상세보기" 링크에 `target="_blank" rel="noopener"` 추가 (SQL_ID 드릴다운 링크도 동일 적용).
- **검증**: 샌드박스에서 `node --check`로 dashboard/detail 인라인 JS 문법 검증, `jinja2`로 detail.html(is_sysstat true/false)와 sql_detail.html(detail None/있음) 양쪽 분기 렌더링 테스트 모두 통과.

### REWORK (미해결)

- [ ] 실제 브라우저에서 크림 톤/그린 배색이 모니터링 데이터와 시각적으로 잘 어울리는지 육안 확인 (운영툴 특성상 다크모드 선호도가 높을 수 있음 — 필요시 다크모크 토글 추가 검토)

## 2026-07-13 — MaxGauge 레퍼런스 기준 위젯 구성 + DESIGN.md NVIDIA 시스템 재적용

- **DESIGN.md 교체(엔비디아 시스템)**: 블랙+화이트 투톤, 단일 그린 액센트(`#76b900`), 2px 각진 지오메트리, 섀도우 없이 헤어라인 보더만 사용. 임계치 60~70/70~80/80~100%가 NVIDIA 자체 시맨틱 컬러(warning/warning-bright/error)와 그대로 맞아떨어짐.
- **MaxGauge 위젯 비교 분석 후 이식**: CPU Memory 도넛, SQL Elapsed Time 스캐터, Alert Log, Session Logical/Physical Reads 실시간 패널 신규 추가. Load Balance는 라이선스가 아니라 멀티인스턴스/RAC 전용 개념이라 단일 인스턴스 아키텍처에 대응 불가로 스킵.
- **Alert Log 신규 구축**: `alert_log` 테이블 + 임계치 전이(None→warn→high→crit) edge-triggered 감지 로직(`_check_alert_transitions`) — AWR 없이 자체 구축, 샌드박스에서 실제 SQLite로 6단계 전이 시나리오 런타임 검증 완료.
- **Active Sessions 확장**: `V$PROCESS`(PGA)/`V$SQLCOMMAND`(Command 텍스트) 조인 추가, Module/Program/P1-3 컬럼 추가, 헤더 클릭 정렬(client-side data-driven sort) + 행별 SQL 복사 버튼.
- **SQL 상세**: 실행계획 테이블 정렬(DOM 재배열 방식) + SQL 전문 복사 버튼 추가.
- **SQL Elapsed Time 스캐터 드래그-부러시 팝업**: ECharts `brush`(rect) 기본 활성화 + `brushSelected` 이벤트로 선택된 구간의 SQL 목록을 모달로 표시.
- **버그 발견/수정**: `sysstat_live` 브로드캐스트가 단순 숫자(rate_per_sec)만 보내던 것을 프론트가 `.delta_value` 객체 속성을 기대하던 불일치 발견 → 백엔드에서 전체 row dict를 보내도록 수정.
- **검증**: `node --check`로 dashboard.html/sql_detail.html 인라인 JS 전체 구문 검증, jinja2로 실행계획 None cost/cardinality sentinel(-1) 렌더링 테스트 통과.

### V2로 명시적 분리 (이번 턴에서는 미구현)

- [ ] **24 Hours Trend Comparison** (어제/오늘 겹쳐보기) — `get_metric_range`를 두 번 호출해 시간대 기준으로 정렬하는 로직 필요
- [ ] **Long Active Session Count** (구간별 세션수 스택) — MaxGauge는 "인스턴스별"인데 우리는 단일 인스턴스라 "시간대별"로 변형 필요

### REWORK (미해결)

- [ ] 실제 Oracle에서 `V$PROCESS`/`V$SQLCOMMAND` 조회 권한 확인 필요
- [ ] 브라우저에서 실제 ECharts brush 드래그 인터랙션 감도 확인 (마우스/트랙패드 양쪽)
- [ ] Alert Log가 실제 임계치 넘을 때 제대로 쌓이는지 실사용 확인

## 2026-07-13 (V2) — 24 Hours Trend Comparison + Long Active Session Count

- **24 Hours Trend Comparison**: `get_trend_comparison()` 신규 — 오늘/비교일 각각 자정(00:00) 기준 경과초(tod_sec)로 버켓해 날짜가 달라도 같은 시간대축에 겹쳐보이게 구현. `skip_weekend` 옵션으로 비교일이 토/일이면 직전 평일까지 거슬러 올라감. STAT 드롭다운은 CPU%/Active Sessions/Mem + V$SYSSTAT 추적 지표 전체를 포함.
- **Long Active Session Count**: MaxGauge의 "인스턴스별" 스택을 "시간대별" 구간(<3s/<10s/<15s/≥15s) 스택 바차트로 변형. 수집기가 매 폴링마다 세션 elapsed_sec을 4단계 티어로 카운트해 `long_session_snapshot`에 적재 + 실시간 브로드캐스트.
- 새 쿼리 컴럼명 삽입 보안: `_get_raw_series`의 컴럼명 f-string 삽입은 고정 화이트리스트(`_METRIC_COLUMNS`) 멤버십 확인 후에만 이루어져 SQL Injection 위험 없음.
- **검증**: 샌드박스에서 실제 SQLite로 오늘/어제 가상 데이터 삽입 후 시간대 정렬 정확성 검증(9시 버켓 값이 오늘/비교일 각각 50/30으로 정확히 분리), sysstat 기반 stat도 동일 로직 확인, Long Session 버켓 평균/최대값 집계 확인. `py_compile`로 main.py 신규 엔드포인트 구문 검증, `node --check`로 대시보드 전체 JS 재검증, jinja2로 `comparable_stats` 드롭다운 렌더링 테스트 모두 통과.

### REWORK (미해결)

- [ ] 24h Trend Comparison이 실제 브라우저에서 오늘/어제 데이터로 제대로 겹쳐보이는지 육안 확인 (데이터가 충분히 쌓여야 의미 있는 비교가 가능)
- [ ] Skip Weekend 로직이 월요일 아침에 실행해도(직전 금요일로 거슬러올라감) 의도대로 동작하는지 실제 날짜로 확인