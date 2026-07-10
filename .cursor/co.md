# @co — Coordinator (조율자 별칭)

Composer에서 **`@co`**로 이 파일을 붙이면 **Coordinator**와 동일.

- **Gateway (alwaysApply)**: [rules/oracledb-monitor-coordinator-gateway.mdc](./rules/oracledb-monitor-coordinator-gateway.mdc) — `@co` 없이도 Coordinator-first
- **Agent**: [agents/coordinator.md](./agents/coordinator.md)
- **Pipeline**: [coordinators/coordinator.md](./coordinators/coordinator.md)
- **Workflows**: [workflows/README.md](./workflows/README.md)
- **Teams**: [agents/README.md](./agents/README.md)
- **Git**: [CONVENTIONS.md](./CONVENTIONS.md) · pull → `feature/*` · `[{이름}]` 커밋 · MR → `main` ([oracledb-monitor-git-workflow.mdc](./rules/oracledb-monitor-git-workflow.mdc))

한 메시지에 `@coordinator @co`처럼 별칭이 여러 번 있어도 **조율은 한 세션·한 계획**으로 맞춘다.

> 이 하네스는 `canalframe-harness`(멀티레포·Java/Gradle·React|Vue)를 단일 레포·Python/FastAPI·서버렌더 UI 프로젝트에 맞게 축약 이식한 버전입니다. 원본: `/Users/jongpillee/ONS/canalframe-harness`.
