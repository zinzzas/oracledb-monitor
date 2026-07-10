# ROLE: @frontend — Jinja2 / 순정 JS / ECharts

## Context

- Rules: `.cursor/rules/frontend.mdc`
- 경로: `app/templates/**`, `app/static/**`

## Rules

1. React/Vue/npm 빌드체인 도입 금지 (재검토 필요 시 `@aa` 상의). CDN 라이브러리만 추가.
2. 기존 다크테마 CSS 변수(`--bg`, `--panel`, `--border`, `--text`, `--muted`, `--ok`, `--warn`, `--crit`, `--accent`) 재사용.
3. 실시간 데이터는 WebSocket(`/ws/live`) 우선, REST는 초기 로딩/fallback 용도로만.
4. 사용자 제어 불가지만 임의 문자열(SQL 텍스트 등)을 DOM에 꽂을 땐 `esc()` 헬퍼로 이스케이프 (XSS 방지).

## Workflow

1. `@backend`가 제공하는 API/WebSocket 스키마 확인
2. 템플릿/JS 구현 (기존 카드·테이블·차트 패턴 재사용)
3. `@tester`에 수동 확인 요청 (렌더/실시간 갱신 육안 체크)

## Output

- `.html` 템플릿, `static/` 자산 diff
