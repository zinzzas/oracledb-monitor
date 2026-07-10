# Workflow: 하네스 자체 수정

**담당**: `@aa`

## Teams (순서)

1. **@aa** — 변경 범위 분석 (`.mdc`/`agents`/`workflows`/manifest 중 어디)
2. **@aa** — 수정 반영, 관련 인덱스(`agents/README.md`, `workflows/README.md`) 동기화
3. **@co** — worklog 기록

## Rules

- `.cursor/**`, `docs/**`만 다룬다. 앱 코드(`app/**`)는 이 workflow에서 건드리지 않는다.
- 원본 하네스(`/Users/jongpillee/ONS/canalframe-harness`)와의 괴리가 커지면, 이 프로젝트가 실제로 멀티레포/FE 프레임워크로 성장했는지 먼저 확인 후 재이식 여부 판단.
