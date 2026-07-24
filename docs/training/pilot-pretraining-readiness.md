# Pilot Pretraining 준비 검증

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [사전학습 계획](./pretraining-plan.md), [Gate 4·5·6 Evidence 검토](../quality/gate4-6-evidence-review.md), [데이터셋 승인 로그](../data/dataset-approval-log.md)
- 후속 문서: 승인 tokenizer·corpus 연결 작업, 실제 Pilot Pretraining 실행 계획
- 구현 전 필수 여부: 실제 Pilot Pretraining 전 필수

## 1. 목적

- [확정] `src/training/pilot_readiness.py`는 실제 tokenizer와 development corpus를 학습 코드에 연결하기 전에 Gate·artifact·데이터 승인·운영 준비 조건을 fail-closed로 검사한다.
- [확정] `configs/pretrain.yaml`에 명시적인 `pilot_readiness` 승인 metadata가 없으면 일반 `data.source` 값을 실제 pilot 승인으로 확대 해석하지 않는다.
- [확정] validator는 준비 상태를 보고할 뿐 config, Gate 문서, tokenizer·corpus 승인 상태를 변경하지 않는다.

## 2. 필수 조건

| 범주 | 필수 조건 |
|---|---|
| Gate | Gate 3·4·5·6 `passed`, Gate 7 `passed` 또는 별도 pilot 정책 `approved` |
| Tokenizer | approval `approved`, SHA-256 fingerprint, vocab 16,000, special token ID 0~7 |
| Corpus | `approved_tokenizer_development`, license `approved`, PII `clear` 또는 승인된 conditional |
| 계보 | corpus manifest checksum, dataset fingerprint, train/validation split 검증 |
| 평가 보호 | evaluation 제외 검증 |
| 운영 | 저장공간, checkpoint 보존, training config, scheduler, batch·accumulation 승인 |
| 복구·예측 | 예상 시간·VRAM 범위와 중단·resume 절차 |

## 3. 현재 결과

- [확정] 현재 결과는 `blocked`다.
- [확정] Gate 4·5·6은 사용자 승인으로 `passed`다. Gate 3과 Gate 7은 `planned`다.
- [확정] 실제 운영 tokenizer와 목적별 승인 corpus artifact·fingerprint가 연결되지 않았다.
- [확정] storage·retention·training config·scheduler·batch·시간/VRAM·resume 운영 승인이 없다.

주요 차단 code:

- `GATE3_NOT_PASSED`, `GATE7_POLICY_NOT_SATISFIED`
- `TOKENIZER_NOT_APPROVED`, `TOKENIZER_FINGERPRINT_MISSING`
- `CORPUS_NOT_APPROVED`, `LICENSE_NOT_APPROVED`, `PII_NOT_CLEARED`
- `SPLIT_NOT_VERIFIED`, `EVALUATION_EXCLUSION_MISSING`
- `TRAINING_CONFIG_NOT_APPROVED`, `STORAGE_NOT_VERIFIED`

추가 운영 차단 code는 Gate 7 정책, vocabulary·special token, corpus manifest·dataset fingerprint, retention·scheduler·batch·예측·resume 조건을 구분한다.

## 4. 입력 계약

명시적인 준비 metadata는 다음 논리 구조를 따른다. 이는 예시이며 현재 `configs/pretrain.yaml`에 추가하거나 승인값을 채우지 않는다.

```yaml
pilot_readiness:
  gates: {}
  tokenizer: {}
  corpus: {}
  training: {}
  storage: {}
```

- [확정] SHA-256 fingerprint는 `sha256:` 접두사와 64자리 소문자 16진수 계약을 사용한다.
- [확정] `approved_by`, `approved_at`은 사용자 승인 전 `null`이다.
- [제외] 기존 fixture용 `data.source.license_status: approved`는 실제 corpus 목적 승인 근거가 아니다.

## 5. 실행

```powershell
python -m scripts.training.validate_pilot_readiness `
  --config configs/pretrain.yaml `
  --json
```

정상적인 현재 출력은 종료 코드 0과 `status: blocked`다. 차단은 도구 실패가 아니라 준비 조건 미충족을 뜻한다. 입력 계약이나 파일 자체가 유효하지 않으면 종료 코드 2와 간결한 오류를 반환한다.

## 6. 실제 Pilot 전 사용자 승인 항목

- [검증 필요] Gate 3과 Gate 7 상태 또는 별도 pilot 정책
- [검증 필요] 운영 tokenizer bundle과 fingerprint
- [검증 필요] 목적별 corpus·license·PII 승인과 manifest·split·평가 제외
- [검증 필요] resolved training config, scheduler, batch·accumulation
- [검증 필요] 저장공간·checkpoint 보존·예상 시간/VRAM·resume 절차

- [제외] 위 조건이 충족되기 전 AI Hub corpus 연결, 장시간 학습과 실제 Pilot 실행

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] Gate 4·5·6 `passed`를 반영하고 Gate 3·7 및 tokenizer·corpus·license·PII 차단을 유지함 |
