# DohaLM General Instruct v0.3 학습 재개 Readiness

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 브랜치·커밋: `develop` · `0b9337699989fb8fe76640faa40b94a16761a200`
- 최종 판단: `ready_for_recovery_design`
- v0.3 학습 상태: `not_started`
- v0.3 학습 준비: `false`
- 실행 권한: `false`
- 관련 문서: [V03-1·V03-2 Recovery Contract](./dohalm-v0.3-recovery-contract.md), [v0.3 Tokenization Readiness](./dohalm-v0.3-tokenization-readiness.md), [publish 실패 보존 계약](./dohalm-v0.3-tokenization-publish-failure.md), [Adapter 후보 선정 결과](./general-instruct-adapter-candidate-selection.md)

## 1. 범위와 판정 원칙

[확정] 이 문서는 저장소 코드·설정·테스트·커밋과 명시적인 Git 외부 v0.3 artifact를 읽기 전용으로 대조한
실행 전 계획이다. Dataset 생성, Tokenization, publish, sampler simulation, GPU load, backward, optimizer step,
checkpoint, 평가, Approval 발급·소비와 Runtime request 생성은 수행하지 않았다.

[확정] Foundation Candidate B 계보, Provider·FastAPI·Frontend와 Runtime manifest는 변경하지 않는다. v0.3는
Qwen Base 기반 Runtime General Instruct Adapter 후보이며 Foundation Instruct가 아니다.

[확정] 다음 상태를 구분한다.

- `ready_for_recovery_design`: 복구 계약·Gate·Task를 설계할 근거는 있음
- `ready_for_tokenization_republish`: 승인된 새 identity와 canonical 입력으로 publish 실행 가능
- `ready_for_training_preflight`: canonical tokenized artifact와 동결된 실행 설정이 있음

현재 판정은 첫 번째에만 해당한다.

## 2. 작업 시작과 확인한 evidence

| 항목 | 결과 |
|---|---|
| Branch | `develop` |
| HEAD | `0b9337699989fb8fe76640faa40b94a16761a200` |
| `origin/develop` | HEAD와 일치 |
| Worktree | clean, 기존 사용자 변경 없음 |
| v0.3 Dataset root | Git 외부 `/home/doha/dohalm-data-v3/DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001` |
| Tokenization parent | Git 외부 `/home/doha/dohalm-data-v3/tokenized` |
| Tokenization final·staging·failed | 모두 관측되지 않음 |
| GPU·네트워크 | 사용하지 않음 |

[확정] Dataset의 기존 `checksums.sha256` 8개 항목은 모두 `OK`였다. 주요 evidence는 다음과 같다.

| Evidence | SHA-256 또는 fingerprint |
|---|---|
| `checksums.sha256` 파일 | `bc1a17b21eaf918aee3acb83291f8822a9994ef92bade4500881d0dd258fb0a3` |
| `manifest.yaml` 파일 | `56091e7531fc79e729535fb6415efd050e28b19be9f369f38e0f2d8d39d167f0` |
| `statistics.json` 파일 | `d2a15e70ecce46d8c9d00166524ce95cd526a862ed4058ba01bba26b3e8249b1` |
| Dataset package fingerprint | `sha256:16204818cedbe079e5a8ad436e1d0e1f315995d0655cadad1ac3f391a559d752` |
| Dataset semantic manifest fingerprint | `sha256:fd7211e65a1db6ac949fdc18d098f76b1bff9318772b211a88f55aa0ccae3885` |

## 3. v0.3 전체 계보

| 단계 | 구현 상태 | 실행 상태 | Run identity | 승인 상태 | 입력 artifact | 출력 artifact·fingerprint | Source commit | Known failure | 재사용·재실행 |
|---|---|---|---|---|---|---|---|---|---|
| Raw Source | 기존 backend·계약 구현 | Run 0015 완료 이력 | `AIHUB-71748-SFT-PROCESSING-20260730-0015` | 과거 단일 처리 이력; 포괄 재승인 아님 | AIHUB-71748 SFT component | Train 10,374·Validation 1,287, source fingerprint `b6848e...98a0` | 별도 계보 | 이용조건·외부 benchmark 증빙 잔여 | byte-identical source만 조건부 재사용, 재처리 미승인 |
| Parsing·Join | 구현·검증 이력 있음 | 완료 이력 | Run 0015 계보 | 후속 실행 권한 없음 | SFTdata·SFTlabel | one-to-one source JSONL | 별도 계보 | 없음으로 승격 불가 | 결과 evidence 재사용 가능 |
| Quality Validation | 정책·처리 이력 있음 | source sidecar 생성 | v0.2 sidecar 계보 | 후속 포괄 승인 아님 | Run 0015 | sidecar fingerprint `sha256:4a1395...fe9c` | 별도 계보 | SFT terms·benchmark 잔여 | aggregate evidence 조건부 재사용 |
| Short Answer Generation | 구현·synthetic/실제 실행 완료 | **완료** | `DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001` | 당시 config는 generation 허용; 현재 추가 실행 불가 | v0.2 source·sidecar | Train 17,639·Validation 1,287; package `sha256:162048...752` | `42f79d96fbacf9f96ec9cdf1e3730d780a7d8f3d` | target medium 15% 미달, 실제 medium 0%; review 539건은 제외 | canonical package read-only 재사용 가능, 재생성 불필요 |
| Dataset Manifest | 구현·검증 완료 | 게시·reload 완료 | Dataset ID와 동일 | `execution_allowed: false` | Short Answer 결과 | manifest `sha256:fd7211...3885` | `42f79d9...` | safety/PII 전용 field 없음 | V03-1 통과 시 입력으로 사용 |
| Tokenization | 구현됨 | 한 번 시도, 성공 evidence 없음 | `DOHALM-V0.3-TOKENIZATION-20260802-0001` | config의 `tokenization_allowed: true`; single-use approval artifact 없음 | canonical v0.3 Dataset·Qwen tokenizer | canonical output 없음 | 실행 HEAD 미보존; 구현 계보 `4234c10...` | wrapper timeout observability loss | 기존 Run ID 재사용 금지, 새 실행 필요 |
| Tokenized Artifact | writer 구현됨 | **미생성으로 판정** | 기존 ID non-reusable | 미승인 | 메모리 내 결과가 있었는지 확인 불가 | final·staging·failed·checksum·fingerprint 모두 없음 | 해당 없음 | incomplete evidence | 복구 재사용 불가 |
| Publish | 후속 hardening 구현·synthetic 검증 | 원래 시도 실패, 재실행 없음 | 기존 ID non-reusable | retry/replay 미승인 | 내부 publish 상태 미보존 | terminal failure artifact도 없음 | 후속 `4c17ebe...` | 내부 예외 `UNRESOLVED` | 새 ID·새 승인 필요 |
| Training Readiness | 초안 config만 존재 | static review만 수행 | 없음 | `training_allowed: false`, `execution_allowed: false` | canonical tokenization 없음 | executable resolved config 없음 | 현재 HEAD | v0.3 backend·필수 설정 미완성 | 재설계 필요 |
| QLoRA Training | v0.1/v0.2 backend만 존재 | 미시작 | 없음 | 미승인 | 없음 | Adapter·checkpoint 없음 | 해당 없음 | 해당 없음 | 새 backend/config freeze 후에만 가능 |
| Evaluation | v0.1/v0.2 evaluator 재사용 후보 | 미시작 | 없음 | 미승인 | Adapter 없음 | 평가 fingerprint 없음 | 해당 없음 | v0.1/v0.2 hard blocker 미통과 이력 | Gate 확장 후 신규 실행 |
| Candidate Selection | Runtime 선정 계약 있음 | v0.3 후보 없음 | 없음 | 승격 미승인 | 평가 없음 | `no_eligible_candidate` 유지 | `0b933769...` | 필수 artifact 누락 | 평가 통과 뒤 신규 판정 |

## 4. Publish-stage failure 분석

### 4.1 관측 사실

| 확인 항목 | 판정 |
|---|---|
| 실패 Run ID | `DOHALM-V0.3-TOKENIZATION-20260802-0001` |
| 외부 관측 code | `WRAPPER_TIMEOUT_OBSERVABILITY_LOSS` |
| 내부 worker failure code | `UNRESOLVED` |
| 실패 시점 | 2026-08-02; 정확한 terminal timestamp 미보존 |
| publish 전 단계 성공 | 문서에는 publish-stage 도달 이력이 있으나 stage-state가 없어 독립 재검증 불가 |
| temporary artifact | 현재 없음 |
| final artifact | 없음 |
| terminal `.failed` artifact | 없음; 해당 계약은 실패 뒤 구현됨 |
| atomic no-replace | 후속 코드와 synthetic test에서 검증; 원래 실행의 성공 증거 아님 |
| checksum mismatch | mismatch evidence 없음; checksum inventory 자체가 없음 |
| raw checksum·parsed checksum | Dataset 생성 단계에서 분리 검증됨; tokenization publish 원인과 직접 연결되지 않음 |
| tokenization output fingerprint | 없음 |
| tokenization manifest fingerprint | 없음 |
| destination | parent는 존재하지만 target identity surface는 비어 있음 |
| 같은 identity 재사용 | 금지; `previous_publish_attempt_recorded: true` |
| Approval consumed | v0.3 Tokenization 코드에 발급·소비 계약이 없어 `not_recorded` |
| Runtime request consumed | v0.3 Tokenization 코드에 연결되지 않아 `not_applicable_not_recorded` |
| retry·replay | 기존 ID로 금지; 새 identity·명시적 승인 필요 |

### 4.2 원인 분류

[확정] 외부 장애는 `environment failure` 범주의 wrapper timeout·관측성 손실이다. 그러나 실제 publish 내부
root cause는 evidence가 없어 `unknown`이며, 복구 관점의 직접 blocker는 `incomplete evidence`다. 다음을 원인으로
확정하지 않는다.

- code defect
- stale artifact
- approval mismatch
- fingerprint mismatch
- destination conflict
- policy rejection

[확정] 당시 조사에서 cross-device rename, no-replace 미지원, directory fsync 미지원, parent 권한, disk·inode 부족은
별도 probe로 배제됐다는 기존 기록을 유지한다. 원래 worker의 terminal exception이 없으므로 이 배제가 실제 내부
예외를 대신하지는 않는다.

## 5. 실패 이후 코드 변경과 충분성

| 변경 | 해결한 문제 | 원래 실패와 직접 관련 | 검증 수준 | 실제 recovery에 충분한가 |
|---|---|---|---|---|
| raw checksum과 parsed record 분리 (`225b0ff`/`42f79d9`) | JSON serialization과 논리 record equality 혼동 제거 | 아니요, Dataset integrity 영역 | synthetic·production-shape 회귀와 실제 Dataset manifest | Dataset 재사용 근거로 충분, publish 원인 해결 증거 아님 |
| 통계 계약 보완 (`97abe5a`/`0f6373b`) | composition·length·review·lineage 집계 완전성 | 아니요 | synthetic test와 실제 `statistics.json` | 분석 evidence로 충분, 실행 승인 근거는 아님 |
| stage tracker·supervisor (`8abb556`/`4c17ebe`) | 전체 timeout 대신 heartbeat·publish timeout 분리 | 관측성 손실에 직접 대응 | synthetic process·timeout test | 다음 실패 진단에는 유효, 원래 내부 원인 해결 여부는 불명 |
| terminal failure artifact | 실패 code·stage·inventory·checksum 보존 | 관측성 손실에 직접 대응 | failure injection·checksum test | 새 실행에서만 증명 가능 |
| 단계별 atomic writer | staging/write/fsync/checksum/reload/no-replace/final 검증 분리 | 가능한 publish defect 범위를 축소 | synthetic success·각 단계 failure injection | 실제 filesystem의 fresh run 검증 전에는 불충분 |
| validation 순서 | staging 검증 후 publish, final reload/checksum 후 성공 | 직접 관련 가능 | synthetic | fresh canonical publish 필요 |
| error classification | 일반 exception을 안정적 단계 code로 분류 | 직접 관련 | synthetic | 실제 원인 재현 여부는 미확정 |

[확정] 후속 코드는 **관측성과 격리 계약을 해결**했지만 **원래 내부 publish root cause를 해결했다고 증명하지 않았다**.

## 6. 데이터 적격성

### 6.1 실제 aggregate

| 항목 | 결과 |
|---|---|
| Source | AIHUB-71748 Run 0015, v0.2 sidecar lineage |
| 사용 범위 | 학생·비상업 로컬 연구로 제한; SFT 목적 취득 증빙과 파생물 재배포는 검증 필요 |
| Train·Validation | 17,639 / 1,287, Validation byte-identical |
| Schema | `instruction/input/output/system`, mismatch 0 |
| 빈 instruction·response | Train·Validation 모두 0 |
| Exact record duplicate excess | split 내부 0, cross-split overlap 0 |
| Original overlap | v0.1/v0.2 source 10,374행이 v0.3 Train prefix로 의도적으로 동일 |
| Short variant | 7,265행, 80~173 assistant token, lineage collision·missing parent 0 |
| 매우 짧은 original | 전체 original 계열에서 16 token 미만 22건, 32 미만 118건; 자동 부적격 기준은 미확정 |
| 언어 aggregate | Hangul char 비율 Train 0.9178·Validation 0.9127, Latin char 비율 0.0151·0.0174 |
| Category | 18,925 resolved, 1 ambiguous; domain category이며 safety category가 아님 |
| Safety·PII field | v0.3 sidecar에 없음 |
| Review queue | 539건은 학습 Dataset에서 제외, raw text 미포함 |
| Evaluation leakage | Dataset 자체 cross-split exact 0; 외부 benchmark source가 없어 contamination clear 불가 |

[검증 필요] source processing의 PII·duplicate·leakage 이력을 v0.3 package가 fingerprint로 계승하지만, 생성된 short
variant에 대한 독립 PII/safety classification evidence는 없다. extractive 생성이라 source 위험을 새로 만들 가능성은
제한되지만, 위험이 없음을 증명하지는 않는다.

**데이터 판정: `data_ready_with_conditions`**

조건은 다음과 같다.

1. AIHUB-71748 SFT 목적 이용·보관·파생 Adapter 로컬 사용 근거를 다시 연결한다.
2. v0.3 accepted 17,639행에 PII exclusion lineage와 safety review 결과를 aggregate-only로 연결한다.
3. 1건의 ambiguous category 처리 원칙과 32 token 미만 original의 포함 근거를 동결한다.
4. 외부 benchmark가 없다는 한계를 Runtime eligibility까지 유지한다.

## 7. Tokenization 적격성

| 항목 | 설계·코드 상태 | 실제 artifact 상태 |
|---|---|---|
| Base·Tokenizer | `Qwen/Qwen2.5-1.5B-Instruct` | 고정 후보 |
| Revision | `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` | source config에 고정 |
| Tokenizer fingerprint | `ad0a85da869c2e4577b9409df0c91e35be70f0395a20c94765c6f4fa02ea6a55` | config 값만 존재 |
| Chat Template | local tokenizer의 공식 template bytes 사용 | 독립 artifact hash 없음 |
| EOS / PAD | `151645` / `151643` | 코드 검증 있음 |
| Assistant-only mask | prompt `-100`, assistant와 마지막 EOS 학습 | 코드·unit test 있음 |
| EOS | 정확히 하나의 마지막 assistant label | 코드·unit test 있음 |
| Packing | `false` | config 고정 |
| Truncation | 1024/1152/1280/1536 중 lossless 최소값 | 실제 선택값 없음 |
| Empty/all-masked | encode 단계에서 empty target 차단 | 실제 artifact 통계 없음 |
| Overlength | 1536까지 lossless 후보 분석 | 실제 결과 없음 |
| Determinism | 고정 tokenizer·record 순서·row fingerprint 설계 | 실제 output fingerprint 없음 |
| Train·Validation token 통계 | 생성하도록 구현 | canonical 결과 없음 |

[확정] canonical tokenized artifact가 없으므로 training input으로 사용할 수 없다. read-only recovery할 파일도 없으며,
기존 ID를 사용한 metadata-only republish도 불가능하다. 새 Run ID에서 Dataset·Tokenizer를 다시 검증하고 Tokenization을
재실행한 뒤 새 artifact를 atomic publish해야 한다.

**Tokenization 판정: `not_ready_missing_canonical_artifact`**

## 8. QLoRA 설정 검토

| 항목 | 현재 v0.3 초안 | 판정 |
|---|---|---|
| Base·revision | Qwen2.5-1.5B-Instruct·고정 revision | 유지 후보 |
| Quantization·dtype | 4-bit NF4·double quant·BF16 | v0.1/v0.2와 동일, GPU smoke 필요 |
| LoRA | r16·alpha32·dropout0.05 | 유지 후보, 동결 전 검증 |
| Target modules | q/k/v/o, gate/up/down proj | 유지 후보 |
| Batch·accumulation | 1 / 16 | 유지 후보 |
| Sequence length | tokenization manifest에서 resolve | canonical artifact 전 미확정 |
| Learning rate | `1e-4` | v0.1/v0.2 `2e-4`보다 보수적 후보 |
| Scheduler·warmup | cosine·0.03 | 후보 |
| Epoch·steps | 1 epoch·예상 1,103 step | artifact row/sampler 검증 전 예상치 |
| Checkpoint | 220 step, 220/440/660/880/1103 평가 | terminal 1103 보존 규칙 명시 필요 |
| Evaluation interval | generation step만 있음 | validation loss interval 미정 |
| Seed | 42 | data seed·sampler epoch seed를 별도 고정해야 함 |
| Gradient checkpointing | true | 유지 후보 |
| Optimizer | 없음 | **blocking** |
| Gradient clipping | 없음 | **blocking** |
| Early stopping | 없음 | 명시적 사용/미사용 결정 필요 |
| Output path | 없음 | 외부 immutable root 계약 필요 |
| Resume | 없음 | 기본 fresh-only·자동 resume false 제안 |
| 실행 backend | v0.3 전용 entrypoint 없음 | **blocking**; v0.2 hard-coded backend 직접 사용 불가 |

### 8.1 v0.1·v0.2 반복 위험

- EOS는 label 계약만으로 충분하지 않다. checkpoint별 EOS 종료·max-length를 smoke부터 측정한다.
- short variant 7,265행이 있어도 original 10,374행과 sampler 순서 때문에 짧은 응답 과적합 또는 원문 장문 회귀가 가능하다.
- v0.2 hard blocker는 EOS·max-length를 목표로만 두어 후보 선정 전 별도 decoding gate가 필요했다. v0.3에서는
  처음부터 candidate hard blocker로 승격한다.
- 빈 출력, 반복, prompt echo, 미완결, maximum-length 종료를 checkpoint별 조기 중단 신호로 사용하되 임계값을
  낮춰 억지로 통과시키지 않는다.
- v0.2의 terminal checkpoint schedule failure를 반복하지 않도록 scheduled step과 terminal step을 합친 exact
  inventory를 학습 전에 검증한다.

## 9. 평가 Gate

[제안] 다음 threshold와 추가 평가는 v0.3 실행 전 review 대상이며 아직 승인·구현된 설정이 아니다. 기존 기준을
완화하거나 제거하지 않는 방향으로 동결해야 한다.

| 구분 | 정책 |
|---|---|
| 기존 gate 유지 | Base 이하 Character F1·ROUGE-L, empty, special-token exposure, repetition 50% 초과 차단 |
| hard blocker 승격 | EOS `<70%`, max-length `>20%`, incomplete `>25%`, 비결정성은 candidate 차단 |
| PASS 목표 유지 | EOS `>=80%`, repetition `<=15%`, max hit `<=10%`, incomplete `<=15%`, Base 이상 품질 |
| 새 평가 추가 | prompt echo, format following, 한국어 품질, short-answer correctness, safety, latency, repeated-run stability |
| 제거 금지 | v0.1/v0.2의 기존 quality·empty·special-token·repetition 검사를 삭제하지 않음 |

### 9.1 Gate 층위

- **Smoke gate**: non-empty, finite generation, EOS token contract, special-token 비노출, deterministic fingerprint.
- **Candidate selection gate**: 40개 고정 prompt에서 위 hard blocker, quality·format·Korean·short-answer·safety 통과.
- **Runtime eligibility gate**: candidate gate와 Base 회귀, dependency·manifest, latency·stability, 실제 Loader smoke를 모두 통과.

[검증 필요] prompt echo·format·한국어·short-answer correctness·safety·latency threshold와 평가 fixture는 별도 설계
Task에서 동결한다. 기존 기준을 완화하지 않는다.

## 10. Readiness blocker

| ID | 등급 | 설명·상태 | 근거 | 해결 작업·검증 | 승인 | 차단 단계 |
|---|---|---|---|---|---|---|
| `V03-BLOCK-001` | critical | SFT 이용조건·취득 증빙·파생 Adapter 로컬 사용 경계 미완료 | Terms review `not_approved` | 비공개 증빙 fingerprint와 허용 범위 기록 | 사용자 | V03-2 이후 전부 |
| `V03-BLOCK-002` | blocking | canonical tokenized artifact 없음 | final·staging·failed 부재 | 새 ID에서 checksum·reload·lineage 포함 publish | 사용자 | Training |
| `V03-BLOCK-003` | blocking | 원래 publish 내부 원인 `UNRESOLVED` | terminal exception·failure artifact 없음 | 후속 hardening 검토, metadata-only preflight, fresh run 단계 evidence | 사용자 | Republish |
| `V03-BLOCK-004` | blocking | Tokenization single-use Approval·Runtime request enforcement 없음 | entrypoint가 Git/path만 검증 | 실행 capability·identity 소비 계약 설계·synthetic 검증 | 사용자 | Republish |
| `V03-BLOCK-005` | blocking | v0.3 executable QLoRA config·entrypoint 없음 | readiness YAML만 존재 | optimizer·clip·eval·output·resume 포함 resolved config와 backend | 사용자 | GPU smoke |
| `V03-BLOCK-006` | blocking | 평가 Gate가 Runtime eligibility에 불충분 | format·Korean·safety·latency 미정 | 기존 gate 유지+추가 fixture·threshold 동결 | 사용자 | Candidate selection |
| `V03-BLOCK-007` | conditional | v0.3 short variant의 독립 PII·safety evidence 없음 | sidecar field inventory | aggregate-only lineage 검증 | 필요 | Tokenization 승인 |
| `V03-BLOCK-008` | conditional | 외부 benchmark contamination clear 불가 | fixed local benchmark 없음 | 미검증 한계 유지 또는 승인 benchmark 계약 | 필요 | Runtime eligibility |
| `V03-BLOCK-009` | informational | Adapter·manifest·GPU load 없음 | 학습 미시작 | V03-8~10 이후 생성 | 필요 | Runtime READY |

## 11. 재개 경로 비교

| 경로 | 장점 | 위험·재현성 | 승인·비용 | Evidence 재사용 | 추천 |
|---|---|---|---|---|---|
| A. 기존 tokenization artifact 복구 | 재계산 최소 | 실제 artifact·checksum·manifest가 없어 실행 불가 | 승인 필요, 비용 낮음 가정 자체 불성립 | Dataset만 재사용 | `not_available` |
| B. Tokenization 재실행 | canonical Dataset과 후속 observable writer 사용, 가장 직접적 | 원래 내부 원인은 미확정; 새 backend gate 필요 | 새 Run·승인 필요, 중간 비용 | Dataset·config 후보·synthetic test 재사용 | **conditionally_recommended** |
| C. 데이터부터 재구성 | 데이터 계약 변경을 반영 가능 | immutable 계보 변경, GPU 생성 비용·검증·승인 최대 | 새 Dataset·Tokenization 승인 모두 필요 | source evidence만 재사용 | 현재 `not_recommended` |

[확정] 권장 경로는 **B**다. 단, `V03-BLOCK-001`, `003`, `004`, `007`을 먼저 닫고 새 identity를 승인받는
조건부 추천이다. Dataset checksum 또는 이용조건·safety gate가 실패할 때만 C를 재검토한다.

## 12. 실행 전 Gate 계획

| Gate | 입력 | 실행 | 산출물 | 통과·실패 조건 | 승인 주체 | 다음 단계 |
|---|---|---|---|---|---|---|
| V03-1 Data lineage·license | v0.3 manifest·source terms·aggregate | metadata-only 검증 | readiness evidence | checksum·lineage·허용범위·PII/safety 연결 모두 통과; 누락 시 실패 | 사용자 | V03-2 |
| V03-2 Canonical Tokenization | 새 Run ID·승인·Dataset·Tokenizer | fresh tokenization·atomic publish | tokenized package·manifest·statistics·checksum | lossless, mask/EOS, reload, checksum, no residue; 실패 artifact 필수 | 사용자 | V03-3 |
| V03-3 QLoRA config freeze | V03-2 manifest | 설정 review·fingerprint | immutable resolved config | 필수 field·step/checkpoint 계산·fresh-only 일치 | 사용자 | V03-4 |
| V03-4 CPU/static preflight | config·artifact·Git | load 없이 schema·lineage·schedule 검증 | preflight evidence | mismatch 0, execution call 0 | Codex, 실행 승인은 사용자 | V03-5 |
| V03-5 GPU 1-step smoke | 승인 ID·V03-4 | 1 optimizer step | smoke artifact | finite loss/grad, Base frozen, LoRA update, no offload, checkpoint reload | 사용자 | V03-6 |
| V03-6 Small overfit | 승인된 small train-only fixture | 제한 step overfit·resume 검증 | overfit evidence | loss 개선, EOS/non-empty, exact resume, VRAM 범위 | 사용자 | V03-7 |
| V03-7 Full training approval | V03-1~6 evidence | 승인 발급만 수행 | single-use approval | identity·config·budget·output unused | 사용자 | Full training |
| V03-8 Evaluation | immutable checkpoints·fixed prompts | loss·generation·safety·stability 평가 | canonical evaluation artifact | hard blocker 0, deterministic fingerprint; 미달 시 후보 없음 | 사용자 | V03-9 |
| V03-9 Candidate selection | V03-8 결과 | eligible set에서 명시적 선택 | selection record | eligible 1개 이상; 아니면 `no_eligible_candidate` | 사용자 | V03-10 |
| V03-10 Runtime manifest eligibility | selected Adapter·Base·metadata | manifest/validator/Loader GPU smoke | immutable manifest·runtime evidence | Task 1~4 strict 검증·Chat/SSE/unload 통과 | 사용자 | Runtime READY 검토 |

[확정] V03-1·V03-2의 schema·evidence·identity·Approval·request·preflight·worker·publish 실행 전 계약은
[Recovery Contract](./dohalm-v0.3-recovery-contract.md)에 작성됐다. 계약 설계 완료는 V03-1 evidence 통과 또는
V03-2 실행 승인이 아니다. 라이선스는 `evidence_insufficient`, data evidence는 `pending`, fresh Tokenization은
`not_approved`다.

## 13. 실행 Task

| Task | 목적 | 예상 변경 파일 | 기존·필요 테스트 |
|---|---|---|---|
| V03-1 | publish failure evidence와 data terms closure | readiness·failure 문서, 별도 evidence 문서 후보 | Markdown·checksum read-only |
| V03-2 | 새 identity·Approval·preflight 계약 설계 | 새 config/계약 문서, tokenization entrypoint·runtime module 후보 | identity·zero-call·approval mismatch unit |
| V03-3 | canonical tokenization recovery 구현 | `src/training/v03_tokenization*.py`, CLI, tests | 단계 failure injection·actual metadata preflight |
| V03-4 | QLoRA config freeze | 신규 executable v0.3 config | strict config·step/checkpoint schedule |
| V03-5 | v0.3 training backend 연결 | 신규 v0.3 entrypoint/module 또는 검증된 공통 backend 최소 확장 | CPU/static·no execution·artifact lineage |
| V03-6 | GPU smoke | 코드 변경 없이 승인된 실행 우선 | 1-step·checkpoint reload·VRAM |
| V03-7 | small overfit·resume | 필요 시 test harness 최소 확장 | finite·loss·EOS·resume |
| V03-8 | full training | 코드 변경보다 승인된 실행 | checkpoint inventory·failure preservation |
| V03-9 | evaluation·selection | 평가 config·v0.3 evaluator 최소 확장 | hard blocker·fingerprint·privacy |
| V03-10 | Runtime manifest·GPU E2E | 승인 artifact root의 manifest·metadata, 필요 시 frontend status | Adapter Validator·Loader·Provider·Chat/SSE·unload |

[확정] 이 표의 파일은 후속 Task 후보이며 이번 작업에서 생성·수정하지 않았다. 실제 Task 시작 때 적용 AGENTS·ADR와
clean worktree를 다시 확인한다.

## 14. 최종 판단

```yaml
v0.3_dataset: created_checksum_verified_conditions_open
v0.3_data_eligibility: data_ready_with_conditions
v0.3_tokenization_publish: failed_or_pending_recovery
v0.3_tokenized_artifact: absent
v0.3_recovery_design: completed
v0.3_recovery_contract: design_completed
v0.3_data_evidence: pending
v0.3_fresh_tokenization: not_approved
v0.3_training: not_started
v0.3_training_ready: false
v0.3_adapter: absent
runtime_candidate_selection: no_eligible_candidate
final_readiness: ready_for_recovery_design
execution_allowed: false
```

- 지금 가능한 작업: Recovery Contract의 `V03-R1`, `V03-R3`, `V03-R4`, `V03-R5` schema·순수 validator 구현.
- 아직 금지된 작업: 기존 ID 재사용, Tokenization·publish 재실행, GPU smoke, QLoRA, 평가, Adapter manifest 생성.
- 사용자 승인 시점: 실제 PII·Safety·Leakage scan/review, V03-1 판정, 새 identity 예약, Approval·request·preflight,
  fresh Tokenization 실행, GPU smoke, small overfit, full training, 평가와 Runtime 승격 각각.
- 예상 최소 경로: `V03-R1~R9 구현·synthetic 검증 → V03-1 evidence 승인·실행·판정 → 새 identity·Approval·request·preflight → 별도 승인 fresh Tokenization → V03-3~10`.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | V03-1·V03-2 Recovery Contract 설계 완료와 license evidence 부족·data evidence pending·fresh Tokenization 미승인 경계 연결 |
| 2026-08-05 | 실제 Dataset·checksum과 비어 있는 tokenization destination을 재검증하고 `ready_for_recovery_design`, 조건부 경로 B, V03-1~10 Gate 계획 작성 |
