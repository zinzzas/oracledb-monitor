# Oracle DB Monitor

서버 접속 없이 **클라이언트에서 리스너로 접속**해 Oracle의 CPU/메모리/실행 중 쿼리/Lock/슬로우쿼리를
실시간으로 모니터링하는 경량 대시보드. python-oracledb Thin mode 사용 (Oracle Instant Client 불필요).

## 빠른 시작

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일을 열어 ORACLE_USER / ORACLE_PASSWORD / ORACLE_DSN 채우기

uvicorn app.main:app --reload --port 8000
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

## 화면 구성

1. **대시보드** — CPU/Mem/Active Session/SGA·PGA 카드 + 실시간 X-log(CPU%, 세션수 시계열) 라인차트
2. **실행 중인 쿼리** — SID/USER/EVENT/ELAPSED/BLOCKED BY/SQL_ID 테이블, SQL_ID 클릭 시 상세로 이동
3. **Lock/Blocking** — `V$SESSION.BLOCKING_SESSION` 기반 블로킹 체인
4. **슬로우 쿼리** — `.env`의 `SLOW_QUERY_THRESHOLD_SEC` 이상인 평균 elapsed 쿼리
5. **SQL 상세 페이지** (`/sql/{sql_id}`) — SQL 전문, 실행계획, 통계

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
