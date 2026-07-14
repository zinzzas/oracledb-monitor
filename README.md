# Oracle Monitor

서버 접속 없이 **클라이언트에서 리스너로 접속**해 Oracle의 CPU/메모리/실행 중 쿼리/Lock/슬로우쿼리를
실시간으로 모니터링하는 경량 대시보드. python-oracledb Thin mode 사용 (Oracle Instant Client 불필요).

## 빠른 시작

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일을 열어 ORACLE_USER / ORACLE_PASSWORD / ORACLE_DSN 채우기

uvicorn app.main:app --reload --port 8001
```

브라우저에서 http://localhost:8000 접속.

## 사전 준비: DB 계정 권한

접속 계정에 아래 권한이 필요합니다. 서버 접속 없이 DBA가 원격 툴로 GRANT 해주면 됩니다.

```sql
GRANT CREATE SESSION TO monitor_user;
GRANT SELECT_CATALOG_ROLE TO monitor_user;
```

(더 좁게 가고 싶다면 `app/db/queries.py` 상단 주석에 최소 권한 목록이 있습니다.)

## 구조

```
app/
├── main.py                # FastAPI 엔트리포인트 (라우팅, WebSocket)
├── config.py               # .env 기반 설정
├── db/
│   ├── connection.py       # python-oracledb Thin mode 커넥션 풀
│   └── queries.py          # V$ 뷰 조회 함수 모음 (CPU/Mem/세션/Lock/슬로우쿼리)
├── collectors/
│   └── metrics_collector.py # APScheduler 기반 주기적 수집 + WebSocket broadcast
├── storage/
│   └── sqlite_store.py     # X-log(시계열)·슬로우쿼리·Lock 이력 SQLite 저장
└── templates/
    ├── dashboard.html      # 메인 대시보드 (CPU/Mem 카드, X-log 차트, 세션/Lock/슬로우쿼리 테이블)
    └── sql_detail.html     # SQL 상세 (전문 + 실행계획)
```

## 화면 구성 및 연동 지표 (Widgets & Metrics Mapping)

대시보드의 각 화면 위젯과 상세 페이지는 라이선스 침해 우려가 없는 순수 Oracle 기본 V$ 뷰를 실시간으로 가공 및 매핑하여 사용하고 있습니다.

| 화면 영역 / 위젯명 | 수집 대상 Oracle V$ 뷰 | 상세 매핑 지표 (Metric) | 설명 |
| :--- | :--- | :--- | :--- |
| **CPU / Memory** | `V$SYSMETRIC`<br>`V$OSSTAT` | `Host CPU Utilization (%)`<br>`PHYSICAL_MEMORY_BYTES`<br>`FREE_MEMORY_BYTES`<br>`INACTIVE_MEMORY_BYTES` | **CPU**: 실시간 Host CPU 사용량 (%)<br>**메모리**: 가용 메모리(`Free + Inactive`)를 분모로 한 실제 메모리 사용률 계산 (리눅스 캐시 영역 오판 방지) |
| **SQL Elapsed Time** | `V$SESSION`<br>`V$SQL` | `LAST_CALL_ET`<br>`SQL_ID`, `SQL_TEXT` | ACTIVE 사용자 세션의 최종 쿼리 기동 경과 시간을 스캐터(산점도) 차트로 매핑 (마우스 드래그를 통해 구간별 상세 SQL 팝업 가능) |
| **Alert Log** | `SQLite (Internal)` | `alert_log` 테이블 | CPU/Memory/Lock/Slow 임계치 초과 시 상태 전이(warn/high/crit) 시점을 기록한 Edge-triggered 경보 이력 |
| **Active Sessions** | `V$SESSION` | `status = 'ACTIVE'`, `type = 'USER'` | 현재 DB에 접속하여 ACTIVE 상태로 쿼리를 수행 중인 사용자 세션의 총 합산 수 |
| **SGA / PGA (MB)** | `V$SGAINFO`<br>`V$PGASTAT` | `Total SGA Size`<br>`total PGA allocated` | SGA 전체 할당 크기 및 현재 세션들에 의해 할당된 PGA 메모리 크기 합산 |
| **Blocking Chains** | `V$SESSION` | `BLOCKING_SESSION` | 12c+ 기준 대기 중인 Lock 세션(Waiter)과 주 원인 세션(Blocker) 간의 관계 수 |
| **Logical / Physical Reads** | `V$SYSSTAT` | `session logical reads`<br>`physical reads` | **Logical**: 초당 데이터 버퍼 캐시 논리적 블록 읽기 수 (Rate/sec)<br>**Physical**: 초당 디스크 물리적 블록 읽기 수 (Rate/sec) |
| **24h Trend Comparison** | `SQLite (Internal)` | `metric_snapshot` 등 | 선택한 지표의 오늘 시간대 추이와 전 영업일(또는 어제)의 동일 시간대 겹쳐보기 시계열 |
| **Long Active Session Count** | `V$SESSION` | `LAST_CALL_ET` 버킷 카운트 | 쿼리 수행 시간을 기준으로 활성 세션을 4단계(`<3s`, `<10s`, `<15s`, `≥15s`)로 분류해 누적한 스택 바 |
| **X-LOG (실시간 추이)** | `V$SYSMETRIC`<br>`V$SESSION` | `Host CPU Utilization (%)`<br>`active sessions count` | 최근 30분 동안의 호스트 CPU 사용율 및 활성 세션 수 추이를 실시간 WebSocket으로 브로드캐스트 |
| **Wait Class (실시간 대기)** | `V$SYSTEM_EVENT` | `TIME_WAITED_MICRO` (Idle 제외) | 인스턴스 기동 이후의 누적 대기 시간을 폴링 단위 델타로 환산하여 초 단위 대기 시간으로 매핑 |
| **CPU 분해 (실시간 분해)** | `V$OSSTAT` | `USER_TIME`, `SYS_TIME`<br>`IOWAIT_TIME`, `NUM_CPUS` | 호스트 CPU 소비 시간을 커널(Sys), 유저(User), 디스크대기(IO Wait) 비율로 환산해 분해 |
| **Active Sessions 테이블** | `V$SESSION`<br>`V$PROCESS`<br>`V$SQLCOMMAND` | `SID`, `SERIAL#`, `EVENT`, `PGA_ALLOC_MEM`, `SQL_TEXT` 등 | 현재 실행 중인 활성 세션의 상세 세션 정보, 대기 이벤트, 세션당 PGA 메모리 및 SQL 전문 연동 |
| **Lock / Blocking 테이블** | `V$SESSION` 자가조인 | `waiter.blocking_session = blocker.sid` | 대기 세션(Waiter)이 대기 중인 락 이벤트(`EVENT`) 및 블로커 정보 시각화 |
| **슬로우 쿼리 테이블** | `V$SQL` | `ELAPSED_TIME / EXECUTIONS` | 비계정(Not SYS/SYSTEM) 쿼리 중 평균 소요시간이 임계치(`SLOW_QUERY_THRESHOLD_SEC`) 이상인 쿼리 목록 |
| **SQL 상세 페이지** | `V$SQL`<br>`V$SQL_PLAN` | `executions`, `elapsed_time` 등<br>`indented execution plan` | 특정 SQL_ID에 대한 실행 통계(CPU/디스크 I/O) 및 트리 구조로 들여쓰기된 쿼리 실행 계획 |

## 라이선스 관련 주의사항

이 프로젝트는 **Diagnostics/Tuning Pack이 필요 없는 뷰**(`V$SESSION`, `V$SQL`, `V$SQL_PLAN`,
`V$OSSTAT`, `V$SYSMETRIC`, `V$SGAINFO`, `V$PGASTAT`)만 사용합니다.
`V$ACTIVE_SESSION_HISTORY`, `DBA_HIST_*`, AWR 관련 뷰는 라이선스 대상이라 의도적으로 배제했습니다.

## 다음 단계 (로드맵)

- [ ] 임계치 초과 시 알림 (Slack/이메일 webhook)
- [ ] 세션 목록 필터/정렬 (사용자별, 대기이벤트별)
- [ ] 슬로우쿼리 추이 그래프 (SQL_ID별 시간대 elapsed 변화)
- [ ] 접속 정보 다중 DB 지원 (여러 인스턴스 전환 드롭다운)
- [ ] Docker화

## AI 협업 하네스 (Cursor)

이 프로젝트는 `canalframe-harness`(`/Users/jongpillee/ONS/canalframe-harness`)의 거버넌스 패턴을
단일 레포·Python/FastAPI 구조에 맞게 축약 이식한 `.cursor/` 하네스를 포함합니다.

- Coordinator gateway가 `@` 없이도 요청을 분류해 팀(`@aa`/`@backend`/`@dba`/`@frontend`/`@tester`/`@security`)에 자동 위임·실행합니다.
- 시작점: [`.cursor/co.md`](./.cursor/co.md) · 팀 인덱스: [`.cursor/agents/README.md`](./.cursor/agents/README.md) · 규칙: [`.cursor/CONVENTIONS.md`](./.cursor/CONVENTIONS.md)
- Oracle 라이선스 경계(`V$ACTIVE_SESSION_HISTORY`/AWR 금지)와 읽기 전용 원칙이 `@dba`/`@security` 규칙에 always-apply로 박혀 있어, Cursor로 이 코드를 건드릴 때도 자동으로 지켜집니다.
