# DohaLM 실험 관리 정책

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 규칙](../governance/development-rules.md), [사전학습 계획](./pretraining-plan.md), [평가 계획](../evaluation/evaluation-plan.md), [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md), [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md) |
| 후속 문서 | [재현성 정책](../quality/reproducibility-policy.md), [실험 템플릿](./experiment-template.md), `17-development-roadmap.md`, `18-testing-checklist.md`, `20-leaderboard-strategy.md` 작성 예정 |
| 구현 전 필수 여부 | 본 학습 전 예 |

- [확정] 현재 `experiments/` 경로, 실험 metadata 파일, 실행 결과와 schema 구현은 없다.
- [확정] 이 문서는 계획 구조이며 이번 단계에서 실험 디렉터리나 YAML을 생성하지 않는다.

## 2. 실험 단위

하나의 실험은 다음 조합으로 식별한다.

```text
코드 버전
+ 모델 설정
+ 토크나이저 버전
+ 데이터 버전
+ split 버전
+ 학습 설정
+ seed
+ 실행 환경
```

- [확정] 위 구성 중 하나라도 결과에 영향을 주도록 바뀌면 같은 experiment ID의 기존 기록을 덮어쓰지 않는다.
- [확정] 재시도는 run ID 또는 명시적 attempt 필드로 구분하고 parent experiment를 연결한다.
- [확정] 비교 목적과 변경 변수·고정 변수를 실행 전에 기록한다.

## 3. 실험 ID

- [가정] 권장 형식은 `EXP-NNNN-purpose`다. 예: `EXP-0001-tiny-overfit`.
- [확정] 숫자 부분은 저장소·registry 안에서 고유해야 하고 purpose는 짧은 영문 kebab-case 후보로 둔다.
- [검증 필요] ID 발급 방식, 자릿수와 동시 작업 충돌 방지는 구현 전에 확정한다.
- [확정] 전체 hyperparameter, 긴 데이터셋명, 사용자 로컬 경로와 비밀정보를 ID에 넣지 않는다.
- [확정] 날짜·설정·데이터 등 상세 정보는 metadata에 저장하고 ID는 안정적인 참조로 유지한다.

## 4. 필수 실험 메타데이터

| 필드 | 목적 | 값 상태·규칙 |
|---|---|---|
| `experiment_id` | 안정적 실험 식별 | 필수, 고유 |
| `name` | 사람이 읽는 이름 | 필수 |
| `purpose` | 검증 질문·목적 | 필수 |
| `status` | 생명주기 상태 | 정의된 enum |
| `created_at` | 기록 생성 시각 | timezone 포함 후보 |
| `started_at` | 실행 시작 시각 | 실행 전 null 가능 |
| `ended_at` | 종료 시각 | 종료 전 null 가능 |
| `git_commit` | 코드 revision | commit SHA; 필수 |
| `git_branch` | 실행 branch | branch명 또는 detached 상태 |
| `working_tree_clean` | commit 외 변경 여부 | boolean과 dirty diff 보존 정책 |
| `model_name` | DohaLM-Tiny/Small 식별 | 필수 |
| `model_config_version` | 모델 설정 snapshot | 필수 |
| `tokenizer_id` | tokenizer 계보 | 필수 |
| `tokenizer_version` | tokenizer version | 필수 |
| `dataset_id` | 입력 데이터 식별 | 목적별 하나 이상 가능 후보 |
| `dataset_version` | 원천·정제 데이터 version | 필수 |
| `split_version` | train/validation/test 분할 | 필수 |
| `preprocessing_version` | 전처리·packing 계보 | 필수 |
| `random_seed` | 대표 실행 seed | 필수; 상세 seed map과 연결 |
| `python_version` | runtime 환경 | 필수 |
| `pytorch_version` | framework 환경 | 필수 |
| `cuda_version` | CUDA runtime/build 정보 | GPU 실행 시 필수 |
| `gpu_name` | GPU 모델 | `RTX 3060 Ti` 기준 실측 기록 |
| `gpu_vram` | 장비 VRAM | byte·표시 단위 함께 기록 후보 |
| `precision` | FP16 mixed precision 등 | 필수 |
| `micro_batch_size` | VRAM 직접 batch | 학습 시 필수, 값 미정 |
| `gradient_accumulation_steps` | 누적 횟수 | 학습 시 필수, 값 미정 |
| `effective_batch_size` | 유효 sequence·token batch | 산식·padding 기준과 함께 기록 |
| `context_length` | 운영 sequence 길이 | 필수 |
| `learning_rate` | 기준 LR | 학습 시 필수, 값 미정 |
| `weight_decay` | decay 값·group 정책 | 학습 시 필수, 값 미정 |
| `warmup` | step 또는 비율 | 단위와 함께 기록, 값 미정 |
| `optimizer` | 종류·parameter group | 학습 시 필수 |
| `scheduler` | 종류·step 기준 | 학습 시 필수 |
| `max_steps` | 최대 optimizer step | 값 미정; token budget과 관계 기록 |
| `token_budget` | 목표 처리 token | 값 미정; 유효 token 정의 필요 |
| `checkpoint_interval` | 저장 주기 | 단위 포함, 값 미정 |
| `evaluation_interval` | 평가 주기 | 단위 포함, 값 미정 |
| `output_directory` | 실행 결과 논리 위치 | 로컬 절대경로를 공개 metadata에 고정하지 않음 |
| `result` | 요약·주요 지표·artifact 참조 | 종료 후 기록 |
| `failure_reason` | 실패 유형·원인·마지막 정상 상태 | 실패·중단·invalid 시 필수 |
| `notes` | 예외·한계·후속 작업 | 선택, 비밀정보 금지 |

- [확정] metadata는 최종 적용된 resolved config를 가리키며 입력 기본값만 기록하지 않는다.
- [확정] 정확한 schema와 YAML 여부는 [검증 필요]이며 이번 단계에서 설정 파일을 만들지 않는다.

## 5. 실험 상태

| 상태 | 진입 조건 | 종료·전이 조건 |
|---|---|---|
| `planned` | 목적·가설·변수가 초안으로 등록됨 | 필수 입력과 기준이 준비되면 `ready`; 취소 사유 기록 후 `archived` 후보 |
| `ready` | 코드·설정·데이터·평가·자원 게이트 검토 완료 | 실행 시작 시 `running`; 선행 조건 취소 시 `planned`/`invalid` |
| `running` | 시작 시각·환경·resolved config가 고정되고 실행 중 | 정상 종료 `completed`; 오류 `failed`; 의도적 중단 `stopped` |
| `completed` | 계획한 실행·필수 평가·결과 기록 완료 | 후속 검토 후 `archived`; 오류 발견 시 `invalid` |
| `failed` | 비의도적 오류로 목적 달성 실패 | 원인 보존 후 새 experiment/attempt로 재시도; `archived` 가능 |
| `stopped` | 사용자·중단 기준에 따라 의도적으로 종료 | 사유·마지막 상태 보존 후 새 실험 또는 `archived` |
| `invalid` | 누수·잘못된 설정·손상 등으로 결과 비교에 사용 불가 | 원인과 영향 보존; 결과를 성공 근거로 사용하지 않음 |
| `archived` | 신규 실행·수정 대상이 아니며 계보 보존 | 재검토 시 새 experiment를 만들고 원본은 유지 |

- [확정] `completed`는 좋은 결과를 뜻하지 않고 계획된 실행과 기록이 정상 종료됐다는 뜻이다.
- [확정] 상태 전이 시 시각, 수행자·자동화 주체와 이유를 남긴다.

## 6. 실패 실험 보존

다음 실패도 metadata, 적용 설정, 환경, 마지막 정상 로그와 가능한 artifact 참조를 보존한다.

| 실패 유형 | 필수 기록 |
|---|---|
| CUDA OOM | 발생 단계·shape·batch·context·allocated/reserved·다른 process |
| NaN 또는 Inf | 최초 step·loss·gradient·AMP scaler·입력 batch 식별자 |
| Loss 미감소 | 구간·초기/최종 loss·LR·데이터·mask·gradient 진단 |
| 데이터 손상 | dataset·shard·checksum·오류 record와 영향 범위 |
| Checkpoint 복원 실패 | checkpoint ID·hash·schema·누락/불일치 key·환경 |
| 시간 초과 | 제한 시간·진행 step/token·처리량·병목 후보 |
| 사용자 중단 | 중단 주체·시각·사유·마지막 정상 상태 |
| 환경 문제 | driver·CUDA·disk·process·dependency 오류 |
| 설정 오류 | 잘못된 field·resolved value·validation 누락 |
| 평가 누수 발견 | 데이터·split·prompt·benchmark 영향과 무효화 범위 |

- [확정] 실패 기록을 삭제하거나 성공 실험 결과로 덮어쓰지 않는다.
- [확정] 재시도는 새 experiment ID 또는 attempt ID를 사용하고 원 실패를 parent로 연결한다.
- [확정] 평가 누수가 확인된 결과는 `invalid`로 전환하고 보고서·선택 결정에서 제외한다.

## 7. 실험 디렉터리 계획

다음은 계획 구조이며 현재 생성하지 않는다.

```text
experiments/
  EXP-0001-example/
    metadata.yaml
    resolved-config.yaml
    result.md
    metrics.csv
    samples.jsonl
    environment.txt
```

| 계획 파일 | 책임 | Git 추적 후보 |
|---|---|---|
| `metadata.yaml` | 실험 ID·상태·계보·참조 | 소형·비밀정보 제거 후 후보 |
| `resolved-config.yaml` | 최종 적용 설정 snapshot | 후보; 구현 전 schema 결정 |
| `result.md` | 목적·결론·실패·다음 작업 | 추적 후보 |
| `metrics.csv` | step/token별 지표 | 요약만 후보, 대용량 원본 제외 |
| `samples.jsonl` | 고정 prompt 생성 원본 | 비민감 선별본만 후보 |
| `environment.txt` | runtime·GPU·dependency 기록 | 비밀·로컬 경로 정제 후 후보 |

- [확정] checkpoint와 optimizer state는 `checkpoints/` 또는 별도 대용량 artifact 경로에 두고 experiment metadata에서 ID·hash로 참조한다.
- [확정] 대용량 로그·profiler trace·제한 데이터 출력은 Git에 포함하지 않는다.
- [검증 필요] `experiments/` 생성 시점, 실제 schema, 외부 artifact backend와 보존 기간은 구현 전에 확정한다.

## 8. 비교 실험 원칙

- [확정] 변경 변수와 고정 변수를 명시하고 가능한 한 한 번에 하나의 질문을 검증한다.
- [확정] 동일 validation split, tokenizer, 평가 코드·prompt·generation 설정을 유지한다.
- [확정] seed 하나의 우연한 결과와 반복 seed 결과를 구분한다.
- [확정] Gradient Checkpointing 전후는 loss·gradient·VRAM·tokens/sec를 함께 비교한다.
- [확정] context length가 바뀌면 처리되는 데이터·padding·비용도 달라질 수 있음을 기록한다.
- [검증 필요] 반복 횟수와 통계적 비교 방법은 자원과 평가 목적에 따라 결정한다.

## 9. 산출물 연결

- [확정] experiment ID는 Git commit, resolved config, dataset·preprocessing·split version, tokenizer ID와 model config version을 연결한다.
- [확정] checkpoint, 평가 결과, 생성 sample, 로그와 환경 기록은 artifact ID·hash 또는 논리 경로로 참조한다.
- [확정] `latest`, `best`, 최종·실패 분석 checkpoint 역할을 구분한다.
- [확정] artifact가 삭제돼도 manifest에는 식별자·삭제 시각·사유와 재생성 가능성을 남긴다.

## 10. 미결정 사항

- [검증 필요] experiment ID 발급 방식과 run/attempt 구분
- [검증 필요] metadata·resolved config schema와 validation 도구
- [검증 필요] 평가·checkpoint 주기와 보존 개수·기간
- [검증 필요] Git 추적 가능한 metrics·sample 크기 한도
- [검증 필요] `experiments/`와 `artifacts/`의 실제 경계 및 외부 저장 backend
- [검증 필요] 반복 seed 수와 비교 통계

## 11. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 실험 단위·ID 후보·metadata·상태·실패 보존·계획 디렉터리 정책 정의 |
