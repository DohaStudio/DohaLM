# Candidate B Final Read-only EOS 진단 계약

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 계약 설계: `design_completed`
- 실행 승인: `not_issued`
- 실행 허용: `false`
- GPU 진단 / Full 진단: `not_started` / `not_started`
- EOS-DIAG-R1: `implemented_synthetic_verified`
- EOS-DIAG-R2 Identity Freezer: `implemented_synthetic_verified`
- EOS-DIAG-R2 Generation Matrix: `implemented_synthetic_verified`
- EOS-DIAG-R3 Static Preflight: `implemented_synthetic_verified`
- 실제 Candidate B Static Preflight: `not_run`
- 실제 Candidate B identity freeze: `incomplete`
- EOS-DIAG-1 / EOS-DIAG-2: `not_passed` / `not_passed`
- 대상: Candidate B Final checkpoint, evaluation-only read-only 분석
- 후속 정책: [Candidate C 주가설 선택 정책](./candidate-c-hypothesis-selection-policy.md)
- 상위 근거: [Base Training Readiness](../training/base-training-readiness.md),
  [Candidate C EOS 가설](../training/candidate-c-eos-hypotheses.md), [ADR-008](../decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md),
  [ADR-009](../decisions/ADR-009-candidate-b-official-reassessment.md)

## 1. 목적과 책임 경계

Candidate B의 pure-greedy EOS 미종료와 repetition loop 현상을 checkpoint를 변경하지 않는 evaluation-only 분석으로
분해하고, Candidate C에 적용할 단일 EOS-focused intervention의 주가설을 선택할 수 있는 근거를 만듭니다.

진단은 Candidate B 재학습·resume·fine-tuning, optimizer state load, gradient 계산, checkpoint·Tokenizer·Dataset
rewrite, 서비스 decoding 채택과 Candidate C config 자동 확정을 하지 않습니다. `model.eval()`과
`torch.inference_mode()`만 허용하며 checkpoint local path, secret과 payload 원문은 공개 artifact에 남기지 않습니다.
Candidate B의 historical 판정과 ADR-009 current baseline 상태도 변경하지 않습니다.

## 2. 고정 입력 Identity 동결안

`확인`은 기존 immutable evidence의 실제 값이고 `미기록`은 실행 전에 새 evidence로 채워야 하는 blocker입니다. 미기록 값을
추정하거나 다른 fingerprint와 같은 값으로 간주하지 않습니다.

| 항목 | 동결 값 / 상태 | 근거 |
|---|---|---|
| Checkpoint artifact ID | `candidate-b-final`, `checkpoint-12208` | [artifact registry](../../configs/evaluation-artifacts.example.yaml) |
| Checkpoint checksum | `sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395` | `checksums.json` SHA-256, Candidate B 결과 |
| Checkpoint manifest fingerprint | `not_recorded` | `manifest.json`의 독립 fingerprint는 현재 공개 evidence에 없음 |
| Model config fingerprint | `sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106` | artifact registry |
| Training run ID | `FULL-PRETRAIN-CANDIDATE-B-20260728-0002` | [실행 결과](../training/candidate-b-execution-result.md) |
| Training source commit | `4c2eced3bf70551fbf7bc8ebde6666062584d92b` | 실행 결과 |
| Full Evaluation ID | `candidate-b-final-full-20260728-03` | [Full 결과](./candidate-b-final-full-result.md) |
| Full result fingerprint | `sha256:7b796f3abed0d6bd7a2426f9dff619f0609f59a4e1d04bf232545548d25d9df0` | ADR-009 |
| Evaluation dataset | `sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790` | Full evaluation identity |
| Split / training lineage | `sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f` / `sha256:a0677dc18dbc98371d349aef0f83ea610ab4a984657412bd1518b883a66bd3c6` | artifact registry |
| Tokenizer ID | `operating-16k-v2/unigram-16k` | 운영 Tokenizer manifest |
| Tokenizer fingerprint | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` | 운영 Tokenizer manifest |
| Tokenizer checksums | bundle `sha256:93dca331e2c82e912e832ecf4252d0638cd55e26f8802aea04d2fe7b3e043e6f`; model `sha256:11e536f275b9377794a52c8f3f5fadfe358f631c4b7af51bf9e371d2124fff0a`; vocab `sha256:9030a0cdc2fba938ac2a3fc8d0f7ae259d22b30ab22a2c57edb3d7cbcdfab11b` | [운영 manifest](../data/aihub-71748-operating-tokenizer-v2.manifest.yaml) |
| Vocabulary / PAD·BOS·EOS | `16000` / `0`·`2`·`3` | 운영 manifest; UNK `1`, role token `4`~`7`도 불변 |
| 기존 prompt fingerprint | `sha256:2cd1fee275601b82d34da9c7fd0f0398abd7dfb15b6a35afbcdbdb96164b37fa` | 기존 A/B 동일 조건 진단 결과 |
| Prompt set ID / version | `not_recorded` / `not_recorded` | 현재 YAML schema에 명시 필드 없음 |
| Prompt count / category | `15`; 15개 required category가 각각 1개 | [prompt config](../../configs/eos-generation-prompts.example.yaml), validator |
| Prompt length distribution | declared context class: `minimal=1`, `short=12`, `medium=1`, `long=1`; token-length bucket distribution `not_recorded` | prompt config에는 context class만 존재 |
| Prompt normalization / PII / leakage | normalization `not_recorded`; `source=synthetic`, `pii_free=true`; formal leakage review `not_recorded` | prompt config |
| Device / dtype / seed | 제안 freeze: `cuda`, `fp16`, `17`; exact GPU identity는 preflight에서 기록 | 기존 Full·A/B 진단은 RTX 3060 Ti, CUDA FP16, seed 17 |
| Diagnostic execution source commit | `not_frozen` | 구현 완료 뒤 immutable commit 필요 |
| Backend / dependency fingerprint | `not_recorded` / `not_recorded` | 기존 environment snapshot은 canonical fingerprints가 아님 |

공개 identity에는 logical ID와 fingerprint만 둡니다. D2·D4가 내부 evaluation prefix 또는 boundary metadata를 사용한다면
위 evaluation dataset·split·lineage와 동일해야 하며, 별도 입력 manifest와 접근 승인이 없으면 해당 진단은
`insufficient_evidence`입니다.

## 3. Diagnostic Run Identity와 reservation

형식은 `DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-YYYYMMDD-NNNN`입니다. 날짜는 예약 시점의 Asia/Seoul 날짜이고 artifact
timestamp는 UTC RFC 3339입니다. Candidate B training Run과 분리된 namespace를 사용하며 기존 진단 ID, 폐기 ID,
retry/replay ID를 재사용하지 않습니다. 새 시도는 새 Run ID와 새 Approval을 요구하고 predecessor diagnostic은 참조만 합니다.
이번 설계의 `diagnostic_run_id`는 `not_assigned`입니다.

기존 Candidate B training ID는 학습 budget 의미를 포함하고, AIHUB Processing Run ledger는 Dataset Processing 전용
schema·상태를 포함하므로 어느 것도 그대로 재사용할 수 없습니다. 고유성, reservation ledger, lifecycle lock, canonical
fingerprint와 atomic no-replace writer 패턴은 재사용하되 EOS 진단 전용 schema와 namespace 구현이 필요합니다. 예약은
identity만 선점하며 Approval 발급, Runtime Request 생성 또는 `execution_allowed=true`를 만들지 않습니다.

## 4. Prompt Set 계약

직접 비교에는 기존 Candidate A/B synthetic 15-prompt set만 사용합니다. prompt text bytes를 동적으로 정규화·생성·교체하지
않고 opaque prompt ID, category와 declared context class를 사용합니다. 실행 전에는 `prompt_set_id`, `version`, token-length
bucket distribution, normalization policy와 formal leakage 상태를 schema에 추가하고 기존 fingerprint와 함께 freeze해야 합니다.

추가 prompt가 필요하면 별도 `diagnostic_only_supplement` identity·checksum·분포로 관리하고 기존 A/B 직접 비교 통계에
합치지 않습니다. 공개 evidence는 전체 prompt를 저장하지 않으며 restricted source evidence만 원문을 보유할 수 있습니다.

## 5. Generation Matrix 동결안

현재 코드와 승인된 ADR-008 범위를 넘는 값을 추가하지 않습니다. 모든 profile은 각 prompt당 1회이며 sampling seed는
`SHA-256(17:profile_name:opaque_prompt_id)`로 결정됩니다. 반복 수 증가는 후속 config freeze와 승인이 필요합니다.

| 등급 | Profile | 고정 값 | 판정 용도 |
|---|---|---|---|
| 공식 모델 진단 | `greedy` | do_sample false; 16/32/64/128; temperature/top-p/top-k 비적용; repetition penalty 1.0; no-repeat 0; forced EOS·logit bias·heuristic stop false | pure model 증거 |
| `diagnostic_only` sampling | `temperature-0.7`, `temperature-1.0` | temperature 0.7/1.0, seed 17 | H5 보조 |
| `diagnostic_only` sampling | `top-k-20`, `top-k-50` | temperature 1.0, top-k 20/50, seed 17 | H5 보조 |
| `diagnostic_only` sampling | `top-p-0.9`, `top-p-0.95` | temperature 1.0, top-p 0.9/0.95, seed 17 | H5 보조 |
| `diagnostic_only` assisted | `repetition-1.05`, `repetition-1.10` | greedy + repetition penalty 1.05/1.10 | H5·H7 보조 |
| `diagnostic_only` assisted | `no-repeat-bigram`, `no-repeat-trigram` | greedy + no-repeat n-gram 2/3 | H5·H7 보조 |

Assisted termination·외부 stopping heuristic profile은 현재 matrix와 구현에 없으므로 `disabled_not_supported`입니다.
Assisted 결과는 Candidate C Base 승격 지표로 직접 쓰지 않습니다. Canonical matrix fingerprint는 schema version, profile의
정렬된 전체 필드, 길이, prompt 반복 수, seed derivation, device/dtype, stop policy와 privacy flags를 canonical UTF-8 JSON으로
직렬화한 SHA-256입니다. 누락·unknown field·순서 drift는 Config Freeze를 실패시킵니다.

## 6. D1~D8 진단·판정 계약

| ID | 최소 record와 집계 | 판정과 한계 |
|---|---|---|
| D1 EOS Rank·Probability Trajectory | opaque prompt ID, category, prompt-length bucket, generation step, EOS logit/probability/rank, selected token ID, 제한된 top competitor token ID·logit summary, decoding mode, max length | finite, record completeness, profile·길이 분리만 무결성 판정; 원문·전체 sequence 금지 |
| D2 Teacher-forced vs Autoregressive Gap | 동일 비교 위치의 teacher/autoregressive EOS rank·probability, absolute gap과 denominator가 0이 아닐 때만 relative gap, category·position aggregate | 동일 prefix/position identity를 증명해야 H1/H2 근거; 기존 aggregate만으로 pairing 불가하면 `insufficient_evidence` |
| D3 Repetition Loop Onset | onset step, token/ngram HMAC, loop length·persistence, unique-token ratio, loop 전후 EOS rank, max-length hit | HMAC key는 artifact 밖; onset 전후 record가 없으면 H7 판정 불충분 |
| D4 Boundary Proximity | opaque boundary identity, EOS target 거리, packed 여부, 인접 sample count, 거리 bucket별 teacher/autoregressive EOS | 기존 prompt-only generation은 boundary identity가 없음; immutable evaluation boundary evidence가 없으면 H3/H4 `insufficient_evidence` |
| D5 Prompt Length·Category·Position | prompt-length bucket, category, output-position bucket, EOS rank/probability, termination type, repetition, incomplete 여부 | 15 category 누락 0, 직접 비교 set과 supplement 분리 |
| D6 Length Matrix | 16/32/64/128별 EOS·max-length·repetition·incomplete count/rate, unique-token ratio, 평균 생성 길이 | 새 통과 threshold 없이 기존 A/B 상대 비교와 방향만 보고 |
| D7 Decoding Ablation | pure greedy와 sampling, repetition penalty, no-repeat n-gram을 분리한 delta; assisted termination은 미지원 표시 | H5 진단 전용; assisted 성공을 pure 성공 또는 Base 승격으로 해석 금지 |
| D8 Budget Proxy | A 10,000,384 vs B 25,001,984 scheduled token, optimizer step 4,883 vs 12,208, teacher EOS·Full·pure greedy·repetition 변화 | 기존 A/B evidence만 사용; 인과 추정·새 학습 금지, H6 근거 수준은 보수적으로 판정 |

`incomplete`는 기존 prompt `completion_shape`와 승인된 종료 판정 규칙에서 산출하며 새 의미·수치 threshold를 만들지 않습니다.
D2·D4용 restricted evaluation prefix는 공개 artifact에서 opaque ID와 aggregate만 남깁니다.

## 7. Output Artifact 계약

다음 18개가 exact set이며 하나라도 없거나 checksum/fingerprint가 불일치하면 `completed`가 아닙니다.

```text
diagnostic-plan.json
checkpoint-identity.json
tokenizer-identity.json
prompt-set-manifest.json
generation-matrix.json
eos-rank-trajectory.jsonl
eos-probability-summary.json
teacher-autoregressive-gap.json
loop-analysis.json
boundary-analysis.json
prompt-category-position-analysis.json
length-matrix.json
decoding-ablation.json
budget-proxy-analysis.json
hypothesis-assessment.json
diagnostic-summary.json
checksum-inventory.json
completion-evidence.json
```

각 artifact는 `schema_version`, `diagnostic_run_id`, checkpoint·Tokenizer·prompt-set logical identity,
`generation_matrix_fingerprint`, source commit, `record_count`, `artifact_fingerprint`, `checksum`을 포함합니다. JSONL은 각
record에 공통 identity envelope 또는 동일 checksum으로 고정된 envelope reference를 둡니다. `artifact_fingerprint`는
volatile 시각·checksum을 제외한 semantic payload SHA-256, 내장 `checksum`은 checksum 필드만 제외한 canonical artifact
SHA-256이며, `checksum-inventory.json`은 최종 file bytes SHA-256으로 completion evidence를 제외한 파일을,
`completion-evidence.json`은 exact set, inventory checksum, validation result와 종료 시각을 no-replace로 마지막 게시합니다.
completion evidence의 검증 성공만 `completed` transition을 허용합니다.

Optional set은 공식 집계와 분리한 restricted qualitative sample bundle뿐입니다. 별도 restricted root, 접근 기록, 자체 checksum,
보존·삭제 정책을 요구하며 exact set의 완료 조건이나 가설 지지 수치에 포함하지 않습니다.

## 8. 보안·개인정보 계약

공개 artifact에는 전체 prompt·응답·raw token sequence, 개인정보, checkpoint·Tokenizer local path, 환경변수, secret과 traceback을
금지합니다. opaque prompt ID, category·bucket, 단일 step token ID, keyed HMAC n-gram, aggregate metric과 safe error code만
허용합니다. HMAC key와 restricted 원문은 공개 checksum inventory에 비밀값으로 포함하지 않습니다. 실패 artifact도 동일한
redaction validator를 통과해야 하며 traceback은 restricted local log로만 둘 수 있습니다.

## 9. Readiness Gate

| Gate | 입력과 통과 조건 | 현재 상태 |
|---|---|---|
| EOS-DIAG-1 Identity Freeze | checkpoint manifest·checksum, Tokenizer, prompt set, diagnostic source commit을 immutable identity로 연결 | `blocked` |
| EOS-DIAG-2 Config Freeze | generation matrix, seed, device/dtype, exact output set의 미결정 0과 canonical fingerprint | `blocked` |
| EOS-DIAG-3 Static Preflight | strict request, repository/source, explicit backend·dependency, metadata-only input, 신규 destination, disk/path/lock/process를 payload load 없이 검증 | `implemented_synthetic_verified`; actual `not_run` |
| EOS-DIAG-4 GPU Smoke Approval | 동일 Run 안의 최소 prompt·짧은 generation, load/unload·OOM/VRAM과 전후 checksum; 별도 자동 권한 없음 | `not_started` |
| EOS-DIAG-5 Full Diagnostic Approval | EOS-DIAG-1~4 계약 충족, single-use Approval·Runtime Request, exact set, 자원·시간, checkpoint write 불가 | `not_started` |

GPU Smoke와 Full은 하나의 bounded supervisor session에서만 연속 수행합니다. Approval은 checkpoint payload 접근 직전에 한 번
소비됩니다. Smoke 실패 시 같은 Approval·Run으로 retry하지 않으며 Full로 진행하지 않습니다.

## 10. Diagnostic-only Approval

전용 strict schema의 필수 필드는 `schema_version`, `approval_id`, `diagnostic_run_id`, checkpoint·Tokenizer·prompt-set·matrix,
backend·dependency·source commit·expected artifact set fingerprint, `allowed_action`, `issued_at`, `expires_at`, `consumed_at`,
`status`, `approver_id`, `checksum`입니다. `allowed_action`은 정확히 `candidate_b_eos_diagnostic_only`이며 checkpoint write,
training, resume, Dataset·Tokenizer modification와 publication 권한은 모두 false입니다. 상태는
`draft -> issued -> consumed` 또는 `draft|issued -> retired`, `issued -> expired`만 허용합니다.

기존 Approval lifecycle의 strict serialization, checksum, expiry, single-use consume, lifecycle lock과 atomic no-replace 패턴은
재사용할 수 있습니다. 기존 Candidate B training/AIHUB Processing schema는 action·budget·capability 의미가 달라 직접
재사용하지 않습니다. 발급은 사용자 승인과 별도 작업이며 이번 문서는 Approval이 아닙니다.

## 11. Diagnostic Runtime Request

여기서 Runtime Request는 Phase 2 Qwen Runtime이 아니라 진단 실행 supervisor에 전달하는 immutable one-shot request입니다.
필수 필드는 `schema_version`, `request_id`, `approval_id`, `diagnostic_run_id`, checkpoint·Tokenizer·prompt-set identity,
canonical generation matrix, backend/dependency fingerprint, source commit, device/dtype, logical output root ID, expected exact set,
nonce, TTL, anti-replay hash, checksum과 status입니다. Approval과 request의 모든 bound identity가 같아야 합니다.
Request 상태는 `issued`, `consumed`, `retired`, `expired`만 허용하고 immutable 본문을 덮어써 전이하지 않으며 one-shot
registry에 후속 상태를 기록합니다.

Request 생성만으로 `execution_allowed`는 true가 되지 않습니다. Supervisor가 fresh issued Approval, unconsumed request,
preflight evidence와 one-shot registry를 같은 lifecycle lock 안에서 검증한 뒤 실제 checkpoint load와 restricted payload 접근
직전에 Approval을 소비합니다. nonce·request ID·fingerprint 재사용, 만료, 기존 output과 predecessor 재실행은 차단합니다.

## 12. 상태 머신과 책임

```text
planned -> identity_frozen -> config_frozen -> preflight_passed
        -> approval_issued -> request_created -> approval_consumed
        -> loading -> gpu_smoke_passed -> diagnostic_running
        -> validating -> completed
```

실패 상태는 `identity_invalid`, `config_invalid`, `preflight_failed`, `gpu_smoke_failed`, `load_failed`,
`diagnostic_failed`, `validation_failed`, `retired`입니다. 실패는 terminal이며 retry/replay는 새 Run입니다.

- Supervisor: reservation·Approval·request·freshness·preflight 검증, consume, checkpoint read-only load/unload, 단계 전이, 자원 상한과
  실패 중단을 책임집니다.
- Diagnostic backend: D1~D8 계산만 하며 상태·Approval·checkpoint write 권한이 없습니다.
- Artifact writer: staging 내부 strict schema·redaction·checksum을 검증하고 final root를 atomic no-replace로 게시하며 마지막에
  completion evidence를 게시합니다. lifecycle이나 성능 판정을 임의 변경하지 않습니다.

## 13. Blocker registry

| ID | 심각도 | 상태 | 현재 evidence | 해소 조건 | 승인 | Blocking Gate |
|---|---|---|---|---|---|---|
| EOS-DIAG-BLOCK-001 checkpoint identity freeze | critical | `blocked` | artifact ID·checksum·model fingerprint 확인, 독립 manifest fingerprint 미기록 | manifest fingerprint와 전후 read-only checksum validator | 필요 | 1 |
| EOS-DIAG-BLOCK-002 tokenizer identity freeze | high | `reviewing` | ID·bundle/model/vocab checksum·fingerprint·special ID 확인 | 실행 source와 exact bundle 결속 검증 | 필요 | 1 |
| EOS-DIAG-BLOCK-003 prompt set freeze | critical | `blocked` | fingerprint·15 category·PII flag 확인 | ID/version, token-length 분포, normalization·leakage evidence 동결 | 필요 | 1 |
| EOS-DIAG-BLOCK-004 generation config freeze | critical | `blocked` | 기존 11 profile·4 길이 존재 | canonical schema/fingerprint와 device/dtype 결정 | 필요 | 2 |
| EOS-DIAG-BLOCK-005 output schema·writer | critical | `completed_r1_synthetic` | 18 exact schema, strict loader/validator, canonical UTF-8, inventory, completion, atomic no-replace와 reload를 synthetic 검증 | R4 실측 record schema 연결 후 actual preflight 재검증 | 필요 | 3 |
| EOS-DIAG-BLOCK-006 diagnostic backend readiness | critical | `blocked` | 기존 trajectory·aggregate 일부 존재 | D1~D8, 특히 paired D2·boundary D4와 assessor 합성 검증 | 필요 | 3 |
| EOS-DIAG-BLOCK-007 GPU resource preflight | high | `not_started` | 과거 RTX 3060 Ti 실행 이력만 존재 | 현재 exact environment·disk·VRAM preflight | 필요 | 4 |
| EOS-DIAG-BLOCK-008 single-use Approval | critical | `not_started` | 전용 artifact 없음 | schema 검증 후 별도 사용자 발급 | 사용자 | 5 |
| EOS-DIAG-BLOCK-009 Runtime Request | critical | `not_started` | 전용 request 없음 | Approval-bound one-shot request 발급·검증 | 사용자 | 5 |
| EOS-DIAG-BLOCK-010 ADR-011 / 사용자 결정 | critical | `blocked` | ADR-011은 draft | 진단은 별도 명시 승인; 결과의 Candidate C 적용은 ADR-011·주가설 사용자 결정 | 사용자 | 5 및 C-1 |

## 14. 후속 구현 Task

예상 경로는 아직 없는 경우 코드 표기로 유지합니다.

| Task | 예상 변경 파일 | 검증 | GPU | checkpoint | 승인 | 완료 조건 |
|---|---|---|---|---|---|---|
| EOS-DIAG-R1 schema·strict validator | [artifact system](../../src/evaluation/eos_diagnostic_artifacts.py), [synthetic tests](../../tests/evaluation/test_eos_diagnostic_artifacts.py) | unknown/duplicate/non-finite/schema/Git SHA/timestamp/checksum/fingerprint/exact set, canonical/no-replace/reload | 불필요 | 없음 | 불필요 | `implemented_synthetic_verified`; 10 tests passed |
| EOS-DIAG-R2 matrix·identity freezer | [identity freezer](../../src/evaluation/eos_diagnostic_identity.py), [matrix freezer](../../src/evaluation/eos_generation_matrix.py), [identity tests](../../tests/evaluation/test_eos_diagnostic_identity.py), [matrix tests](../../tests/evaluation/test_eos_generation_matrix.py) | explicit-input canonicalization, immutable ID/version·fingerprint, lineage, exact profile/count, R1 payload 연결 | 불필요 | synthetic metadata fixture만 | 실제 freeze 승인 없음 | `implemented_synthetic_verified`; 실제 Gate 1·2 미통과 |
| EOS-DIAG-R3 metadata-only static preflight | [preflight](../../src/evaluation/eos_diagnostic_preflight.py), [synthetic tests](../../tests/evaluation/test_eos_diagnostic_preflight.py) | strict request, clean Git, allowlist source hash, dependency snapshot, stat-only input, 신규 destination·disk·path·lock·process, Gate 1·2 mapping, R1 plan 연결 | 불필요 | payload read 없음 | 불필요 | `implemented_synthetic_verified`; actual preflight `not_run` |
| EOS-DIAG-R4 D1~D8 backend | `src/evaluation/eos_diagnostic_backend.py`, metric unit tests | synthetic logits·prefix·boundary·loop fixtures | 단위 검증 불필요 | 없음 | 불필요 | D1~D8와 insufficient evidence 상태 |
| EOS-DIAG-R5 aggregate·hypothesis assessor | `src/evaluation/eos_hypothesis_assessor.py`, assessor tests | support/contradiction/insufficient·no forced selection | 불필요 | 없음 | 정책 검토 | decision artifact strict 생성 |
| EOS-DIAG-R6 Approval·Request·Run ledger | `src/evaluation/eos_diagnostic_control.py`, CLI, lifecycle tests | TTL·nonce·anti-replay·consume·atomic no-replace·race | 불필요 | 없음 | schema 승인 | one-shot control plane 합성 검증 |
| EOS-DIAG-R7 synthetic E2E rehearsal | synthetic fixture/config와 E2E tests | exact set, failure injection, zero secret/path/text, no mutation | 불필요 | 합성 fixture | rehearsal 승인 | completion evidence 포함 dry rehearsal |
| EOS-DIAG-R8 GPU smoke | 외부 immutable smoke evidence만 | 1개 최소 prompt, 짧은 길이, load/unload, VRAM, 전후 checksum | 필요 | 실제 read-only | single-use 실행 승인 | smoke 통과 또는 terminal 실패 |
| EOS-DIAG-R9 Full diagnostic | 외부 immutable 18-artifact bundle, 결과 문서 | D1~D8·exact set·checksum·completion validation | 필요 | 실제 read-only | 같은 bounded Run 승인 | completed 또는 terminal 실패; 상태 자동 승격 없음 |

R1~R3은 아래 범위로 구현·합성 검증됐습니다. R4~R7은 별도 요청이며 R8/R9는 실제 Run ID, Approval과 Request가 생긴
뒤에만 가능합니다.

### 14.1 EOS-DIAG-R1 구현 경계

[확정] R1은 18개 filename exact set, 공통 envelope, 8개 관리 artifact payload, D1~D8 계열 schema-only envelope,
canonical UTF-8 JSON, duplicate-key·NaN/Inf·unknown-field 차단, semantic fingerprint·artifact checksum, atomic hard-link
no-replace writer, reload 검증, content inventory와 completion evidence를 구현했습니다. `.jsonl` trajectory는 R1에서 단일
canonical envelope record만 허용하며 실제 step record schema는 R4에서 확장합니다.

[확정] `synthetic_schema_rehearsal` completion은 18개 artifact가 정확히 존재하고 inventory·identity·checksum이 일치할 때만
가능합니다. `diagnostic_execution` completion은 D1~D8 artifact가 `schema_only`인 동안 fail-closed되므로 이번 구현으로 실제
진단 완료를 만들 수 없습니다. Checkpoint·Tokenizer load, torch·CUDA, inference, generation과 EOS 계산은 수행하지 않았습니다.

### 14.2 EOS-DIAG-R2 구현 경계

[확정] R2는 caller가 명시적으로 전달한 값만 검증합니다. filesystem 자동 탐색, 실제 checkpoint·Tokenizer·prompt payload 읽기,
환경 자동 조회와 네트워크 접근은 구현하지 않았습니다. Checkpoint·Tokenizer·Prompt Set·Backend·Dependency identity는 frozen
dataclass와 canonical SHA-256 fingerprint로 표현하며 unknown field, 잘못된 checksum·Git SHA·version, lineage mismatch와 필수 값 누락을
fail closed 처리합니다. Identity fingerprint에는 timestamp 필드가 없으므로 실행 시각에 따라 변하지 않습니다.

[확정] Generation Matrix는 기존 decoder가 지원하는 11개 profile과 길이 `16/32/64/128`, prompt 15개, 반복 1회를 정확히
동결합니다. 논리 evaluation cell은 `15 × 11 × 4 = 660`이고, 기존 구현이 최대 128-token trajectory를 한 번 생성한 뒤 길이별
prefix를 재사용하므로 trajectory 호출 수는 `15 × 11 = 165`로 별도 기록합니다. 공식 모델 지표는 `greedy` 하나뿐이며 나머지
10개 sampling·assisted profile은 `diagnostic_only`입니다. 외부 termination heuristic은 지원하지 않습니다.

[확정] Synthetic complete fixture에서는 EOS-DIAG-1·2 validator의 `passed` 경로와 R1 관리 artifact 6개 payload 연결을
검증할 수 있습니다. Synthetic Run ID는 `SYNTHETIC-` namespace를 강제하며 실제 diagnostic completion으로 전환할 수 없습니다.
이 결과는 실제 Candidate B Gate 통과, Approval, Runtime Request 또는 실행 허용을 뜻하지 않습니다.

[검증 필요] 실제 Candidate B는 independent checkpoint manifest fingerprint가 없고, prompt set ID/version·token-length
distribution·normalization·formal leakage evidence가 미동결이며, diagnostic source commit·backend module fingerprint·dependency
snapshot도 아직 공급되지 않았습니다. 따라서 실제 identity freeze는 `incomplete`, Gate EOS-DIAG-1·2는 `not_passed`입니다.

### 14.3 EOS-DIAG-R3 구현 경계

[확정] R3는 절대경로를 artifact에 넣지 않는 strict `StaticPreflightRequest`, 명시된 저장소의 branch·remote·HEAD·
`origin/develop`·clean worktree·진행 중 Git operation 검증, caller allowlist source/schema 파일의 결정론적 fingerprint와
stat mutation detection, 경로를 노출하지 않는 dependency snapshot을 구현했습니다. Backend source read만 허용하며 저장소
전체 scan이나 네트워크 조회는 하지 않습니다. Dependency version의 local suffix는 제거하지 않고 exact 문자열로 보존합니다.

[확정] Checkpoint·Tokenizer·Prompt root는 root와 지정 manifest의 존재·type·symlink·read access를 stat metadata로만
확인합니다. 쓰기 가능 여부를 시험하기 위한 파일 생성이나 permission 변경은 하지 않고, read-only 계약은 `payload_reads=0`,
`write_attempts=0`으로 증명합니다. Output·staging·failure는 생성하지 않은 채 신규성, 서로 다른 경로, source/input 하위 금지,
부모 writable metadata, same-volume, explicit disk minimum, longest exact artifact/temp/failure path, reserved name, lock와
caller-supplied process inventory를 검증합니다.

[확정] R3 evidence는 18개 exact set을 변경하지 않고 `diagnostic-plan.json`의 optional strict `preflight` section으로 연결됩니다.
Synthetic complete fixture에서 Gate 1·2 `passed` 경로를 검증해도 `diagnostic_execution_allowed=false`이고 completion evidence,
Approval 또는 Runtime Request를 만들지 않습니다.

[확정] 외부 오류는 `EOS_DIAG_PREFLIGHT_INVALID`, `EOS_DIAG_REPOSITORY_STATE_INVALID`,
`EOS_DIAG_SOURCE_COMMIT_MISMATCH`, `EOS_DIAG_BACKEND_FINGERPRINT_INVALID`,
`EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID`, `EOS_DIAG_INPUT_ROOT_INVALID`, `EOS_DIAG_INPUT_NOT_READ_ONLY`,
`EOS_DIAG_OUTPUT_ROOT_INVALID`, `EOS_DIAG_OUTPUT_CONFLICT`, `EOS_DIAG_DISK_SPACE_INSUFFICIENT`,
`EOS_DIAG_PATH_LENGTH_EXCEEDED`, `EOS_DIAG_LOCK_CONFLICT`, `EOS_DIAG_PROCESS_CONFLICT`,
`EOS_DIAG_IDENTITY_INCOMPLETE`, `EOS_DIAG_GATE_NOT_READY`의 stable code만 사용합니다. 전체 절대경로, remote credential,
environment path, payload와 traceback은 오류에 포함하지 않습니다.

[검증 필요] 실제 Candidate B local path, formal identity evidence와 clean immutable 실행 commit을 입력하지 않았으므로 actual
Static Preflight는 `not_run`입니다. Synthetic R3 구현 완료가 실제 Gate 1·2 또는 EOS-DIAG-3 통과를 뜻하지 않습니다.

## 15. 현재 상태

```text
candidate_b_eos_diagnostic_contract: design_completed
eos_diag_r1_artifact_system: implemented_synthetic_verified
eos_diag_r2_identity_freezer: implemented_synthetic_verified
eos_diag_r2_generation_matrix: implemented_synthetic_verified
eos_diag_r3_static_preflight: implemented_synthetic_verified
actual_candidate_b_static_preflight: not_run
actual_candidate_b_identity_freeze: incomplete
gate_eos_diag_1: not_passed
gate_eos_diag_2: not_passed
candidate_b_eos_diagnostic_execution_allowed: false
candidate_b_checkpoint_mutation_allowed: false
candidate_c_primary_hypothesis: not_selected
candidate_c_readiness: blocked
gate_c1: review
gate_c4: blocked
gpu_diagnostic: not_started
full_diagnostic: not_started
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | EOS-DIAG-R3 metadata-only Static Preflight, explicit backend/dependency identity, Git·input/output·disk/path/lock/process 검증과 Gate 1·2/R1 plan synthetic 연결; actual preflight 미실행 유지 |
| 2026-08-05 | EOS-DIAG-R2 explicit-input identity·lineage freezer, exact 11-profile/4-length matrix, Gate 1·2 evidence와 R1 management payload 연결을 synthetic-only로 구현; 실제 identity freeze·Gate는 미완료 유지 |
| 2026-08-05 | EOS-DIAG-R1 18-artifact strict schema·canonical loader/validator·atomic no-replace writer·inventory·completion evidence 구현과 synthetic 10-test 검증 반영 |
| 2026-08-05 | Candidate B Final read-only EOS 진단 identity·matrix·D1~D8·artifact·Gate·Approval·Request·상태 머신·blocker·구현 Task 설계 |
