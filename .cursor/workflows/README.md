# Workflows — Coordinator 라우팅

Coordinator(`.cursor/rules/oracledb-monitor-coordinator-gateway.mdc`)가 요청 유형에 따라 아래 workflow를 선택합니다.

| Workflow | 트리거 키워드 |
|----------|---------------|
| [feature.md](./feature.md) | 새 지표, 새 페이지, 기능 추가 |
| [bugfix.md](./bugfix.md) | 버그, fix, 장애 |
| [harness-tuning.md](./harness-tuning.md) | 하네스, `.cursor/`, 컨벤션 수정 |

> `canalframe-harness`의 Type A~D 세분화(풀스택/BE/FE/컴포넌트)를 단일 레포 규모에 맞게 **feature.md 하나**로 축약. FE/BE가 물리적으로 분리되어 있지 않아 조합별 workflow가 불필요.

**공통 규칙**: [feedback-loop.md](./feedback-loop.md) — @ 없이 Coordinator 실행, 병렬, Fix-until-PASS.

**Agent 작업 지시**: [prompt-formula.md](./prompt-formula.md) — **역할·맥락·과제·제약·형식**.

**병렬**: 쿼리/응답 스키마 확정 후 `[병렬]` backend/frontend · tester 정적 → 동적.
