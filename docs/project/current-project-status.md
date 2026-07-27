# DohaLM Current Project Status

- 문서 상태: `review`
- 기준 시점: 2026-07-28
- 기준 브랜치/실패 실행 commit: `feat/candidate-b-design` / `bdcf85d4fd60aefb15178ec4041735737bb86b1b`
- 관련 근거: [개발 Roadmap](../quality/development-roadmap.md), [Candidate A 결과](../training/full-pretraining-candidate-a-result.md), [Evaluation Framework](../evaluation/README.md), [Candidate B Readiness](../training/candidate-b-readiness.md)

## 1. 통합 상태

| 영역 | 상태 | 근거 |
|---|---|---|
| Gate 0 | `approved` | 사용자 승인 |
| Gate 1~7 | `passed` | Roadmap과 Gate evidence |
| 운영 Tokenizer | `approved` | `operating-16k-v2/unigram-16k`, vocab 16,000, UNK 0%, exact round-trip 100% |
| Dataset lineage | `completed` | canonical pilot-v2 Training lineage·split·PII·tokenization·packing fingerprint |
| Tiny Overfit | `passed` | 64문서, 1,000-step, packed Top-1 99.9047%, exact continuation |
| Pilot runtime smoke | `passed` | canonical pilot-v2 5-step |
| Pilot 100-step | `completed` | 100 optimizer step, 204,800 token, approval consumed |
| Candidate A 10M | `completed` | 4,883 step, 10,000,384 scheduled token |
| Evaluation Framework | `completed` | Quick·Full·EOS·position·category·stability·privacy·lineage |
| Candidate A Full baseline | `approved` | ADR-007과 Final Full result |
| Candidate B design/backend | `fix_validated` | numeric checkpoint validation·quarantine 보존 정책 포함 |
| Candidate B first execution | `failed` | 12,208 step 후 checkpoint 문자열 정렬 버그; 공식 결과 없음 |
| Candidate B training | `not_approved` | 기존 승인 소비; 새 실행 승인 없음 |
| Candidate B rerun | `awaiting_separate_approval` | `execution_allowed: false`; 새 commit·Run ID·Approval 필요 |

첫 실행의 Failure Manifest와 approval consumption record는 외부 제한 경로에서 read-only로 보존한다. 실행은 12,208 step에 도달했지만 checkpoint가 제거돼 Quick/Full Evaluation과 공식 Candidate B 결과는 없다. 이번 수정은 새 실행 승인이 아니며 병합 후에도 `execution_allowed: false`를 유지한다.

## 2. Gate 최신 상태

| Gate | 상태 | 핵심 결과 |
|---|---|---|
| 0 | `approved` | 프로젝트 범위 승인 |
| 1 | `passed` | 환경·설정 기반 |
| 2 | `passed` | 데이터 pipeline 계약 |
| 3 | `passed` | 운영 16k v2 Unigram |
| 4 | `passed` | 모델 component |
| 5 | `passed` | 통합 forward/loss/generation |
| 6 | `passed` | Trainer·AMP·checkpoint/resume |
| 7 | `passed` | 실제 corpus Tiny Overfit |

## 3. Dataset와 Tokenizer

- [확정] AIHUB-71748 license는 `approved_student_noncommercial`; 상업 이용과 원본·파생 데이터 재배포는 `not_approved`다.
- [확정] source package registry는 제공자 version·취득 증빙이 미확정이므로 `reviewing`을 유지한다.
- [확정] 이와 별개로 승인된 canonical `pilot-v2` derivative와 고정 training lineage는 Pilot과 Candidate A에 사용됐다.
- [확정] AI Hub 원래 Validation, 외부 benchmark, SFT·RLHF·preference 데이터는 Base 학습에 사용하지 않았다.

## 4. Pilot와 Candidate A

- Pilot: `PILOT-100-V2-20260727-0001`, 100 step, 204,800 token, NaN/OOM/AMP skip 0.
- Candidate A: `FULL-PRETRAIN-CANDIDATE-A-20260727-0001`, 4,883 step, 10,000,384 token, NaN/OOM/AMP skip 0.
- Candidate A Final Full: loss 6.369027, PPL 583.4899, Top-1/5/10 16.8417%/29.2154%/35.5767%.
- Candidate A 실행 승인은 소비됐고 추가 학습·resume·publication은 승인되지 않았다.

## 5. Evaluation

- [확정] Initial/Pilot/Candidate A Mid/Final 동일 Quick 비교와 Candidate A Final Full을 완료했다.
- [확정] Candidate A Final Full은 공식 internal baseline이다.
- [확정] Final Quick은 `approximately_representative`이며 optimistic bias가 있어 공식 판정은 Full을 사용한다.
- [확정] EOS 4,799 input과 4,782 target 차이는 label shift에 따른 position-0 제외 17건으로 완전히 설명됐다.
- [확정] EOS success policy, Quick representativeness policy와 Candidate B Evaluation Contract는 approved다.
- Quick v2는 `planned_awaiting_separate_approval`이다.

## 6. Candidate B 현재 상태

- Budget: 25,000,000 requested / 25,001,984 scheduled token, 12,208 step.
- Initialization: fresh seed 17, Candidate A checkpoint/state 재사용 금지.
- Checkpoint: 4,883 / 9,766 / 12,208.
- Quick: start / 4,883 / final. Full: training 종료 후 final evaluation-only 1회.
- 첫 실행: `FULL-PRETRAIN-CANDIDATE-B-20260728-0001`, 12,208 step 도달 후 `failed`.
- 첫 Approval: `CANDIDATE-B-APPROVAL-20260728-0001`, atomic consumed, 재사용 불가.
- 실패 원인: checkpoint 이름의 lexicographic ordering; checkpoint는 기존 cleanup으로 미보존.
- 보완: numeric ordering·invalid/missing/duplicate/unexpected/final/metadata 진단과 향후 quarantine 정책 구현.
- Quick/Full Evaluation: `not_run`; 공식 Candidate B 결과: `unavailable`.
- `execution_allowed: false`, training `not_approved`, rerun `awaiting_separate_approval`.

## 7. 미승인·미착수

- Candidate B training, Candidate C, Candidate B resume/retry/extension
- Quick v2 생성
- SFT, RLHF, Preference Training
- Instruct·Chat·Code·SQL·Recruit·Game·Agent·Vision/Multimodal 학습
- Model/checkpoint/tokenizer/dataset publication과 deployment

## 8. 다음 권장 작업

1. 수정·테스트가 병합된 새 immutable commit 후보 검토
2. 별도 새 Run ID와 single-use Approval 발급 여부 결정
3. 별도 승인 시 실행 직전 physical preflight와 모든 fingerprint 재검증
4. 새 실행이 정상 완료된 경우에만 Quick·Full Evaluation 수행

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate B 첫 실행 실패·승인 소비·checkpoint 미보존과 validator/quarantine 보완 상태 반영 |
| 2026-07-28 | Gate 0~7, tokenizer, Pilot, Candidate A, Evaluation과 Candidate B 현재 blocker 통합 snapshot 작성 |
