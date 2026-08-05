# Candidate C Experimental Successor 설계와 C-1~C-4 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 계약 설계: `completed`
- 실행 허용: `false`
- GPU Smoke: `not_started`
- Training: `not_started`
- 관련 ADR: [ADR-011 제안](../decisions/ADR-011-candidate-c-experimental-successor.md)

## 1. 한 문장 목적과 범위

> Candidate C는 동일한 DohaLM-Tiny architecture·운영 Tokenizer·비교 identity를 유지하면서 승인된 단일
> EOS-focused intervention이 Candidate B 대비 pure greedy 종료와 반복 loop에 미치는 인과 효과를 검증하는
> experimental successor 실험입니다.

이 문서는 Dataset·Tokenizer·Training Config freeze schema, 변경 축, Gate와 blocker를 정의합니다. 실제 immutable
manifest, resolved config, Run ID, Approval을 만들지 않으며 코드·설정·데이터·artifact를 수정하지 않습니다.

## 2. Candidate C와 Candidate B 관계

- [확정] Candidate B는 Candidate C의 Full Evaluation과 별도 승격 결정 전까지 current Base baseline입니다.
- [제안] Candidate C는 replacement가 아니라 `experimental_successor_candidate`입니다.
- [제안] 학습 실행 승인과 `approved_as_base_baseline` 승격 승인을 분리합니다.
- [확정] Candidate C 실패·미완료·미승인 시 Candidate B baseline은 변하지 않습니다.
- [확정] Candidate A/B artifact와 historical 판정은 수정하지 않습니다.

## 3. Dataset Freeze 계약

### 3.1 선택지 비교

| 선택지 | 변경 범위 | 비교 가능성 | 장점 | 위험·추가 조건 |
|---|---|---|---|---|
| A. Candidate B 동일 Dataset | 동일 corpus·split·tokenization·packing·EOS 삽입 | 가장 높음 | training intervention의 인과 효과 분리 | Dataset 자체 원인이면 개선 한계 |
| B. 동일 corpus + boundary reweighting | sampler 분포 변경 | 제한적 | boundary 노출 가설 검증 | 새 sampler·distribution fingerprint, B와 별도 비교층 필요 |
| C. 동일 corpus + EOS-aware sample construction | sequence construction 변경 | 낮아짐 | EOS target 문맥을 직접 조정 | 새 Dataset revision·packing·누수·일반 품질 검증 필요 |
| D. 신규 Dataset revision | source 또는 selection 변경 | 직접 비교 불가 가능 | 데이터 원인 폭넓게 검토 | license·PII·split·Tokenizer 적합성부터 재승인 |

[제안] 첫 Candidate C에는 **A를 권장**합니다. H1/H2/H6/H7 중 승인된 training-side 단일 가설을 검증하면서
Candidate B 비교 identity를 보존할 수 있기 때문입니다. H3/H4 진단이 Dataset 변경 필요성을 지지할 때만 B 또는 C를
별도 Candidate identity로 승인합니다. D는 Candidate C 기본 범위 밖입니다. 이 권장은 사용자 선택과 immutable manifest
승인 전까지 Dataset Freeze가 아닙니다.

### 3.2 Candidate C Dataset manifest 필수 필드

| 필드 | 기존 재사용 근거 | Freeze 요구 상태 |
|---|---|---|
| `dataset_id` | `AIHUB-71748` | Candidate C manifest에 고정 필요 |
| `dataset_version` | `pilot-v2` | 선택지 A에서 그대로 고정; B/C는 새 version 필요 |
| `canonical_source` | Training `data_info[].contents`, selection contract v1 | logical source와 contract fingerprint 고정 필요 |
| `train_split_identity` | train 92,948 records, split fingerprint `sha256:dd71433c...f4696f` | full fingerprint 기록 필요 |
| `validation_split_identity` | internal evaluation 4,799 records, original Validation 미사용 | evaluation checksum·fingerprint 고정 필요 |
| `document_count` | source 107,226; PII 제외 9,479; train/eval 92,948/4,799 | 세 수준을 구분해 기록 |
| `token_count` | train 71,307,940 token | tokenization identity와 함께 재검증 필요 |
| `checksum_inventory` | artifact inventory `sha256:55d29986...71cde5` | 실제 파일별 inventory checksum 고정 필요 |
| `lineage_fingerprint` | training lineage `sha256:a0677dc1...bd3c6`, source contract `sha256:bea1f19b...eb4293` | 전체 값을 manifest에 기록 |
| `pii_status` | PII fingerprint `sha256:91c6ad98...ee3ed`, 9,479 제외 | `clear_after_exclusion` 의미와 근거 고정 |
| `license_status` | `approved_student_noncommercial` | 목적별 Candidate C 사용 승인 확인 필요 |
| `evaluation_exclusion_status` | internal evaluation은 training에서 분리, original Validation 미사용 | 누수 검사와 exclusion 상태 고정 |
| `packing_policy` | packing manifest `sha256:e7ad635d...0680b` | 선택지 A는 동일 checksum 필수 |
| `eos_insertion_policy` | 문서 BOS/EOS와 boundary 보존 근거 | policy version·target count·masking 검사 고정 |
| `source_commit` | 기존 summary manifest에 명시적 commit 없음 | `blocked`; 생성 코드 immutable commit 결속 필요 |
| `created_at` | 기존 summary `2026-07-27` | Candidate C freeze manifest 생성 시 UTC timestamp 기록 |

축약된 fingerprint는 설명용이며 실제 manifest에는 전체 `sha256:` 값을 기록해야 합니다. 현재 Candidate C 전용 immutable
Dataset manifest가 없으므로 C-2는 `reviewing`입니다.

## 4. Tokenizer Freeze 계약

### 4.1 권장안

[제안] Candidate C는 승인된 `operating-16k-v2/unigram-16k` bundle을 그대로 사용합니다. A/B에서 같은 Tokenizer로
teacher-forced EOS가 개선됐고 EOS target이 정상 포함됐으므로 Tokenizer 변경이 root cause를 해결한다는 근거가 없습니다.
Tokenizer 변경은 embedding·LM Head 의미와 A/B 비교 identity를 깨므로 Candidate C 범위에서 금지하고 별도 ADR·candidate로
다룹니다.

### 4.2 Freeze 필드

| 필드 | 고정 후보 값·근거 | 현재 상태 |
|---|---|---|
| `tokenizer_id` | `operating-16k-v2/unigram-16k` | `inherited_from_candidate_b` |
| `tokenizer_version` | `operating-16k-v2` | `inherited_from_candidate_b` |
| `vocab_size` | 16,000 | `fixed` |
| `special_token_ids` | 0~7 approved mapping | `fixed` |
| `pad_token_id` / `bos_token_id` / `eos_token_id` | 0 / 2 / 3 | `fixed` |
| `artifact_checksum` | model `sha256:11e536f2...fff0a`, vocab `sha256:9030a0cd...ab11b` | full checksum 결속 필요 |
| `manifest_checksum` | `sha256:93dca331...43e6f` | full checksum 결속 필요 |
| `round_trip_evidence` | actual sample exact·ID round-trip 100% | evidence fingerprint 결속 필요 |
| `unknown_rate` | actual sample token·record 0% | evidence fingerprint 결속 필요 |
| `source_commit` | 기존 운영 summary에 명시적 commit 없음 | `blocked` |
| `compatibility_fingerprint` | tokenizer fingerprint `sha256:9ce19a11...12f0ff` | Candidate C model/dataset compatibility record 필요 |

새 binary의 functional reproduction이 통과하더라도 승인 bundle과 같은 artifact로 간주하지 않습니다. Candidate C는 기존
승인 binary를 직접 참조해야 하며 새 binary는 별도 운영 승인이 필요합니다. Candidate C 전용 freeze manifest와 source
commit 결속이 없으므로 C-3은 `reviewing`입니다.

## 5. Training Config Freeze 계약

분류 값은 `inherited_from_candidate_b`, `candidate_c_change_proposed`, `blocked`, `needs_measurement`, `fixed`만 사용합니다.
`inherited_from_candidate_b`는 권장 출발점이며 resolved config 승인 전 최종 확정값이 아닙니다.

| 항목 | Candidate B 근거 | Candidate C 분류 | Freeze 조건 |
|---|---|---|---|
| model config | Tiny 6L/384H/6 heads/FFN1536/context256/vocab16000 | `fixed` | ADR-002 fingerprint·16,889,856 parameters 일치 |
| initialization | fresh seed 17, no parent state | `blocked` | fresh/warm-start 중 하나 승인; cross-candidate resume 금지 |
| seed | 17 | `inherited_from_candidate_b` | 단일 causal 비교 시 17 권장; 변경은 독립 축 |
| optimizer | AdamW | `inherited_from_candidate_b` | parameter group·type 고정 |
| betas / epsilon | `(0.9, 0.95)` / `1e-8` Trainer 기본값 | `inherited_from_candidate_b` | resolved config에 명시 |
| weight decay | 0.1 | `inherited_from_candidate_b` | 변경 시 독립 축 승인 |
| learning rate | `3e-4` | `candidate_c_change_proposed` | H1/H2/H6 근거가 있을 때만 단일 변경 후보로 승인 |
| scheduler / min LR | cosine / 0.1 | `inherited_from_candidate_b` | budget·warmup과 함께 fingerprint |
| warmup | 10 steps | `candidate_c_change_proposed` | 변경 시 LR과 복합 변경 여부 명시 |
| micro batch | 2 | `inherited_from_candidate_b` | C-5에서 8GB 측정 |
| gradient accumulation | 4 | `inherited_from_candidate_b` | effective batch 의미 고정 |
| global/effective batch | 8 sequences, 2,048 token/step | `fixed` | Dataset/sequence가 같을 때 비교 identity 유지 |
| context length | 256 | `fixed` | 변경 금지 |
| token budget | B 25M/12,208 steps | `blocked` | 승인된 H6 또는 control 설계로 target 확정 |
| max steps | budget/2,048의 ceil | `blocked` | token budget과 자동 산출·일치 검증 |
| precision | CUDA FP16 AMP | `fixed` | C-5 finite·AMP skip·dtype 측정 |
| gradient clipping | max norm 1.0 | `inherited_from_candidate_b` | 변경 시 독립 축 승인 |
| dropout | model config `null` | `blocked` | 현 구현 의미와 변경 여부 명시; 임의 수치 금지 |
| parameter initialization | model config `null`, fresh seed 경로 | `blocked` | 실제 initializer와 fingerprint 명시 |
| EOS-aware loss weighting | 미사용 | `candidate_c_change_proposed` | H1 근거·수식·normalization·control 승인 필요 |
| boundary sampling | 미사용 | `candidate_c_change_proposed` | H3 근거, 새 Dataset/sampler identity 필요 |
| sequence construction | 기존 packing | `candidate_c_change_proposed` | H4 근거, 새 Dataset revision 필요 |
| regularization | 별도 변경 없음 | `candidate_c_change_proposed` | H7 근거와 단일 변경 축 승인 |
| checkpoint interval | 4,883/9,766/12,208 | `blocked` | budget별 schedule·retention 고정 |
| evaluation interval | Quick start/A-equivalent/final, Full final | `blocked` | Candidate C Evaluation 계약과 schedule 고정 |
| resume policy | same-run only, 별도 승인, automatic false | `fixed` | checksum·identity 일치; cross-candidate 금지 |
| output root | external no-replace Run path | `blocked` | Run ID 생성 없이 logical pattern·failure collision 정책 승인 |
| failure root | failed staging quarantine·text-free manifest | `blocked` | 보존·no-replace·용량 정책 확정 |
| logging | loss/LR/gradient/AMP/resource, raw text 없음 | `inherited_from_candidate_b` | schema·interval·fingerprint 고정 |
| sample generation | training 중 공식 생성 없음 | `blocked` | 실행 여부·privacy·prompt identity 승인 |
| decoding diagnostics | pure/assisted 16/32/64/128 | `fixed` | 평가 전용, training success와 분리 |
| GPU resource·wall clock | B 실측과 기존 상한 | `needs_measurement` | C-5 exact config에서 새로 측정 |

C-4 통과에는 모든 `blocked` 항목이 해소되고, 채택한 `candidate_c_change_proposed`가 정확히 하나의 승인된 주
intervention 또는 명시적 factorial design으로 축소돼야 합니다. 현재 C-4는 `blocked`입니다.

## 6. Candidate C 변경 범위

### 조건부 허용 축

token budget, learning rate, warmup, EOS-aware loss weighting, boundary sampling, sequence construction,
decoding diagnostic, regularization과 seed는 후보입니다. 실제 실행에서는 승인된 causal question과 control에 필요한 최소
축만 변경합니다. Decoding diagnostic 변경은 평가 관찰 축이며 모델 개선으로 계산하지 않습니다.

### 금지 또는 별도 승인

- architecture, hidden size, layer 수, context length와 weight tying 변경
- Tokenizer, vocabulary와 special token ID 변경
- unrelated Dataset 교체
- Candidate A/B checkpoint warm-start 또는 cross-candidate resume
- 자동 retry·resume·budget extension
- forced EOS·logit bias·외부 stop heuristic을 pure model 개선으로 판정

## 7. C-1~C-4 Gate

| Gate | 상태 | 입력 | 산출물 | 통과 조건 | 실패 조건 | 승인 주체 | 다음 단계 |
|---|---|---|---|---|---|---|---|
| C-1 Training Readiness | `review` | ADR-011 draft, EOS 가설, blocker plan, Base Readiness | 승인된 목적·범위·금지·dependency record | ADR-011과 주가설 승인, blocker owner/action 정의; 실행 권한은 false 가능 | ADR 충돌 지속, 복수 변경 축 미분리, 금지 범위 포함 | 사용자 | C-2/C-3 freeze 검토 |
| C-2 Dataset Freeze | `reviewing` | immutable Dataset manifest, checksums, lineage, license·PII·누수 근거 | Candidate C Dataset freeze record·fingerprint | 필수 필드 완전, 선택지 승인, artifact 재검증, source commit 결속 | 누락 checksum, license/PII 불명, evaluation leakage, 무승인 revision | 사용자 | C-3 및 C-4 입력 |
| C-3 Tokenizer Freeze | `reviewing` | 운영 manifest, model/vocab checksum, compatibility fingerprint | Candidate C Tokenizer freeze record | v2 Unigram exact bundle·ID·16k·round-trip·UNK·source commit 결속 | 새 binary/ID/vocab, checksum 불일치, 별도 승인 없음 | 사용자 | C-4 입력 |
| C-4 Training Config Freeze | `blocked` | resolved config manifest, Evaluation Gate, Run·Approval policy, C-2/C-3 fingerprints | config fingerprint와 C-5 전용 실행 계획 | 미결정값 0, 단일 intervention, budget/step/checkpoint 일치, C-5 scope·failure criteria 승인 | placeholder·implicit default, 복합 변경 미승인, Run/Approval 발급, C-2/C-3 미완료 | 사용자 | 별도 승인 후 C-5 GPU Smoke |

문서 작성만으로 Gate를 `passed` 또는 `approved`로 바꾸지 않습니다. C-1의 `review`는 계약 초안이 검토 가능하다는 뜻이며,
ADR 승인이나 실행 허용을 뜻하지 않습니다.

## 8. Blocker Registry

| ID | Blocker | Severity | 상태 | 근거 | 해결 작업 | 승인 필요 | 차단 Gate |
|---|---|---|---|---|---|---|---|
| C-BLOCK-001 | ADR conflict | critical | `reviewing` | ADR-009 `not_required`와 새 로드맵 | ADR-011 사용자 검토·승인 | 예 | C-1 |
| C-BLOCK-002 | EOS root cause | high | `reviewing` | 현상은 확정, 인과 미확인 | Candidate B read-only 진단 후 주가설 승인 | 예 | C-1, C-4 |
| C-BLOCK-003 | Dataset freeze | critical | `reviewing` | C 전용 immutable manifest 없음 | 선택지 결정·필드 완성·checksum 재검증 | 예 | C-2, C-4 |
| C-BLOCK-004 | Tokenizer freeze | critical | `reviewing` | 승인 bundle 존재, C 결속·source commit 없음 | exact bundle compatibility freeze | 예 | C-3, C-4 |
| C-BLOCK-005 | Training config | critical | `blocked` | budget·initialization·intervention 등 미정 | 미결정값 0인 resolved config 계약 | 예 | C-4 |
| C-BLOCK-006 | Evaluation Gate | critical | `review` | 지표 분류는 작성, 수치 승격선 미승인 | Evaluation 계약 사용자 승인 | 예 | C-1, C-4, C-7 |
| C-BLOCK-007 | Run identity | high | `not_started` | immutable commit·Run ID·output 없음 | C-4 뒤 별도 identity·preflight package | 예 | C-5, C-6 |
| C-BLOCK-008 | Execution Approval | critical | `not_started` | 새 single-use 승인 없음 | C-5 통과 후 Run 전용 승인 | 예 | C-6 |

## 9. 현재 결론

```text
candidate_c_contract_design: completed
candidate_c_execution_allowed: false
gate_c1: review
gate_c2: reviewing
gate_c3: reviewing
gate_c4: blocked
gpu_smoke: not_started
training: not_started
```

다음 작업은 Candidate B checkpoint의 read-only EOS 진단 계약을 실행 가능한 별도 계획으로 검토하고, 그 결과로 단일
가설·Dataset 선택지·Training intervention을 승인하는 것입니다. GPU Smoke와 Candidate C 학습은 포함하지 않습니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Dataset·Tokenizer·Training Config freeze, Candidate C 변경 축, C-1~C-4 Gate와 ID 기반 blocker 계약 작성 |
