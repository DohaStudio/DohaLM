# DohaLM Current Project Status

- 문서 상태: `review`
- 기준 시점: 2026-07-28
- 기준 브랜치/commit: `feat/candidate-b-design` / `a6464becd1594febc0143bd8717bde0169bc1391`
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
| Candidate B design/backend | `completed` | resolver·scope·approval·Git·probe·runtime·runner |
| Candidate B training | `not_approved` | 실행 승인 없음 |
| Candidate B execution | `not_approved` | `execution_allowed: false`; clean immutable Git 재확정·physical preflight·single-use 승인 대기 |

이 문서 감사 시작 시점에는 기준 commit이 upstream과 일치하고 worktree가 clean이었다. 현재 문서 최신화 변경은 아직 미커밋이므로 Candidate B 실행 직전에는 clean worktree와 새 immutable commit/upstream 일치를 다시 확정해야 한다. 버전 관리된 readiness YAML은 backend commit 전 snapshot으로 유지되며 이번 문서 작업에서 변경하지 않는다.

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
- Backend, resolved config, CPU smoke와 output probe는 완료됐다.
- [조사 시작 관측] HEAD와 upstream은 `a6464bec...1391`로 일치하고 worktree는 clean이어서 backend의 pre-commit blocker는 당시 해소돼 있었다.
- [현재 blocker] 이 문서 변경을 포함한 clean immutable Git identity 재확정, `CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING`, `CANDIDATE_B_EXECUTION_APPROVAL_MISSING`.
- [정합성 주의] versioned readiness manifest와 status 문자열은 commit 전 snapshot을 보존하므로 `awaiting_commit`을 포함한다. YAML은 이번 문서 작업 범위에서 수정하지 않는다.
- `execution_allowed: false`, training `not_approved`, training started `false`다.

## 7. 미승인·미착수

- Candidate B training, Candidate C, Candidate B resume/retry/extension
- Quick v2 생성
- SFT, RLHF, Preference Training
- Instruct·Chat·Code·SQL·Recruit·Game·Agent·Vision/Multimodal 학습
- Model/checkpoint/tokenizer/dataset publication과 deployment

## 8. 다음 권장 작업

1. 이 장기 전략 문서 검토와 승인 여부 결정
2. Candidate B 실행 직전 physical preflight
3. 확정 commit·Run ID·resolved fingerprint에 결합된 single-use 실행 승인
4. 별도 승인 후 Candidate B 단일 실행과 post-training Full Evaluation

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Gate 0~7, tokenizer, Pilot, Candidate A, Evaluation과 Candidate B 현재 blocker 통합 snapshot 작성 |
