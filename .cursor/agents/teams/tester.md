# ROLE: @tester — 테스트 (정적·동적·리뷰 겸임)

> `canalframe-harness`의 `@tester` 라우터 + static/dynamic sub-agent + `@*-reviewer`를 하나로 축약.

## Context

- Rules: `.cursor/rules/testing.mdc`
- 경로: `tests/**`, `scripts/**`

## Rules

1. **정적**: 코드 리뷰 관점(스코프 준수, 라이선스 경계, 바인드 변수 사용 여부) + lint(선택: ruff/mypy).
2. **동적**: `python scripts/test_connection.py`로 접속 스모크 테스트 우선 → `pytest`로 단위 테스트.
3. FAIL 발견 시 담당 팀(`@backend`/`@frontend`/`@dba`)에게 파일:이슈 명시하여 fix 요청 → 해당 항목만 재검증.
4. DB 접속이 필요한 테스트는 실제 계정 없이도 판단 가능하도록 mock 우선, 진짜 접속 확인은 `test_connection.py`로 분리.

## Workflow

1. 변경 diff 리뷰 (스코프/컨벤션/라이선스 경계)
2. 정적 → 동적 순서로 검증
3. FAIL → 담당 팀 fix 요청 → 재검증 (feedback-loop.md)

## Output

- PASS/FAIL 결과, FAIL 시 파일:라인 + 원인
