# Oracle DB Monitor — 설계 문서

## 1. 요구사항

- 서버(OS) 접속 불가 → 클라이언트에서 DB 리스너로만 접속
- 확인 대상: CPU, 메모리(호스트/인스턴스), 실행 중인 쿼리, Lock, 슬로우 쿼리
- 상용 툴(MaxGauge 등) 미사용, 라이선스 이슈 없는 방식
- 대시보드 + X-log(시계열) + 세부 페이지 구성

## 2. 기술 스택 및 근거

| 레이어 | 선택 | 근거 |
|---|---|---|
| DB 드라이버 | python-oracledb (Thin mode) | Instant Client 불필요, 순수 TCP 접속 |
| 백엔드 | FastAPI | async 지원 → 폴링 + WebSocket push 동시 처리 |
| 스케줄러 | APScheduler | N초 주기 수집, 재시작 시 자동 등록 |
| 저장소 | SQLite | 별도 DB 설치 없이 시계열 히스토리 저장 |
| 프론트 | Jinja2 + Vanilla JS + ECharts(CDN) | Node 빌드체인 없이 `pip install`만으로 실행, 빠른 반복(바이브 코딩)에 적합 |

React/Vite 도입은 화면이 복잡해지고 여러 개발자가 붙을 때 재검토. 현재 백엔드는
REST + WebSocket API로 분리되어 있어 프론트만 교체해도 무방하도록 설계함.

## 3. 상용 툴 벤치마킹

MaxGauge / OEM Performance Hub / Toad for Oracle 공통 패턴:

**개요(Overview) → 목록(List) → 상세(Drill-down)** 의 3단 정보구조.

- 상단: 실시간 게이지/카드 (CPU, Mem, Active Session)
- 중단: 시계열 스트립차트 (X-log)
- 하단: Top N 리스트 (세션, SQL, Lock) → 클릭 시 상세

## 4. 화면 기획 (IA)

1. **대시보드 `/`**
   - 카드: CPU%, Mem Used/Total, Active Sessions, SGA/PGA, Blocking Chains 수
   - X-log 라인차트: CPU% / Active Sessions (WebSocket 실시간 push, 최근 120포인트 롤링)
   - 실행 중인 쿼리 테이블 (요약)
   - Lock 테이블 (요약)
   - 슬로우 쿼리 테이블 (요약)
2. **SQL 상세 `/sql/{sql_id}`**
   - 통계 카드 (Executions, Elapsed, CPU Time, Buffer Gets, Disk Reads)
   - SQL 전문
   - 실행계획 (`V$SQL_PLAN`)

## 5. 데이터 흐름

```
APScheduler (N초 주기)
   └─> queries.py 가 V$ 뷰 조회 (connection pool, Thin mode)
         ├─> SQLite 적재 (X-log, 슬로우쿼리, Lock 이력)
         └─> in-memory LATEST 캐시 갱신
               └─> WebSocket 구독자 전원에게 broadcast
                     └─> 브라우저가 카드/차트/테이블 즉시 갱신
```

REST API(`/api/overview`, `/api/sessions`, `/api/locks`, `/api/slow-queries`, `/api/xlog`)는
WebSocket 미지원 환경이나 새로고침 시 초기 데이터 로딩용으로 병행 제공.

## 6. 필요 권한

```sql
GRANT CREATE SESSION TO monitor_user;
GRANT SELECT_CATALOG_ROLE TO monitor_user;
```

## 7. 라이선스 경계

사용: `V$SESSION`, `V$SQL`, `V$SQL_PLAN`, `V$LOCK`, `V$OSSTAT`, `V$SYSMETRIC`, `V$SGAINFO`, `V$PGASTAT`
(Diagnostics/Tuning Pack 불필요)

미사용(의도적 배제): `V$ACTIVE_SESSION_HISTORY`, `DBA_HIST_*`, AWR 관련 뷰
(Diagnostics Pack 라이선스 대상 — 조회만 해도 라이선스 이슈 발생 가능)

## 8. 실행 로드맵

- **Phase 1 (완료)**: 프로젝트 스캐폴딩 — DB 연결, V$ 쿼리 모듈, SQLite 스토어, 수집기, FastAPI, 대시보드/상세 페이지
- **Phase 2**: 실제 DB 접속 테스트 및 쿼리 검증 (권한 이슈 대응)
- **Phase 3**: 세션/슬로우쿼리 필터·정렬 UI, 슬로우쿼리 추이 그래프
- **Phase 4**: 임계치 알림 (Slack/이메일 webhook)
- **Phase 5**: 다중 DB 인스턴스 지원, Docker화
