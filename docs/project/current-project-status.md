# DohaLM Current Project Status

- 문서 상태: `review`
- 기준 시점: 2026-07-29
- 기준 학습 commit: Run 0001 `bdcf85d4fd60aefb15178ec4041735737bb86b1b` / Run 0002 `4c2eced3bf70551fbf7bc8ebde6666062584d92b`
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
| Foundation framework | `completed` | Base data·tokenizer·training·evaluation·lineage·approval 체계 |
| DohaLM Base Tiny | `completed` | Candidate B current baseline, Candidate A historical baseline |
| Candidate A Full baseline | `historical` | ADR-007 당시 baseline; ADR-009 이후 회귀 비교용 보존 |
| Candidate B design/backend | `fix_validated` | numeric checkpoint validation·quarantine 보존 정책 포함 |
| Candidate B first execution | `failed` | 12,208 step 후 checkpoint 문자열 정렬 버그; 공식 결과 없음 |
| Candidate B Run 0002 training | `completed` | 12,208 step, 25,001,984 token, retry/resume/extension 없음 |
| Candidate B Final Quick | `completed` | 기존 final checkpoint evaluation-only 결과 |
| Candidate B Final Full | `completed` | same-artifact Quick reference, 불변성·checksum 검증 통과 |
| Candidate B official result | `evaluated_contract_not_passed` | teacher-forced 개선, greedy EOS·maximum-length 조건 미충족 |
| EOS Generation·Decoding diagnostic | `completed` | 동일 A/B prompt, greedy 128 EOS 0%; assisted-only 종료 |
| ADR-008·모델 단계별 EOS 정책 | `approved` | teacher-forced/generation, pure/assisted, Base/Instruct/Chat 계약 분리 |
| Candidate B ADR-008 reassessment | `approved_as_base_baseline` | ADR-009; historical 계약 판정과 분리 |
| Current official Base baseline | `candidate_b` | Full·EOS teacher-forced·position·stability 개선, generation 비악화 |
| Candidate B derivative parent | `approved_experimental` | 실제 파생 학습·publication은 미승인 |
| DohaLM Instruct | `design_completed` | ADR-010·schema·template·evaluation·safety·readiness 문서 |
| Instruct processing backend | `implemented_synthetic_validated` | 메모리 전용 Rule·Manifest schema·Validation·Statistics, 실제 Processing 미승인 |
| Instruct execution | `not_approved` | AIHUB-71748 SFT conditionally selected, processing·SFT backend not_started, execution_allowed false |
| Chat·Code·SQL·Recruit·Game·Agent | `not_started` | 각 family 별도 design·data·학습 승인 필요 |

첫 실패 Run 0001과 성공 Run 0002의 Approval·failure evidence는 외부 제한 경로에서 read-only로 보존한다.
Run 0002 checkpoint 4,883/9,766/12,208, Final Quick·Full과 EOS ranking 진단이 완료됐다.
Candidate B 학습은 다시 실행하지 않는다.

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
- [확정] Candidate A Final Full은 historical internal baseline이며 수치·fingerprint를 회귀 기준으로 보존한다.
- [확정] Candidate B Final Full은 ADR-009에 따른 현재 공식 Base baseline이다.
- [확정] Final Quick은 `approximately_representative`이며 optimistic bias가 있어 공식 판정은 Full을 사용한다.
- [확정] EOS 4,799 input과 4,782 target 차이는 label shift에 따른 position-0 제외 17건으로 완전히 설명됐다.
- [확정] ADR-008, 모델 단계별 EOS Success Policy, Quick representativeness policy와 Candidate B historical Evaluation Contract는 approved다.
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
- Quick Evaluation: `completed`; Full Evaluation: `completed`; EOS diagnostic: `completed`.
- Teacher-forced loss·Top-k·EOS rank는 Candidate A보다 개선됐지만 greedy EOS 0%와 maximum-length 100%로 계약 미통과.
- 동일 조건 16/32/64/128-token 진단에서도 pure greedy EOS는 0%; 상태 제안은 `decoding_assisted_termination_only`, 공식 상태는 불변.
- Training Run 0002: `completed`; 추가 training/retry/resume/extension: `not_approved`.
- Historical contract: Candidate B `evaluated_contract_not_passed`; ADR-008 reassessment:
  `approved_as_base_baseline`.
- Official Base baseline: Candidate B Final Full; Candidate A: `historical_base_baseline: true`.
- Candidate B derivative parent eligibility: `approved_experimental`; 파생 학습·publication은 `not_approved`.

## 7. 미승인·미착수

- Candidate B 추가 training, Candidate C, Candidate B resume/retry/extension
- Quick v2 생성
- SFT, RLHF, Preference Training
- Instruct·Chat·Code·SQL·Recruit·Game·Agent·Vision/Multimodal 학습
- Model/checkpoint/tokenizer/dataset publication과 deployment
- Service decoding 채택·구현, Instruct·Chat EOS numeric thresholds
- Instruct·Chat·Domain CPT·EOS-aware SFT 실행과 data contract
- Instruction dataset processing·다운로드·생성, SFT backend와 Instruct evaluation 실행

## 8. Instruct Project

- Parent: Candidate B Final, immutable, `approved_experimental`.
- Version 후보: `dohalm-instruct-tiny-v1`; 실제 model artifact는 `not_created`.
- Dataset: AIHUB-71748 SFT Component `CONDITIONALLY_SELECTED`; Processing Backend는 Synthetic 검증 완료, 실제 Processing·Manifest 생성은 미승인·미실행.
- Prompt·Evaluation·Tool Calling·Safety: framework 설계 완료, 구현·수치 threshold 미승인.
- Chat lineage: `Base → Instruct → Chat`; Chat project는 `not_started`.
- Readiness: `design_completed`, `execution_allowed: false`, training·publication `not_approved`.

### AIHUB-71748 Processing Run 상태

- [확정] Run 0008은 Approval no-replace 보안 수정에 따른 backend fingerprint 불일치로
  `retired_backend_fingerprint_mismatch`, Approval 0008은 `retired_not_issued`다.
- [확정] Run 0009 metadata-only Preflight와 Live Refresh 뒤 발급된 Approval 0009는 공식 retirement service로
  `retired_before_consumption` 전환됐다. Run 상태는 `retired_runtime_request_governance_mismatch`다.
- [확정] RuntimeExecutionRequest v1 공식 writer·CLI는 합성 검증을 통과했다. 실제 Run 0009 request,
  Approval consume, Dataset payload·Processing은 모두 0건이며 `execution_allowed=false`다.
- [확정] issued·미소비 Approval의 public retirement artifact service·별도 lifecycle evidence·lock/CAS·CLI가
  합성 검증됐고 Approval 0009에 공식 적용됐다. Run 0010 Preflight는 실행하지 않았다.

## 9. 다음 권장 작업

1. Run 0010 Metadata-Only Preflight를 신규 identity로 별도 승인
2. Prompt serialization·mask·EOS와 evaluation numeric 계약 별도 승인
3. SFT Backend 구현·CPU fail-closed 검증은 별도 작업으로 승인

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-30 | Approval 0009 공식 retirement와 Run 0009 영구 폐기; Run 0010 미생성 유지 |
| 2026-07-30 | issued Approval retirement service 합성 구현; Approval 0009·Run 0010 실제 상태 유지 |
| 2026-07-30 | RuntimeExecutionRequest v1 writer·CLI 구현과 Run 0009 Approval issued·unconsumed 상태 반영 |
| 2026-07-30 | Run 0008 backend fingerprint mismatch 폐기와 Run 0009 metadata-only Preflight 통과 상태 반영 |
| 2026-07-29 | AIHUB-71748 SFT 공식 조건부 선정과 Processing·Backend·Training 미승인 상태 반영 |
| 2026-07-28 | ADR-010 DohaLM Instruct design_completed·execution_not_approved 상태 반영 |
| 2026-07-28 | ADR-009 Candidate B current Base baseline 승격과 experimental derivative parent 적격성 반영 |
| 2026-07-28 | ADR-008·모델 단계별 EOS 정책 승인과 Candidate B 재평가·derivative parent 미승인 경계 반영 |
| 2026-07-28 | 동일 Candidate A/B EOS generation·decoding 진단 완료와 공식 상태 불변 반영 |
| 2026-07-28 | Candidate B Full·EOS ranking·Candidate A/B 비교 완료와 계약 미통과 판정 반영 |
| 2026-07-28 | Candidate B Run 0002 학습·checkpoint·Quick 완료와 Full evaluator blocker 반영 |
| 2026-07-28 | Candidate B 첫 실행 실패·승인 소비·checkpoint 미보존과 validator/quarantine 보완 상태 반영 |
| 2026-07-28 | Gate 0~7, tokenizer, Pilot, Candidate A, Evaluation과 Candidate B 현재 blocker 통합 snapshot 작성 |
