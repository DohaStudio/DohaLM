# DohaLM Inventory

- 문서 상태: `review`
- 마지막 검토일: 2026-08-11
- 경로 표기: 로컬 절대 경로는 `<REPO>`, `<LOCAL_DATASET_ROOT>`, `<LOCAL_MODEL_ROOT>`로 마스킹

## 1. Repository Inventory

`git ls-files` 기준 761개 파일이다. 핵심 분포는 docs 228, src 184, tests 145, scripts 87, frontend 41, configs 39, server 20이다.

| 영역 | 현재 구성 | 판정 |
|---|---|---|
| Model | `src/model` 17개; Decoder-only Tiny 구성요소·generation | 유지 후보 |
| Training | `src/training` 42개; pretraining, SFT, QLoRA, checkpoint/resume | 일반화 후 재사용 |
| Data | `src/data` 66개; adapter, 검증, processing, lineage | 거버넌스 핵심 재사용 |
| Evaluation | `src/evaluation` 23개; loss, generation, EOS, comparison, reporting | 음악 task metric 확장 필요 |
| Inference | `src/inference` 14개; provider, loader, Adapter manifest·validation | capability routing으로 리팩터링 후보 |
| Runtime | `src/runtime` 4개; environment, path, logging | 유지 후보 |
| Config | `src/config`, `configs/` | 단일 config 원칙 유지; 도메인 config 추가 필요 |
| REST·Streaming | `server/` FastAPI 20개; health, models, chat, SSE | transport 재사용 |
| Prompt | Qwen chat template, evaluation YAML, 문서상 template | 독립 Prompt Engine 미구현 |
| Frontend | Next.js local chat validation UI | 제품 UI가 아닌 검증 도구로 유지/분리 검토 |
| Manifest | Dataset·training·evaluation·Adapter별 YAML/JSON schema | 공통 artifact registry로 수렴 필요 |

상세 모듈은 `src/data`, `src/training`, `scripts/datasets`, `scripts/training`에 편중되어 있다. 음악 capability, reference audio feature extraction, similarity 계산 구현은 현재 저장소에 없다.

## 2. Local Asset Inventory

내용 원문은 열지 않고 metadata와 파일 형식만 조사했다.

| 마스킹 경로 | 파일/디렉터리 | 크기 | 내용과 상태 |
|---|---:|---:|---|
| `<REPO>/data` | 4/4 | 4 B | raw·cleaned·tokenized·sft placeholder만 존재 |
| `<REPO>/checkpoints` | 1/0 | 1 B | `.gitkeep`만 존재 |
| `<REPO>/artifacts` | 7/20 | 16.6 KB | 테스트·preflight YAML 중심; Git ignored |
| `<REPO>/.tmp` | 830/88 | 12.1 MB | 테스트 복제본·log·임시 archive; cache 성격 |
| `<LOCAL_DATASET_ROOT>` | 683/255 | 176.8 GB | AI Hub ZIP/JSON, processed JSONL, tokenizer, training/evaluation 결과, cache |
| `<LOCAL_MODEL_ROOT>` | 10/3 | 3.10 GB | 고정 Qwen2.5-1.5B-Instruct snapshot |
| 인접 Doha artifact/temp roots | 44/33 | 33.8 MB | music JSON·SQLite; DohaLM 코드 참조는 확인되지 않음 |

- [확정] `configs/local-datasets.yaml`이 `<LOCAL_DATASET_ROOT>`를 바인딩하며 Git ignore 대상이다.
- [확정] `.env.example`은 model snapshot, Adapter root, model cache root를 로컬 `.env`에만 두도록 한다.
- [확정] `<LOCAL_MODEL_ROOT>`에는 revision `989aa7…306`의 `model.safetensors`(약 3.087 GB), tokenizer와 config가 있다.
- [WARNING] `<LOCAL_DATASET_ROOT>/cache`에도 같은 Qwen snapshot이 있어 중복 저장 가능성이 있다. 이번 작업에서는 삭제하지 않았다.

### 자산 종류별 위치

| 요청 범주 | 확인 위치 | 판정 |
|---|---|---|
| datasets | `<LOCAL_DATASET_ROOT>/downloads`, `extracted`, `processed`, `pilot` | 실자산 존재 |
| models | `<LOCAL_MODEL_ROOT>`, `<LOCAL_DATASET_ROOT>/cache`, `models` | Qwen snapshot·tokenizer 존재 |
| checkpoint | `<REPO>/checkpoints`, 외부 `analysis/*/runs` | Git 내부는 placeholder; 외부는 manifest/summary 중심 |
| adapter | 외부 `training/smoke/*/checkpoint-1` | smoke weight만 확인; approved artifact 없음 |
| evaluation | 외부 `analysis/evaluation`, training/evaluation 문서 | 결과·비교·진단 계보 존재 |
| cache | `<REPO>/.tmp`, `.pytest_cache`, `.ruff_cache`, 외부 `cache/huggingface` | 재생성/중복 후보; 삭제 미수행 |
| logs | 독립 `<REPO>/logs`는 없음; metrics JSONL·`.tmp` log에 분산 | 통합 retention 정책 없음 |
| outputs | 외부 `analysis/*/runs`, `training/*` | run별 분산 저장 |
| results | JSON/YAML/JSONL result·summary·statistics | 중앙 result registry 없음 |

## 3. Dataset Inventory

| 종류 | 위치 | 상태 |
|---|---|---|
| Raw AI Hub | `<LOCAL_DATASET_ROOT>/downloads`, `extracted` | read-only·restricted; AIHUB-71748 등 5종 |
| 분석 | `analysis/*` | schema, sample aggregate, leakage, tokenizer, training/evaluation evidence |
| Instruct processed | `processed/instruct/AIHUB-71748` | General SFT 계보; 음악 목적 재사용 승인 없음 |
| Tokenized | `processed/tokenized/AIHUB-71748` | Qwen SFT 계보 |
| Pilot/Foundation | `analysis/pilot-pretraining`, `analysis/full-pretraining` | Tiny Candidate A/B 계보 |
| v0.2/v0.3 | configs·docs 및 외부 package | weighted/short-answer 연구 계보; eligible runtime candidate 없음 |

목표 task partition인 `lyrics_generation`, `lyrics_rewrite`, `planning`, `prompt_generation`, `track_edit`, `section_edit`, `mix_direction`, `similarity_revision`, `music_analysis`는 현재 registry에 없다.

## 4. Model Inventory

| 모델/계보 | 위치 | 현재 판정 |
|---|---|---|
| DohaLM-Tiny Candidate B | 외부 analysis 결과·문서 evidence | current Foundation baseline; EOS 제약 존재 |
| Candidate C | 설계·config proposal | readiness blocked, training not started |
| Qwen2.5-1.5B-Instruct Base | `<LOCAL_MODEL_ROOT>` 및 dataset cache | local offline snapshot 확인 |
| General Instruct QLoRA v0.1~v0.3 | config·result 계보 | no eligible candidate |
| Music-specific model/Adapter | 없음 | not_started |

## 5. Checkpoint·Adapter Inventory

- Foundation Candidate A/B의 checksum·summary·metrics는 `<LOCAL_DATASET_ROOT>/analysis`에 있으나 이번 metadata 조사에서 실제 weight 파일은 확인되지 않았다.
- QLoRA smoke의 `adapter_model.safetensors` 약 73.9 MB가 stage 1/2에 각각 존재한다.
- `DohaLM-v0.1` 본 실행 디렉터리는 `.failed`이며 metrics만 확인됐다.
- [확정] 승인 manifest·license·evaluation을 모두 충족하는 Runtime Adapter는 없다.

## 6. Prompt Inventory

| 종류 | 구현/위치 | 상태 |
|---|---|---|
| Inference chat | Qwen 공식 `chat_template` | partial implemented |
| Foundation evaluation | `configs/evaluation-prompts.example.yaml` | synthetic continuation probes |
| EOS evaluation | `configs/eos-generation-prompts.example.yaml` | synthetic diagnostic probes |
| QLoRA evaluation | `configs/evaluation/dohalm-v0.1-*` | 30개 synthetic QA 등 |
| Instruction template | `docs/instruct/instruction-prompt-template.md` | design only |
| Music Director prompts | 없음 | not_started |

## 7. Database·Manifest·Metadata Inventory

- [확정] DohaLM 저장소와 확인된 외부 DohaLM 자산에는 운영 SQLite DB가 없다.
- [확정] 상태 저장은 YAML config/manifest, JSON identity·summary·environment·statistics, JSONL dataset·metrics·lineage에 분산된다.
- [확정] 인접 music artifact/temp root에는 SQLite3 파일이 있으나 DohaLM 코드의 의존성은 확인되지 않았다.
- [WARNING] Dataset, model, Adapter, evaluation의 공통 질의·승격 registry가 없어 상태가 문서와 파일 트리에 분산된다.

## 8. 조사 한계

접근 거부된 일부 테스트 임시 디렉터리는 파일 metadata를 열람하지 못했다. 비공개 데이터 원문, 모델 tensor, checkpoint payload, 생성 원문은 안전 경계상 읽지 않았다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-11 | Repository와 Git 외부 로컬 자산의 metadata inventory 작성 |
