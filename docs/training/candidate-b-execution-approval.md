# Candidate B 실행 승인 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 승인 상태: `pending`
- 관련 schema: [Approval schema](./candidate-b-approval.schema.yaml)
- 공개 example: [Approval example](../../configs/candidate-b-approval.example.yaml)

## Manifest 계약

승인은 Candidate B run ID, action, 25M/12,208-step budget, resolved config와 Dataset·split·packing·tokenizer·model·initialization fingerprint, immutable Git commit/upstream/repository identity, 외부 output logical root를 정확히 묶는다. `candidate_b_execution`, single-use, unconsumed, no publication/resume/retry/extension만 유효하다.

승인 manifest가 없거나 `approved`가 아니거나 fingerprint·run·commit·budget이 다르거나 만료·소비된 경우 실행을 차단한다. Example은 의도적으로 `pending`, commit `null`이며 실제 승인이 아니다.

## 소비 순서

1. Static·Git·output·physical preflight 완료
2. Dataset loader와 model·optimizer·scheduler 초기화
3. 첫 batch forward/backward 및 finite gradient 검증
4. optimizer step 1 직전 별도 외부 consumption record를 atomic publish
5. 소비 성공 후에만 optimizer step 1 수행

소비 record는 approval 원본을 수정하지 않는다. 소비 실패 시 Trainer state는 step 0, checkpoint는 0개이며 staging은 제거하고 text-free failure manifest만 남긴다. 소비 후 실패한 승인은 복원·재사용하지 않고 Resume/retry는 별도 승인 없이는 금지한다.

CPU test는 `synthetic_test_fixture`와 `SYNTHETIC-TEST-` run ID만 소비할 수 있다. 실제 approval을 fixture mode로 소비하는 호출은 차단한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate B immutable single-use 승인 schema와 optimizer step 1 직전 atomic 소비 계약 구현 |
