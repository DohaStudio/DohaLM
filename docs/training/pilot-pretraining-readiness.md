# Pilot Pretraining 준비 검증

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 선행 문서: [사전학습 계획](./pretraining-plan.md), [Gate 4·5·6 Evidence 검토](../quality/gate4-6-evidence-review.md), [데이터셋 승인 로그](../data/dataset-approval-log.md)
- 후속 문서: [Pilot 실행 준비 계획](./pilot-pretraining-execution-plan.md), 승인 corpus 연결 작업
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
| Corpus | `approved_pilot_pretraining`, license `approved_student_noncommercial`, PII `clear` 또는 승인된 conditional |
| 계보 | corpus manifest checksum, dataset fingerprint, train/validation split 검증 |
| 평가 보호 | evaluation 제외 검증 |
| 운영 | 저장공간, checkpoint 보존, training config, scheduler, batch·accumulation 승인 |
| 복구·예측 | 예상 시간·VRAM 범위와 중단·resume 절차 |

## 3. 현재 결과

- [확정] 현재 결과는 `ready_awaiting_final_execution_approval`이다. Source lineage와 pilot-v2 Runtime Smoke 재검증은 완료됐고 100-step 최종 실행 승인만 남아 있다.
- [확정] Gate 3·4·5·6·7은 사용자 승인으로 `passed`다.
- [확정] 운영 v2 Unigram과 tokenizer development corpus identity는 확정됐고, 제한 Gate 7 실험에서 실제 Training 64문서 연결을 검증했다.
- [확정] 제한 실험은 Pretraining 목적 승인, PII clearance, train/validation split 또는 Pilot 정책 승인을 대체하지 않는다.
- [확정] example config, 실행 manifest, 외부 logical directory, checkpoint·logging·resume·중단 정책은 검토 가능한 초안으로 준비됐다.
- [확정] 외부 출력 경로의 쓰기·atomic rename·read/checksum·임시 파일 삭제와 994,569,031,680 bytes 가용 공간을 확인했다.
- [확정] corpus 목적 승인·PII 자동 제외·manifest·95/5 split·dataset fingerprint와 config·scheduler·batch·retention 조건을 충족했다.
- [확정] 기존 5-step 자원 Smoke는 v1 runtime evidence로만 보존하며 canonical pilot-v2 학습 evidence로 승격하지 않는다.
- [확정] canonical pilot-v2 전용 `SMOKE-PILOT-V2-0001`은 정확히 5 optimizer step, finite metric, checkpoint checksum·load-only resume와 mismatch 차단을 통과했다.

과거 주요 차단 code:

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

정상적인 현재 validator 출력은 blocker 0건인 `ready_for_user_approval`이다. 운영 문서 상태는 실행 승인이 아직 없음을 명확히 하는 `ready_awaiting_final_execution_approval`이며 100-step 실행 미승인을 유지한다.

## 6. 실제 Pilot 전 사용자 승인 항목

- [확정] 목적별 corpus·license·PII 자동 제외와 manifest·split·평가 제외
- [확정] resolved training config, scheduler, batch·accumulation
- [확정] 저장공간·checkpoint 보존·자원 Smoke·resume 차단 절차
- [확정] 48 record source selection 차이 전수 분류와 canonical pilot-v2 계보 검증
- [확정] pilot-v2 Runtime Smoke 재검증은 승인 범위인 5 optimizer step에서 통과
- [검증 필요] 이후 100-step Pilot 최종 실행 승인

- [제외] 위 조건이 충족되기 전 AI Hub corpus 연결, 장시간 학습과 실제 Pilot 실행

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] canonical pilot-v2 전용 5-step Runtime Smoke, checkpoint checksum·load-only resume·mismatch 차단을 통과해 `RUNTIME_REVALIDATION_REQUIRED`를 해제하고 최종 실행 승인 대기 상태로 전환함 |
| 2026-07-27 | [확정] byte-quota 제어 흐름 버그로 발생한 pilot-only 48건을 전수 분류하고 canonical 107,226건·corpus SHA를 재현한 pilot-v2를 검증해 `SOURCE_LINEAGE_NOT_VERIFIED`를 해소함; runtime 재검증은 미승인 |
| 2026-07-27 | [확정] 5-step Smoke 통과 후 기존 tokenizer corpus 107,226건과 Pilot replay 107,274건의 계보 불일치를 발견해 `SOURCE_LINEAGE_NOT_VERIFIED`로 다시 차단함; 추가 step과 100-step 실행은 미수행 |
| 2026-07-27 | [확정] Pilot example config·실행 manifest·외부 디렉터리·checkpoint/logging·중단 정책과 inspection-only CLI를 준비하고 11개 blocker 및 실행 미승인을 유지함 |
| 2026-07-27 | [확정] Gate 7 `passed`를 반영해 Gate 차단은 해소했으나 Pilot·Pretraining 목적 승인, PII, split, config와 storage 조건이 남아 readiness `blocked`를 유지함 |
| 2026-07-27 | [확정] Gate 3과 운영 tokenizer 확정, 제한 Gate 7 실험 결과를 반영하되 Gate 7·PII·Pretraining·Pilot 차단을 유지함 |
| 2026-07-24 | [확정] Gate 4·5·6 `passed`를 반영하고 Gate 3·7 및 tokenizer·corpus·license·PII 차단을 유지함 |
