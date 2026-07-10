# Agents — 팀·Sub-agent 인덱스

Coordinator(`.cursor/agents/coordinator.md`)가 모든 요청을 분류한 뒤 아래 팀 agent에 위임합니다.

**Manifest**: `.cursor/project.manifest.json` — `backendStack`=`python-fastapi`, `uiStack`=`jinja2-htmx-echarts` 고정 (프로젝트당 스택 1종, 선택 로직 없음).

> `canalframe-harness`의 `agents/README.md` 축약 이식판. `planner/architect/aa` → **`@aa`** 하나로 통합, `fe-react/fe-vue` → **`@frontend`**, `be-core/be-service` → **`@backend`**. reviewer 서브롤은 팀 인원이 적어 생략 — `@tester`가 리뷰 관점도 겸함.

---

## Coordinator

| @멘션 | 파일 |
|-------|------|
| `@co` `@coordinator` `@coco` | [coordinator.md](./coordinator.md) · [../co.md](../co.md) |

---

## 기획·설계·거버넌스

| @멘션 | 파일 | 한 줄 |
|-------|------|--------|
| `@aa` | [teams/aa.md](./teams/aa.md) | 요구사항·설계·하네스/가이드 현행화 (통합 롤) |

---

## Backend

| @멘션 | 파일 | 경로 힌트 |
|-------|------|-----------|
| `@backend` | [teams/backend.md](./teams/backend.md) | `app/main.py`, `app/config.py`, `app/collectors/**` |

## DB

| @멘션 | 파일 | 경로 힌트 |
|-------|------|-----------|
| `@dba` | [teams/dba.md](./teams/dba.md) | `app/db/**`, `app/storage/**` — V$ 쿼리·라이선스 경계 |

## Frontend

| @멘션 | 파일 | 경로 힌트 |
|-------|------|-----------|
| `@frontend` | [teams/frontend.md](./teams/frontend.md) | `app/templates/**`, `app/static/**` |

## Tester

| @멘션 | 파일 | 담당 |
|-------|------|------|
| `@tester` | [teams/tester.md](./teams/tester.md) | pytest, 접속 스모크 테스트, 리뷰 관점 겸임 |

## Security

| @멘션 | 파일 |
|-------|------|
| `@security` | [teams/security.md](./teams/security.md) |

---

## Workflows

Coordinator가 선택: [../workflows/README.md](../workflows/README.md)

## Scoped rules (`.mdc`)

Path 편집 시 **자동 주입** — agent @ 없이도 MUST 적용.

| Team | Rule |
|------|------|
| Backend | [backend.mdc](../rules/backend.mdc) |
| DBA | [db.mdc](../rules/db.mdc) |
| Frontend | [frontend.mdc](../rules/frontend.mdc) |
| Tester | [testing.mdc](../rules/testing.mdc) |
| Always | [oracledb-monitor-coordinator-gateway.mdc](../rules/oracledb-monitor-coordinator-gateway.mdc), [oracledb-monitor-git-workflow.mdc](../rules/oracledb-monitor-git-workflow.mdc), [oracledb-monitor-project-core.mdc](../rules/oracledb-monitor-project-core.mdc), [security.mdc](../rules/security.mdc) |

## Template

신규 agent 추가 시 `teams/*.md`를 참고해 동일 포맷(Context/Rules/Workflow/Output)으로 작성.
