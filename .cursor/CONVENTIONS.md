# oracledb-monitor 워크스페이스 — 공통 규칙 (모든 에이전트)

> Git·Coordinator 게이트웨이·팀 협업을 한 파일로 모읍니다.
> **팀 agent**: [agents/README.md](./agents/README.md) · **조율**: [coordinators/coordinator.md](./coordinators/coordinator.md) · **Workflow**: [workflows/README.md](./workflows/README.md)
>
> 이 문서는 `canalframe-harness`의 CONVENTIONS.md를 **단일 레포·Python/FastAPI 프로젝트**에 맞게 축약한 버전입니다. 멀티레포 매핑 표·Java/Gradle 관련 항목은 이 프로젝트에 해당하지 않아 제외했습니다.

---

## 프로젝트 Manifest

`.cursor/project.manifest.json`:

| 필드 | 설명 |
|------|------|
| `backendStack` | `python-fastapi` 고정 |
| `uiStack` | `jinja2-htmx-echarts` — 별도 빌드체인 없음 |
| `dbTarget` | `oracle-19c-client-only` — 서버 접속 불가, 클라이언트(python-oracledb Thin)로만 접속 |
| `activeTeams` | Coordinator가 할당 가능한 팀 |
| `git` | `baseBranch`/`mrTargetBranch`(기본 `main`), `authorName`, `featureBranchPrefix` |

Coordinator gateway(`rules/oracledb-monitor-coordinator-gateway.mdc`)가 **모든 세션**에서 manifest를 따릅니다.

## 프로젝트

- **정식명**: Oracle DB Monitor — 서버 접속 없이 클라이언트에서 리스너로 접속해 CPU/Mem/실행쿼리/Lock/슬로우쿼리를 모니터링하는 FastAPI 대시보드
- **레포**: **단일 레포** (`canalframe-harness`와 달리 `apps/` 분리 없음) — `.cursor/`, `docs/`, `app/`, `scripts/`, `tests/` 전부 이 레포 하나에 커밋
- **구조**: [docs/plan.md](../docs/plan.md), [README.md](../README.md) 참고

---

## Git — 브랜치·커밋·MR (필수)

> Always rule: [rules/oracledb-monitor-git-workflow.mdc](./rules/oracledb-monitor-git-workflow.mdc)
> Manifest: `project.manifest.json` → `git` (baseBranch, mrTargetBranch, authorName)

### 작업 시작 (Git 관련 세션 — Coordinator **@co** 담당)

1. `git fetch origin`
2. `git checkout main` (manifest `git.baseBranch`)
3. `git pull origin main`
4. `git checkout -b feature/<slug>` (manifest `git.featureBranchPrefix`)

`main`에 직접 커밋하지 않음 (오너가 hotfix로 base 브랜치 지정한 경우만 예외).

### 커밋 메시지

- 포맷: **`[{작업자이름}] 작업내용`**
- `{작업자이름}`: manifest `git.authorName` → 없으면 `git config user.name` → 없으면 세션당 1회 오너 확인
- **`git commit -m "…"`만 사용** — `--trailer` 등 금지

### Merge Request (MR)

- **머지 대상**: `main` (manifest `git.mrTargetBranch`)
- push / MR 생성은 **오너 명시 요청 시에만**

---

## 오너(@co 사용자) 작업 패턴 — 실행 페르소나 공통

1. **직접 실행**: 터미널·도구로 조사·실행하고, 사용자에게만 시키기로 끝내지 않음.
2. **맥락 연속**: 후속 메시지는 같은 작업의 연장·수정으로 해석.
3. **범위 준수**: 요청 밖 드라이브바이 리팩터·무관 파일 수정 금지.
4. **DB / 운영 데이터**: **DML/DDL·세션 kill·GRANT 실행 전 사용자 명시 승인.** `@dba`는 조회·SQL 초안까지, 실행은 승인 후. (이 프로젝트는 원칙적으로 **읽기 전용(V$ SELECT)만** 수행 — 쓰기 작업은 스코프 밖)
5. **조율 vs 구현**: Coordinator gateway가 모든 요청을 1차 수신. Full pipeline 시 역할 분리 서술; 구현은 `@backend`/`@frontend`에 위임; 검증은 `@tester`.
6. **소통·협업**: 할당 시 선행·후행 역할, 맞출 산출물(API 응답 스키마, 쿼리 결과 컬럼, 테스트 전제)을 문장으로 남긴다.

---

## 오라클 라이선스 경계 (이 프로젝트 고유 — 필수)

> 상세: [rules/db.mdc](./rules/db.mdc)

- **사용 가능**: `V$SESSION`, `V$SQL`, `V$SQL_PLAN`, `V$LOCK`, `V$OSSTAT`, `V$SYSMETRIC`, `V$SGAINFO`, `V$PGASTAT` 등 Diagnostics/Tuning Pack **불필요** 뷰
- **사용 금지**: `V$ACTIVE_SESSION_HISTORY`, `DBA_HIST_*`, AWR 관련 뷰 — 조회만 해도 라이선스 이슈 발생 가능
- `@dba`, `@backend`가 새 쿼리 추가 시 **반드시 이 경계를 먼저 확인**

---

## 페르소나·팀 agent·`.mdc` 간 소통·협업

- **Role `.mdc`**: `app/**/*.py` 편집 시 `backend.mdc`, `app/db/**` 편집 시 `db.mdc` 등 **자동 주입** — @mention 없이 MUST
- **Coordinator gateway**: `@` 없이 workflow·팀 자동 지시·실행 ([feedback-loop.md](./workflows/feedback-loop.md))
- **병렬**: API/쿼리 스키마 확정 후 backend/frontend, `@tester` static → dynamic
- **피드백 루프**: review/qa/test FAIL → 담당 dev 즉시 fix → 해당 gate만 재실행 until PASS

---

## 경로 → 팀 agent (요약)

| 경로 | 팀 agent |
|------|----------|
| `app/db/**`, `app/storage/**` | `@dba` (쿼리·스키마) → `@backend` (구현) |
| `app/collectors/**`, `app/main.py`, `app/config.py` | `@backend` |
| `app/templates/**`, `app/static/**` | `@frontend` |
| `scripts/**`, `tests/**` | `@tester` |
| `.env*`, 인증·크리덴셜 관련 | `@security` |
| `.cursor/**`, `docs/**` | `@aa` |

---

## 테스트 피라미드 (축약)

상세 workflow: [workflows/testing.md](./workflows/testing.md)

| 단계 | 내용 | 주 담당 | 도구 |
|------|------|---------|------|
| **1. 정적** | lint · type check · V$ 라이선스 경계 검토 | `@tester` | `ruff`, `mypy` (선택) |
| **2. 동적** | 단위 테스트 · DB 접속 스모크 테스트 | `@tester` | `pytest`, `scripts/test_connection.py` |
| **3. 수동 확인** | 대시보드 렌더/실시간 갱신 육안 확인 | `@tester`, `@qa` 겸 오너 | 브라우저 (Playwright 미도입, 향후 옵션) |

`canalframe-harness`의 SonarQube/Gradle/JUnit/Playwright는 이 프로젝트 스택에 해당 도구가 없어 제외. 규모가 커지면 `@aa`가 재검토.

---

## 요청 유형별 파이프라인 (요약)

1. **새 지표/페이지 추가**: `@dba`(쿼리 설계, 라이선스 경계 확인) → `@backend`(API/수집기) → `@frontend`(템플릿/차트) → `@tester` → 필요 시 `@security`.
2. **버그 수정**: 원인 분석 → 조치 설계 → 조치 → `@tester` 재검증.
3. **하네스 자체 수정**: `@aa`.

상세 조율: [coordinators/coordinator.md](./coordinators/coordinator.md) · Workflow: [workflows/README.md](./workflows/README.md)
