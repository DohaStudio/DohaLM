# EOS Success Policy

- 문서 상태: `approved`
- 정책 상태: `approved`
- 승인일: 2026-07-28
- 적용 범위: 향후 Base·Instruct·Chat 모델 단계별 EOS 평가
- historical 결과 소급 적용: `forbidden`
- 관련 ADR: [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md)

## Common

[확정] Teacher-forced EOS와 autoregressive generation EOS는 서로 다른 능력을 측정하며 합성 점수로
합치지 않는다. artifact identity, prompt/config fingerprint, 개인정보 비저장, 수치 안정성과 평가 재현성을
모두 검증한다.

- Teacher-forced: target count·ratio, Top-1/5/10, mean loss, median/p90 rank, masking·packing·label shift
- Generation: EOS/maximum-length rate, mean termination step, repetition, distinct-n, degenerate loop, category
- Pure model: 보정 없는 greedy
- Decoding-assisted: sampling, repetition penalty, no-repeat n-gram 등 승인된 profile
- Forced EOS·logit bias·외부 stop heuristic: 모델 자체 EOS 성공에서 제외

[확정] 공식 generation 진단 길이는 16/32/64/128 token이다. 완결형·미완결형·질문형·대화형·설명형·
목록형·code-like·SQL-like·domain-like·장문 context·반복 유도·명시적 종료 유도 category를 분리 보고하고
하나의 평균으로만 판정하지 않는다. 현재 synthetic prompt 진단은 실제 사용 분포를 대표하지 않는다는
한계를 함께 기록한다.

## Base

```text
Base pure greedy EOS:
diagnostic_required
not_sufficient_as_single_failure_condition
```

[확정] Full loss·PPL·Top-k, token category·position, teacher-forced EOS, stability, lineage, privacy와 checkpoint
integrity는 필수다. Pure greedy EOS와 maximum-length는 필수 진단이지만 greedy EOS 0%만으로 Base 전체를
자동 실패 처리하지 않는다. 심각한 반복·무한 loop·일반 성능 붕괴는 별도 blocker다.

## Instruct

```text
instruct_eos_contract: approved_policy_framework
numeric_thresholds: proposed
training: not_approved
```

[확정] instruction completion, format compliance, 응답 종료, maximum-length, 반복, empty response,
special-token exposure, 과도한 장문과 구조 출력 완결성을 필수 항목으로 정의한다. 실제 benchmark와 데이터가
승인되기 전에는 수치 임계값과 학습을 승인하지 않는다.

## Chat

```text
chat_eos_contract: approved_policy_framework
numeric_thresholds: proposed
training: not_approved
```

[확정] 응답·멀티턴 종료, 반복, 중간 중단, 과도한 장문, stop sequence 중복과 안전 거절 완결성을 평가한다.
Pure greedy는 모델 baseline이며 실제 서비스 decoding과 stop 조건은 별도 정책으로 관리한다.

## Service decoding

```text
service_decoding_policy: proposed
implementation: not_started
```

Temperature, top-p/top-k, repetition penalty, no-repeat n-gram, stop sequence, 문장 경계와 forced EOS는
별도 승인 대상이다. 보조 종료를 pure model EOS 성공으로 간주하지 않는다.

## Historical 적용 경계

[확정] Candidate A Final Full은 공식 Base baseline이다. Candidate B는 당시 승인된 계약에서
`evaluated_contract_not_passed`이며 `decoding_assisted_termination_only`로 진단됐다. 이 정책은 그 판정을
소급 변경하지 않는다. Candidate B 재평가는 `awaiting_separate_approval`, derivative parent eligibility는
`proposed`, publication·Instruct·Chat training은 `not_approved`다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | ADR-008 승인에 따라 Common·Base·Instruct·Chat 계약과 historical 비소급 원칙 확정 |
