# DohaLM 평가 프레임워크

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- 태그: `evaluation`, `reproducibility`, `privacy`, `checkpoint`

이 디렉터리는 동일한 내부 평가 데이터와 운영 tokenizer로 DohaLM-Tiny 산출물을 비교하는 계약을 설명한다. 평가 실행은 `model.eval()`과 `torch.inference_mode()`만 사용하며 optimizer, scheduler, backward 또는 parameter 갱신을 허용하지 않는다.

## 문서 목록

- [평가 계획](./evaluation-plan.md)
- [평가 데이터 정책](./evaluation-dataset-policy.md)
- [평가 지표](./evaluation-metrics.md)
- [생성 평가](./generation-evaluation.md)
- [체크포인트 비교 정책](./checkpoint-comparison-policy.md)
- [모델 평가 리더보드](./model-evaluation-leaderboard.md)
- [평가 Readiness](./evaluation-readiness.md)
- [Candidate A Final Quick 결과](./candidate-a-final-quick-result.md)
- [Candidate A Final Full 결과](./candidate-a-final-full-result.md)
- [Initial·Pilot·Candidate A 동일 Quick 비교](./initial-pilot-candidate-a-quick-comparison.md)
- [EOS·불완전 블록 진단](./eos-incomplete-block-diagnostic.md)
- [Quick·Full 대표성 정책](./quick-full-representativeness-policy.md)
- [Candidate B 평가 계약](./candidate-b-evaluation-contract.md)
- [평가 manifest 예시](./evaluation-manifest.example.yaml)
- [외부 benchmark 정책](./benchmark-policy.md)

## 공개 설정과 실행

- 공개 설정: [`configs/evaluation.example.yaml`](../../configs/evaluation.example.yaml)
- artifact registry: [`configs/evaluation-artifacts.example.yaml`](../../configs/evaluation-artifacts.example.yaml)
- synthetic prompt set: [`configs/evaluation-prompts.example.yaml`](../../configs/evaluation-prompts.example.yaml)
- CLI: `python -m scripts.evaluation.run_evaluation --mode inspect`

실제 경로는 기존 `configs/local-datasets.yaml`의 external root mapping으로만 해석한다. 실행 결과는 Git 외부의 `configured_external_root/analysis/evaluation/`에 atomic publish한다.

## 마일스톤 상태

- Framework implementation, Candidate A Quick/Full, checkpoint Quick comparison, EOS diagnostic: `completed`
- Quick representativeness, EOS success, Candidate B evaluation contract: `approved` (2026-07-27)
- Quick v2: `planned_awaiting_separate_approval`
- Candidate B design/backend: `review_backend_ready_awaiting_commit_preflight_and_approval`
- Candidate B training: `not_approved`
- 배포: `not_applicable`

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Candidate B backend ready와 실제 평가 미실행·학습 미승인 경계 반영 |
| 2026-07-28 | Candidate B 25M readiness package 작성과 training 미승인·실행 차단 상태 반영 |
| 2026-07-27 | 평가 프레임워크 문서 인덱스와 공개 경계 작성 |
| 2026-07-27 | Candidate A Final Quick 결과 연결 |
| 2026-07-27 | Initial·Pilot·Candidate A 동일 Quick 비교 결과 연결 |
| 2026-07-27 | Candidate A Final Full Evaluation 결과 연결 |
| 2026-07-27 | EOS·불완전 블록 진단과 Quick 대표성·Candidate B 평가 계약 제안 연결 |
| 2026-07-27 | ADR-007과 세 평가 정책 승인 및 Evaluation Framework 마일스톤 완료 상태 반영 |
