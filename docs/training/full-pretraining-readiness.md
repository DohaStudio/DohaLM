# Full Pretraining Readiness

- 문서 상태: `approved`
- 마지막 검토일: 2026-07-27
- 관련 문서: [실행 계획](./full-pretraining-execution-plan.md), [승인 manifest](./full-pretraining-approval.manifest.yaml), [Pilot 결과](./pilot-pretraining-100-v2-result.md)

## 현재 판정

- [확정] Candidate A 단일 실행은 `completed`이며 [결과 문서](./full-pretraining-candidate-a-result.md)에 검증 evidence를 기록했다.
- [확정] single-use 승인은 소비됐고 `execution_allowed: false`, `training_started: true`이다.
- [확정] 실행 backend와 runtime/checkpoint validation은 `passed`이다.
- [확정] 동일 승인 재사용과 기존 Run ID/output 재사용은 차단한다.
- [확정] 승인 전 readiness fingerprint는 `sha256:fc5c74313d31070a1304e61d93ad94117c03cc59b606329144888fecb3073683`이다.
- [확정] 완료 후 재실행 차단 fingerprint는 `sha256:b50590c592a28fc2f508f1a3fefa37630531f17dacd79833fc3b3c852e622893`이다.

## 검증된 범위

| 범위 | 결과 |
|---|---|
| Gate와 Pilot | Gate 0~7 충족, canonical Pilot 완료, checkpoint/resume 통과 |
| 데이터 계보 | Dataset, source lineage, PII, split, tokenization, packing fingerprint 일치 |
| Tokenizer와 Model | 운영 tokenizer checksum/fingerprint와 DohaLM-Tiny fingerprint 일치 |
| Candidate A | 10M 목표, 10,000,384 scheduled token, 4,883 step 강제 |
| 정책 | 초기화, 학습, 평가, checkpoint, retention, disk, wall-clock, system safety 승인 |
| 저장소 | 외부 output probe와 10GiB 시작 여유 공간 조건 검증 |
| Backend | inspection 기본, dry-run 지원, 명시적 `--execute` 분리, fail closed 테스트 통과 |

## 실행 전 수동 확인

최종 실행 승인 시 Windows 절전 비활성화, 재시작·업데이트 예약 없음, 전원 연결, 냉각·환기, NVIDIA/CUDA 인식, 다른 장시간 GPU 작업 부재를 확인하고 승인 기록에 남긴다. 확인 실패 시 실행하지 않는다.

## Inspection과 dry-run

```powershell
python -m scripts.training.run_full_pretraining `
  --config configs/full-pretraining.example.yaml `
  --manifest docs/training/full-pretraining-approval.manifest.yaml `
  --json

python -m scripts.training.run_full_pretraining `
  --config configs/full-pretraining.example.yaml `
  --manifest docs/training/full-pretraining-approval.manifest.yaml `
  --dry-run `
  --json
```

두 명령은 model 또는 optimizer를 만들지 않고 학습을 시작하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | [확정] Candidate A 단일 실행 완료와 승인 소비·runtime/checkpoint validation 반영 |
