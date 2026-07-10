# Workflow: Coordinator → Agent 작업 지시 — PROMPT FORMULA

> Full pipeline에서 Coordinator가 sub-agent(역할)에게 작업을 넘길 때 **본 포맷 권장**.

---

## FORMULA (5요소)

| # | 요소 | Coordinator가 채울 내용 |
|---|------|-------------------------|
| 1 | **역할 (Role)** | `@backend` 등 agent 정의 · `.cursor/agents/teams/...` · scoped rules |
| 2 | **맥락 (Context)** | workflow, manifest, 사용자 요청 요약, 선행 gate 산출(예: `@dba` 쿼리), 경로 |
| 3 | **과제 (Task)** | 구체적 작업 목록 (동사로 시작 · 검증 가능) |
| 4 | **제약 (Constraint)** | MUST read context, MUST NOT, 라이선스 경계, 읽기 전용 원칙, gate 조건 |
| 5 | **형식 (Format)** | 산출물 형태, PASS/FAIL, 말미 `## 요약` |

**마무리 한 줄 (권장)**: `한 단계씩 생각하고 검증한 뒤 실행하세요.`

---

## 표준 템플릿

```markdown
### [@role] 작업 지시

#### 역할 (Role)
당신은 oracledb-monitor **@role** ([agent md 경로])입니다.
적용 rules: [scoped .mdc 목록]

#### 맥락 (Context)
- **Workflow**: [feature | bugfix | harness-tuning]
- **사용자 요청**: [1~2문장]
- **선행 산출**: [@dba 쿼리 초안 / …]
- **대상 경로**: `app/db/…` | `app/templates/…`

#### 과제 (Task)
1. [구체적 작업 1]
2. [구체적 작업 2]
3. [검증: pytest / test_connection.py / 육안 확인]

#### 제약 (Constraint)
- MUST read: [context md paths]
- MUST NOT: V$ACTIVE_SESSION_HISTORY/AWR 사용, DML/DDL 무승인 실행
- Gate: [PASS 조건]

#### 형식 (Format)
- 산출: [파일 목록]
- 역할 섹션: **수행 / 산출 / 결과(PASS|FAIL|N/A)**
- 세션 말미: `## 요약`

한 단계씩 생각하고 검증한 뒤 실행하세요.
```

---

## 역할별 제약 (Constraint) 빠른 참조

| Role | Constraint highlights |
|------|----------------------|
| `@backend` | asyncio.to_thread 래핑 · 커넥션 풀 사용 · Python 3.9 호환(`from __future__ import annotations`) |
| `@dba` | 라이선스 경계(`db.mdc`) · 바인드 변수 · 읽기 전용 |
| `@frontend` | 빌드체인 도입 금지 · 기존 다크테마 토큰 재사용 · `esc()` XSS 이스케이프 |
| `@tester` | 정적 → 동적 순서 · `test_connection.py` 우선 |
| `@security` | 크리덴셜 `.env`만 · SQL Injection 방지 |
| `@aa` | `docs/plan.md`·`.cursor/**`만, 앱 코드 구현 금지 |

Agent index: [agents/README.md](../agents/README.md)

---

## 적용 시점

| 시점 | FORMULA |
|------|---------|
| Full pipeline — 역할 전환 직전 | 템플릿 전체 출력 후 즉시 실행 |
| Fix loop handoff | FAIL 이슈를 **과제**에 명시 · fix owner 역할 재지정 |
| Lightweight | 생략 가능 (직접 답변) |

---

## 연동

- Gateway: [../rules/oracledb-monitor-coordinator-gateway.mdc](../rules/oracledb-monitor-coordinator-gateway.mdc)
- Feedback: [feedback-loop.md](./feedback-loop.md)
