# DohaLM Foundation Model Strategy

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 공식 Phase: `phase_1: foundation_model_development`

## 1. 목적과 범위

Phase 1은 Dataset·Tokenizer부터 직접 구현 Base model의 학습·평가·선정까지 검증하는 현재 최우선 연구 트랙입니다.
Runtime이나 외부 애플리케이션 구현을 Foundation 완료 조건에 포함하지 않습니다.

```text
Dataset → Tokenizer → DohaLM-Tiny → Base Pretraining → Evaluation → Foundation Base
```

## 2. 핵심 모델 목표

| 목표 | 역할 | 현재 상태 |
|---|---|---|
| Candidate B | current Foundation Base baseline과 Candidate C 비교 기준 | `completed` |
| Candidate C | 단일 EOS 가설을 검증할 experimental successor | contract design `completed`, execution `blocked` |
| Foundation Instruct | Foundation Base 파생 SFT 연구 계보 | `planned`, parent decision pending |

Candidate A는 historical baseline으로 보존합니다. Candidate C가 학습되더라도 Evaluation과 별도 selection 승인 없이는
Candidate B를 대체하지 않습니다. ADR-010은 Candidate B parent 설계를 승인하고 있으므로 Candidate C 기반 Foundation Instruct는
후속 ADR 없이는 실행할 수 없습니다.

## 3. 현재 근거 조사와 향후 실행 분리

### 현재 근거 조사

```text
Candidate A/B Evidence
  → Candidate B EOS Diagnostic Review
  → Dataset · Tokenizer · Config Review
  → Candidate C Readiness Decision
```

Base Training Readiness review와 Candidate C contract design은 완료됐습니다. EOS 현상과 기존 진단은 확인됐지만 단일 root
cause는 확정되지 않았습니다. EOS-DIAG-R1/R2는 synthetic 검증됐고 실제 Candidate B identity freeze는 불완전하며 진단
Gate 1·2는 통과하지 않았습니다.

### 향후 Candidate C 실행

```text
Dataset Freeze
  → Tokenizer Freeze
  → Training Config Freeze
  → GPU Smoke
  → Training
  → Evaluation
  → Candidate Selection
```

```text
base_training_readiness_review: completed
candidate_c_contract_design: completed
candidate_c_readiness: blocked
candidate_c_execution_allowed: false
candidate_c_training_started: false
```

상세 blocker와 C-1~C-8은 [Base Training Readiness](../training/base-training-readiness.md)와
[Candidate C Design](../training/candidate-c-design.md)을 따릅니다.

## 4. Gate 관계

기존 Gate 1~7은 저장소 Foundation capability와 historical Tiny 검증입니다. Candidate C 전용 Gate C-1~C-8은 새 실행의
identity·freeze·GPU·학습·평가·선정을 통제하므로 기존 Gate 통과로 자동 충족되지 않습니다. EOS Diagnostic Gate 1·2도
Candidate B read-only evidence의 실제 identity와 승인 입력을 동결하는 별도 진단 gate입니다.

## 5. 다른 Phase와의 관계

Phase 2 [Reusable Model and Runtime](./reusable-model-strategy.md)은 Qwen 기반 별도 계보를 사용할 수 있으며 Phase 1 완료를
계보 선행조건으로 삼지 않습니다. 현재 우선순위가 Phase 1이라는 사실과 Phase 2 병행 가능성은 구분합니다. 두 Phase는
manifest·evaluation·versioning이라는 공통 산출물 체계로 연결됩니다.

`Publish Recovery`라는 모호한 Foundation 작업명은 사용하지 않습니다. Foundation artifact publication은 model·checkpoint·
tokenizer·dataset별 별도 승인이고, Qwen v0.3 recovery는 Phase 2 이력입니다.

## 6. 불변 원칙

- 기준 하드웨어는 단일 `RTX 3060 Ti 8GB`입니다.
- Candidate 간 Dataset·Tokenizer·config·checkpoint·evaluation identity를 명시합니다.
- EOS teacher-forced, pure generation과 decoding-assisted 결과를 분리합니다.
- 새 threshold를 임의로 만들지 않고 기존 Evaluation Framework를 재사용합니다.
- 학습, candidate selection과 publication 승인을 각각 분리합니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Phase 1 직접 모델 연구 범위, Phase 2 병행 계보와 공통 출력 체계 명시 |
| 2026-08-05 | A/B 근거 조사와 Candidate C 실행 흐름·Gate·상태 분리 |
