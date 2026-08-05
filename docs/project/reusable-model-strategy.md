# DohaLM Reusable Model and Runtime Strategy

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 공식 Phase: `phase_2: reusable_model_and_runtime`

## 1. 목적

Phase 2는 Runtime 코드만 만드는 단계가 아니라, 평가와 identity가 고정된 **재사용 가능한 DohaLM 모델 artifact**와 이를
로드하는 Runtime을 만드는 단계입니다.

## 2. 공식 흐름

```text
Qwen Base / Instruct
  → Korean · General SFT
  → QLoRA Adapter 또는 merged model
  → Evaluation
  → Versioned DohaLM Model
  → Inference Runtime
```

Qwen 계보는 Phase 1 Candidate B/C의 파생 계보가 아닐 수 있습니다. 양쪽은 manifest, checksum, evaluation evidence와
versioning이라는 공통 출력 계약으로 수렴합니다.

## 3. 현재 상태

| 구성 | 상태 | 근거 |
|---|---|---|
| General Instruct Adapter | `no_eligible_candidate` | v0.1~v0.3 evidence·이용조건·artifact 판정상 승인 후보 없음 |
| Manifest·Validator | `implemented_verified` | strict validation과 fail-closed 계약 구현 |
| PEFT Loader·Provider | `implemented_mock_verified` | mock lifecycle 검증; 실제 승인 artifact 미검증 |
| Adapter Runtime | `unavailable_without_approved_artifact` | 코드 구현과 실제 사용 가능 상태를 분리 |
| Qwen v0.3 recovery | historical evidence preserved | recovery 기록은 유효하지만 후보 승인과 동일하지 않음 |

## 4. 완료 조건

1. license·lineage·checksum이 완전한 eligible model 또는 Adapter를 선정합니다.
2. 평가 결과와 manifest identity를 versioned release candidate에 결속합니다.
3. 실제 artifact로 loader·provider·GPU smoke를 통과합니다.
4. unsupported 또는 불일치 artifact를 fail closed 처리합니다.
5. Phase 3가 사용할 안정된 model·Runtime compatibility contract를 제공합니다.

세부 Adapter 계약은 [Adapter Runtime](../service/dohalm-adapter-runtime.md), 계보 분리는
[Instruct Strategy](../instruct/instruct-strategy.md)를 따릅니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Phase 2를 reusable model artifact와 Runtime의 결합 단계로 정의 |
