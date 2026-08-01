# DohaLM v0.2 Sidecar·Sampling Dataset

- 문서 상태: `implemented`
- 마지막 검토일: 2026-08-01
- Dataset ID: `DOHALM-V0.2-DATASET-SIDECAR-20260801-0001`

## 1. 목적과 범위

Run `AIHUB-71748-SFT-PROCESSING-20260730-0015`의 Train·Validation JSONL을
바이트 단위로 보존하면서 품질 Sidecar와 Train 전용 Sampling 정책을 결합한 외부
Dataset package를 만든다. 신규 QA 생성, 요약, 재작성, truncation, 행 변경,
JSONL EOS 삽입, Tokenization 및 학습은 이 단계의 범위가 아니다.

구현은 [설정](../../configs/data/dohalm-v0.2-sidecar-sampling.yaml)과
`scripts/datasets/build_dohalm_v02_sidecar.py`를 단일 정책 진입점으로 사용한다.
실제 경로는 CLI 인자로만 주입하며 저장소 설정에는 기록하지 않는다.

## 2. 콘텐츠 보존 계약

- `train.jsonl`과 `validation.jsonl`은 원본 byte, 크기, SHA-256, 행 수, 순서 및
  개행을 그대로 유지한다.
- 레코드를 추가·삭제·복제하거나 split 사이에서 이동하지 않는다.
- EOS는 Tokenization 산출물에서 `exactly_one_final_assistant_label` 계약만
  검증하며 Source JSONL에는 문자열이나 token을 넣지 않는다.
- Source package의 관리 대상 5개 checksum을 생성 시작과 게시 직전에 각각
  검증한다. 불일치하면 final을 게시하지 않는다.

## 3. Sidecar와 identity

`quality-sidecar.jsonl`은 Source와 동일한 순서와 전체 행 수를 가진다.
`record_hash`는 `SHA-256(canonical JSON({split, line_index, record}))`로 계산한다.
질문·답변 원문과 token sequence는 Sidecar 및 Review Queue에 저장하지 않는다.

Category는 원본 SFT component를 기존 join 계약으로 읽어 canonical record
content hash에 연결한다. 하나의 값만 확인되면 `resolved`, 둘 이상이면
`ambiguous`, 없으면 `unresolved`로 기록한다. 모호한 값을 추정하지 않는다.

길이는 assistant label token 수를 기준으로 다음 구간에 포함한다.

| Bucket | 포함 범위 |
|---|---:|
| `short` | 0–128 |
| `medium` | 129–256 |
| `long` | 257–512 |
| `very_long` | 513 이상 |

완결성 점수는 명확한 종결과 미완성 신호를 결합해 `1.00`, `0.75`, `0.50`,
`0.00`으로 고정한다. 반복 점수는 강한 신호 없음 `0`, 약한 n-gram·near
duplicate 신호 `1`, 동일 문장·강한 반복 `2`, 연속 문장 반복 `3`으로 고정한다.

## 4. Sampling 정책

목표 `short/medium/long/very_long = 0.25/0.35/0.30/0.10`은 물리적 행 비율이
아니라 Train sampler의 분석적 기대 분포다. 행을 복제하거나 삭제하지 않는다.

최종 가중치는 다음 순서로 계산한다.

1. 길이: `target ratio / observed ratio`, 범위 `0.25–2.00`.
2. Category: `sqrt(mean category count / category count)`, 범위 `0.75–1.35`.
3. 품질: 여러 신호를 곱하지 않고 가장 보수적인 단일 tier를 선택한다.
4. 결합값을 범위 `0.25–3.00` 안에서 평균 1이 되도록 투영한다.

Train ESS 비율이 `0.60` 미만이면 Fail Closed한다. Validation에는 Sampling
정책을 적용하지 않으며 모든 가중치를 `1.0`, shuffle을 `false`로 유지한다.

초기 상한 `3.00`은 실제 Train에서 ESS `0.553901`로 실패했다. Dataset 행과
ESS 기준을 유지한 채 길이 상한만 `2.00`으로 제한한 진단 후보는 ESS
`0.638948`을 기록했다. 따라서 목표 `25/35/30/10`을 달성했다고 과장하지 않고,
clamp 후 분석적으로 계산한 예상 분포와 목표 차이를 Statistics에 함께 기록한다.

## 5. 산출물과 fingerprint

최종 외부 package는 아래 8개 파일만 포함한다.

- `train.jsonl`, `validation.jsonl`
- `quality-sidecar.jsonl`, `review-queue.jsonl`
- `sampling-policy.yaml`, `manifest.yaml`, `statistics.json`
- `checksums.sha256`

Sidecar, Sampling policy, Statistics 및 Manifest semantic payload는 canonical
JSON SHA-256으로 각각 fingerprint한다. 전체 package fingerprint는 Source JSONL
두 checksum과 위 네 fingerprint를 이 순서로 묶은
`canonical-json-ordered-components-v1` payload의 SHA-256이다. 파일 checksum은
`checksums.sha256`에서 별도로 검증한다.

## 6. Writer와 Fail Closed

Writer는 final과 같은 부모의 exclusive staging directory에서 canonical
serialization, file flush·fsync, directory fsync, checksum 및 reload 검증을
완료한 뒤 atomic no-replace로 한 번만 게시한다. final·staging·failed identity가
이미 있거나 경쟁 writer가 먼저 final을 만들면 덮어쓰지 않는다.

Source checksum 변경, JSONL byte 변경, Sidecar 정렬·identity 불일치, Category
lineage 부재, 비정상 가중치, ESS 미달, Validation weight 변경, fingerprint·reload
실패는 모두 게시 전 실패 조건이다.

## 7. 현재 권한

```yaml
v2_dataset_generation: approved_once_after_merge
tokenization_started: false
training_started: false
execution_allowed: false
```

생성된 Dataset package는 Git에 추가하지 않는다. 후속 weighted
Tokenization/Dataloader 및 QLoRA는 별도 승인 대상이다.
