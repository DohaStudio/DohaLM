# Full Pretraining 초기화·Resume 정책

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 관련 문서: [실행 계획](./full-pretraining-execution-plan.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md)

## 초기화

- [확정] DohaLM-Tiny를 seed 17로 새로 초기화한다.
- [확정] Pilot checkpoint는 검증 evidence로만 보존하며 승격하거나 resume하지 않는다.
- [확정] Pilot token은 Candidate A 10M token budget에 포함하지 않는다.
- [확정] initialization fingerprint는 `sha256:c580d1786efc2aa85ebb4c9ada4cf28ac280b3367beeee69cd263dc25b7a3356`이다.

## Full Run 내부 Resume

Resume는 같은 Run ID의 checksum-valid Full checkpoint에서만 가능하며 별도 사용자 승인이 필요하다. Dataset·source lineage·PII·split·tokenization·packing·tokenizer·model·initialization·config fingerprint, token/step budget, optimizer·scheduler·AMP scaler·RNG·sampler 상태가 모두 일치해야 한다.

Pilot checkpoint, 다른 Full run, 변경된 seed·LR·warmup·scheduler·batch·context·budget·Dataset·Tokenizer·Model 또는 checksum 불일치는 차단한다. 자동 resume와 자동 retry는 허용하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] fresh seed-17과 Full Run 내부 별도 승인 Resume 정책 승인 |
