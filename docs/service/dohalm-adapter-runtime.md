# DohaLM General Instruct Adapter Runtime 설계

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 구현 상태: `adapter_artifact_validator_implemented_synthetic_validated`
- 기준 문서: [README](../../README.md), [Current Project Status](../project/current-project-status.md), [Instruct Strategy](../instruct/instruct-strategy.md)
- 선행 구현: [FastAPI 백엔드 MVP](./dohalm-backend-mvp.md), [Base Qwen Provider](./dohalm-base-qwen-provider.md), [Frontend MVP](./dohalm-frontend-mvp.md)

## 1. 목적과 범위

[확정] 이 문서는 Qwen Base와 별도 General Instruct QLoRA Adapter를 현재 로컬 Runtime에 연결하기 위한
Adapter Loader의 책임, manifest, 검증 순서, Provider lifecycle과 구현 Task를 정의한다. 기존 FastAPI Chat·SSE,
Provider Registry, Base Qwen loader와 Next.js MVP를 최대한 재사용한다.

[확정] Task 1은 immutable manifest model과 strict loader를 구현했고 Task 2는 manifest가 명시한 artifact의
존재·checksum·정적 내용과 계보를 synthetic test로 검증했다. PEFT Loader와 Provider 연결은 시작하지 않았으며,
어떤 v0.1/v0.2 Adapter도 Runtime 후보로 승인하거나 `deployment_ready`로 승격하지 않는다.

- [제외] Foundation Model Track과 Candidate B의 weight·Tokenizer·평가 계약 변경
- [제외] Base weight와 Adapter merge, 자동 Adapter 탐색, 네트워크 다운로드와 자동 fallback
- [제외] Docker, Kubernetes, Cloud와 운영 배포
- [제외] Memory, RAG, Tool Calling, Agent와 DohaMusic 구현

## 2. 현재 구현 분석

### 2.1 Backend와 inference

```text
FastAPI lifespan
  → ProviderRegistry
      ├── MockProvider
      ├── BaseQwenProvider
      └── DohaLMAdapterProvider       placeholder
  → InferenceService
  → POST /api/v1/chat
  → POST /api/v1/chat/stream
```

| 영역 | 현재 구현 | Adapter 연결 시 판단 |
|---|---|---|
| `ProviderRegistry` | 세 Provider를 application lifetime 단위로 고정 등록하고 unknown name을 startup에서 거부 | 기존 registry를 유지하되 Adapter 설정과 startup preflight를 주입해야 함 |
| `BaseQwenProvider` | 고정 revision, local-only, lazy load, 상태 lock, 단일 load task, semaphore, 취소·timeout·unload 구현 | lifecycle·동시성·generation/stream 코드를 재사용할 기준 구현 |
| `DohaLMAdapterProvider` | `not_available` health와 `ADAPTER_NOT_AVAILABLE`만 반환 | 실제 Loader를 소유하되 유효 Adapter가 없으면 현재 동작을 유지 |
| Base loader | 고정 Qwen snapshot, special token, GPU·VRAM·offload를 fail closed로 검증 | Base load 로직을 공유하고 Adapter 적용 전후 identity를 추가 검증 |
| generation | 공식 `apply_chat_template`, request generation mapping, worker 기반 streaming | 검증된 Tokenizer·Template·Generation Config를 사용하는 한 재사용 |
| FastAPI lifespan | registry 생성, active Provider health 호출, shutdown `close()` | metadata-only Adapter startup preflight를 명시적으로 호출하도록 확장 필요 |
| `/ready` | `READY`가 아니면 모두 `PROVIDER_NOT_READY` 503 | Adapter 원인을 `ADAPTER_NOT_AVAILABLE` 또는 `ADAPTER_INCOMPATIBLE`로 보존 필요 |
| `/models` | model/provider/status/capabilities만 공개 | 안전한 Adapter version·Base revision·runtime status를 선택적으로 추가 가능 |

[확정] 현재 `ProviderStatus`는 `ready`, `not_loaded`, `loading`, `unloading`, `not_available`, `unavailable`,
`error`만 지원한다. Adapter compatibility를 공개 상태로 구분하려면 `incompatible` 상태와 안전한 reason code가 필요하다.

[확정] `requirements-inference.txt`와 `pyproject.toml`의 inference extra에는 현재 `peft`가 없다. 실제 Loader 구현
Task에서 학습 artifact의 `peft_version`과 일치하는 고정 runtime dependency를 별도 검증해야 한다.

### 2.2 Instruct artifact와 계보

- v0.1 training backend는 `final-adapter/`에 `adapter_model.safetensors`, `adapter_config.json`,
  `training-config.yaml`, `environment.json`, `tokenizer-reference.json`, `training-result.yaml`과 checksum을 기록한다.
- v0.1 Tokenizer fingerprint는 문서화돼 있으나, 실제 배포 후보의 Adapter·평가 fingerprint와 파일 checksum은
  외부 artifact에서 다시 검증해야 한다.
- v0.2는 2 epoch·1,298 step 학습 완료 기록이 있으나 post-processing failure와 evaluation-only recovery가
  `pending`이다. 현재 `deployment_ready=false`이며 자동 후보가 아니다.
- v0.3은 Tokenization publish 실패 상태이고 QLoRA 실행이 승인되지 않았다.
- Qwen Runtime Adapter는 Candidate B 기반 Foundation Instruct와 별도 계보다.

### 2.3 Frontend

[확정] Frontend는 `/health`, `/ready`, `/api/v1/models`, 일반 Chat과 SSE를 이미 분리해 사용한다. Provider 선택 기능은
없고 active Provider 상태만 표시한다. Chat request, SSE `start/delta/done/error`, 취소·재시도 로직은 Adapter에서도
그대로 재사용할 수 있다. 현재 UI에는 Adapter version, active Adapter, Base revision과 compatibility 원인 표시는 없다.

## 3. Runtime 구조와 책임

```text
DohaLM Runtime
├── Runtime
├── Adapter Loader
│   └── Adapter Artifact Validator
├── Adapter Manifest
├── Base Validator
├── Chat Template Validator
├── Tokenizer Validator
├── Metadata Loader
└── Generation Config Loader
```

| Component | 책임 | 금지·실패 경계 |
|---|---|---|
| Runtime | Provider 상태 전이, 단일 lazy-load task, generation semaphore, chat/stream/cancel/shutdown 조정 | 부분 load 객체 공개, Base 자동 fallback, 요청별 Adapter 교체 금지 |
| Adapter Loader | 명시된 manifest 한 개를 기준으로 Base load 후 PEFT Adapter를 `is_trainable=false`로 attach하고 완성된 bundle만 publish | directory scan, network, pickle weight, merge, 임의 checkpoint 선택 금지 |
| Adapter Artifact Validator | `adapter_config.json`과 `adapter_model.safetensors` 존재·checksum·형식·LoRA/CAUSAL_LM·inference mode·Base identity 검증 | `.bin`/pickle, full-model weight, trainable Adapter, checksum 없는 파일 거부 |
| Adapter Manifest | Loader가 읽는 단일 source of truth로서 strict schema, exact field set, version, artifact identity와 lineage를 제공 | unknown field, symlink/path traversal, 절대 artifact 경로, YAML implicit type fallback 금지 |
| Base Validator | manifest, runtime config, local snapshot과 Adapter config의 model ID·revision 일치 검증 | 다른 Qwen variant·revision, remote fallback, CPU/disk offload 허용 금지 |
| Chat Template Validator | Tokenizer의 실제 template 문자열 hash, manifest template identity와 고정 role render smoke 검증 | template 누락·drift, 임의 system prompt 삽입, fallback template 금지 |
| Tokenizer Validator | local Tokenizer file inventory hash, model/revision, fast tokenizer, EOS/PAD, padding/truncation side 검증 | 다른 tokenizer, special-token drift, network 보완 금지 |
| Metadata Loader | training run, Adapter fingerprint, environment, evaluation fingerprint와 eligibility를 checksum 관계로 연결 | training 완료만으로 eligibility 승인, 원문·경로·비밀의 API 노출 금지 |
| Generation Config Loader | checksum이 있는 config를 strict allowlist로 읽고 EOS/PAD·범위·request override 정책 검증 | 알 수 없는 key, special-token override, 무제한 값, silent default 금지 |

### 3.1 Runtime bundle

[제안] Loader가 성공했을 때만 다음 immutable bundle을 Provider에 한 번 publish한다.

```text
LoadedAdapterRuntime
├── manifest identity + safe metadata
├── validated tokenizer
├── Base model with active PEFT Adapter
├── validated generation policy
└── torch/runtime handles
```

[확정] validation 또는 load 중간 객체는 `_loaded`에 저장하지 않는다. 실패하면 지역 참조를 해제하고 CUDA cache를
정리한 뒤 `ADAPTER_INCOMPATIBLE`로 전환한다. 같은 process에서 자동 retry하지 않으며 설정 수정 후 process를 다시
시작해야 한다.

## 4. Adapter Manifest 설계

### 4.1 파일과 canonical 규칙

[확정] manifest 기본 파일명은 `adapter-manifest.json`, 지원 schema version은 `1`이다. Loader는 호출자가 명시한
단일 `Path`만 읽으며 JSON은 strict UTF-8, 중복 key 금지, 최상위·중첩 exact field set으로 검증한다. 실제 Adapter
root 밖으로 나가는 절대경로와 `..`는 허용하지 않는다.

[확정] SHA-256과 fingerprint는 prefix 없는 64자리 lowercase hexadecimal만 허용한다. 아래 값은 schema 예시이며
실제 후보 값이 아니다. Task 1 Loader는 구조·자료형·문자열·hash·경로만 검증하며 실제 후보 identity와 eligibility는
Task 2 Adapter Validator가 별도로 검증한다.

```json
{
  "schema_version": 1,
  "adapter_name": "dohalm-general-instruct",
  "adapter_version": "<approved-candidate-version>",
  "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
  "base_revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
  "tokenizer": "Qwen/Qwen2.5-1.5B-Instruct",
  "tokenizer_hash": "<64-lowercase-hex>",
  "chat_template": {
    "source": "tokenizer_config.json#chat_template",
    "sha256": "<64-lowercase-hex>"
  },
  "peft_version": "<exact-training-compatible-version>",
  "transformers_version": "4.57.6",
  "torch_version": "2.7.1+cu118",
  "generation_config": {
    "path": "generation-config.json",
    "sha256": "<64-lowercase-hex>",
    "request_override_policy": "api_bounds_only"
  },
  "evaluation_fingerprint": "<64-lowercase-hex>",
  "training_run": {
    "id": "<immutable-training-run-id>",
    "result_path": "training-result.yaml",
    "result_sha256": "<64-lowercase-hex>"
  },
  "created_at": "<UTC-RFC3339>",
  "adapter_config": {
    "path": "adapter_config.json",
    "sha256": "<64-lowercase-hex>"
  },
  "adapter_weights": {
    "path": "adapter_model.safetensors",
    "sha256": "<64-lowercase-hex>"
  },
  "metadata": {
    "path": "adapter-metadata.json",
    "sha256": "<64-lowercase-hex>"
  }
}
```

### 4.2 필드 계약

| Field | 검증 계약 |
|---|---|
| `adapter_name`, `adapter_version` | 비어 있지 않은 안전한 slug/version, Provider 공개 identity |
| `base_model`, `base_revision` | runtime 승인값, local snapshot과 Adapter config가 모두 exact match |
| `tokenizer`, `tokenizer_hash` | 학습 Tokenizer identity와 local inventory의 canonical hash exact match |
| `chat_template` | source 위치와 실제 template 문자열 SHA-256 exact match |
| dependency versions | 학습·평가와 runtime의 승인 compatibility tuple에 exact match; 허용 범위 정책은 별도 승인 전 사용하지 않음 |
| `generation_config` | root 내부 파일, checksum, strict schema와 API override 정책 연결 |
| `evaluation_fingerprint` | 배포 후보를 판정한 immutable evaluation 결과 identity; 결과 상태도 Metadata Loader가 검증 |
| `training_run` | immutable run ID와 training result checksum 연결 |
| `created_at` | timezone이 있는 UTC RFC 3339, 현재 시각 기반의 자동 승인에는 사용하지 않음 |
| `adapter_config`, `adapter_weights`, `metadata` | top-level artifact reference의 root-relative path와 checksum; 파일 검증은 Task 2 범위 |

### 4.3 Task 1·2 구현 상태

```yaml
adapter_manifest: implemented_synthetic_validated
strict_json_loader: implemented_synthetic_validated
static_schema_validation: implemented_synthetic_validated
artifact_existence_validation: implemented_synthetic_validated
artifact_checksum_verification: implemented_synthetic_validated
adapter_artifact_validator: implemented_synthetic_validated
base_snapshot_validator: static_identity_only
peft_adapter_loader: not_started
provider_integration: not_started
runtime_adapter_loading: unavailable
```

[확정] `src/inference/adapter_manifest.py`는 frozen dataclass, duplicate-key 차단, 1 MiB manifest 상한,
strict UTC `created_at`, exact schema, safe relative path containment와 구조화된 내부 오류를 제공한다. 테스트 fixture는
`synthetic-not-for-runtime`으로 표시하며 실제 artifact 파일을 포함하지 않는다.

[확정] `src/inference/adapter_validation.py`는 실제 모델을 load하지 않고 다음 정적 계약을 fail closed로 검증한다.

- config·metadata·generation config는 각각 1 MiB, training result는 4 MiB, safetensors는 8 GiB 이하
- regular file·non-symlink·root containment·streaming SHA-256과 검증 전/열린 handle/검증 후 파일 identity 일치
- Adapter config의 `LORA`, `CAUSAL_LM`, Base identity, rank·alpha·dropout·target·bias·inference mode 핵심 필드;
  PEFT 추가 필드는 허용
- safetensors의 16 MiB 이하 JSON header, tensor metadata와 data offset 범위·중복·겹침; tensor payload는 load하지 않음
- metadata schema v1의 Adapter·Base·Tokenizer·Template·training/evaluation lineage와 artifact checksum 참조;
  versioned 핵심 필드 외 확장 필드는 허용
- generation config exact allowlist와 현재 Chat API 범위, manifest의 `api_bounds_only` request override 경계
- 절대경로와 검증 시각을 제외한 canonical JSON 기반 `sha256:<64 lowercase hex>` validation fingerprint

[확정] 이 결과는 **manifest와 artifact 사이의 정적 일관성**만 증명한다. 실제 local Base snapshot, Tokenizer 파일,
Chat Template 문자열, dependency version과 PEFT attach는 검증하지 않으므로 Runtime Adapter Loading은 계속 `unavailable`이다.

## 5. Validator와 Fail Closed 규칙

### 5.1 검증 순서

1. `adapter_root`가 명시됐는지 확인한다.
2. `adapter-manifest.json`을 size 제한 안에서 strict parse한다.
3. 모든 상대경로를 resolve하고 root containment, regular file, symlink 금지와 checksum을 확인한다.
4. Metadata와 evaluation eligibility를 확인한다.
5. Base model ID·revision·snapshot inventory를 확인한다.
6. Tokenizer inventory·identity·special token을 확인한다.
7. Chat Template hash와 render smoke를 확인한다.
8. Adapter config·safetensors header·PEFT identity를 확인한다.
9. Generation Config schema와 Tokenizer special token 일치를 확인한다.
10. dependency version tuple을 확인한다.
11. 위 metadata-only preflight가 모두 통과하면 `not_loaded`로 진입한다.
12. 첫 chat/stream에서 Base와 Adapter를 load하고 active Adapter·device·trainable parameter 0·generation smoke를 확인한 뒤 `ready`를 publish한다.

### 5.2 외부 상태와 오류 코드

| 조건 | Provider status | API/SSE error code | 동작 |
|---|---|---|---|
| Adapter root 또는 manifest 미설정·부재 | `not_available` | `ADAPTER_NOT_AVAILABLE` | 요청 거부, Base fallback 없음 |
| manifest parse/schema/checksum 실패 | `incompatible` | `ADAPTER_INCOMPATIBLE` | 안전한 일반 메시지만 반환 |
| Base model·revision 불일치 | `incompatible` | `ADAPTER_INCOMPATIBLE` | weight load 전 차단 |
| Tokenizer·Chat Template 불일치 | `incompatible` | `ADAPTER_INCOMPATIBLE` | prompt 생성 전 차단 |
| Adapter config·weight·metadata 불일치 | `incompatible` | `ADAPTER_INCOMPATIBLE` | PEFT attach 금지 |
| Generation Config 불일치 | `incompatible` | `ADAPTER_INCOMPATIBLE` | request 실행 금지 |
| preflight 통과, 아직 weight 미load | `not_loaded` | 기존 `PROVIDER_NOT_READY` 또는 첫 요청이 load 대기 | lazy-load 가능 |
| load 진행 | `loading` | load 대기 또는 timeout | 단일 load task만 허용 |
| 모든 post-load 검사 통과 | `ready` | 없음 | chat/stream 허용 |
| shutdown 진행 | `unloading` | 기존 `MODEL_UNLOADING` | 신규 요청 거부 |

[확정] 내부 로그에는 안정적인 세부 reason code와 manifest fingerprint만 기록할 수 있으나 절대경로, prompt/response,
token ID, Adapter weight와 원문 metadata는 기록하지 않는다. 외부 응답은 `ADAPTER_NOT_AVAILABLE` 또는
`ADAPTER_INCOMPATIBLE`로 제한해 로컬 파일 구조와 dependency 세부를 노출하지 않는다.

### 5.3 Adapter post-load 검사

- active Adapter 이름과 manifest identity 일치
- `is_trainable=false`, trainable parameter 수 0
- Base parameter가 Adapter load 전후 수정되지 않았음을 sampled/full fingerprint 정책으로 검증 `[검증 필요]`
- parameter device가 CUDA이고 CPU·disk·META offload가 없음
- Tokenizer object가 preflight identity와 동일
- 고정 synthetic message의 template/tokenization이 preflight 결과와 동일
- generation config의 EOS/PAD가 Tokenizer와 동일
- 실패 시 partial model·tokenizer를 해제하고 `ready`를 한 번도 노출하지 않음

## 6. Provider Lifecycle

```text
startup
  ↓
명시적 manifest 확인
  ├─ 없음 ───────────────→ not_available / ADAPTER_NOT_AVAILABLE
  ↓
Base·Tokenizer·Template·Adapter·Metadata·Generation preflight
  ├─ 불일치 ─────────────→ incompatible / ADAPTER_INCOMPATIBLE
  ↓
not_loaded
  ↓ first chat 또는 stream
단일 lazy load task
  ├─ load/post-load 실패 ─→ incompatible / ADAPTER_INCOMPATIBLE
  ↓
ready
  ├─ chat: 기존 generate 경로
  ├─ stream: 기존 SSE·cancel·timeout 경로
  ↓
shutdown
  → 신규 요청 차단
  → 진행 중 generation 종료 대기
  → Adapter/Base/Tokenizer 참조 해제
  → CUDA cache 회수
  → not_loaded
```

[제안] `InferenceProvider`에 `startup()` lifecycle을 추가하거나 Registry가 Adapter provider의 명시적 initializer를
호출한다. 모든 Provider에 no-op 기본 구현을 제공하는 방식과 protocol 변경 방식은 구현 Task 4에서 결정하되,
constructor에서 filesystem I/O를 수행하지 않는다.

[확정] lazy load는 기존 Base Provider와 같은 single-flight lock/task, semaphore와 cooperative cancellation을 사용한다.
첫 요청은 load 완료 후 같은 요청을 계속 처리할 수 있다. `/ready`는 metadata preflight만 통과한 `not_loaded`를 READY로
표시하지 않는다.

## 7. API 영향 분석

### 7.1 유지하는 계약

[확정] 다음 request/정상 response 계약은 변경할 필요가 없다.

- `POST /api/v1/chat`: `ChatRequest`와 `ChatResponse` 유지
- `POST /api/v1/chat/stream`: `start → delta* → done` 또는 `start → error` 유지
- generation option 범위, request ID, timeout, 취소와 안전한 오류 body 유지
- 요청별 Provider·Adapter 선택 필드 추가 없음

Adapter Provider가 active일 때 response의 기존 `model`은 안전한 runtime model ID, `provider`는
`dohalm-adapter`를 사용한다. model ID 형식은 `<adapter_name>@<adapter_version>` 후보이며 구현 전 공개 API 계약 검토가 필요하다.

### 7.2 필요한 additive 변경

- `/ready`: active Adapter가 unavailable/incompatible이면 generic `PROVIDER_NOT_READY` 대신 해당 Adapter error code를
  503 body에 보존한다. 성공 response shape는 유지한다.
- `/api/v1/models`: 기존 필드를 유지하고 Adapter record에 optional `runtime_metadata`를 추가한다.

```json
{
  "adapter_name": "dohalm-general-instruct",
  "adapter_version": "<version>",
  "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
  "base_revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
  "runtime_status": "not_loaded"
}
```

[확정] Adapter root, filename, checksum 전체값, training output 경로와 내부 validation reason은 API에 노출하지 않는다.
[검증 필요] `/ready` 오류 의미와 `/models` schema 확장은 공개 API 변경이므로 구현 전 ADR 또는 동등한 명시적 사용자
승인으로 계약을 확정한다.

## 8. Frontend 영향 분석

[확정] 현재 Chat 화면, message history, generation settings, SSE parser, 취소·재시도는 그대로 유지한다. Provider 선택,
Adapter upload와 filesystem picker는 추가하지 않는다.

추가 대상은 상태 표시 계층으로 제한한다.

| 표시 항목 | Source | UI 동작 |
|---|---|---|
| Adapter Version | `/models.runtime_metadata.adapter_version` | Adapter Provider일 때만 표시 |
| Runtime Status | `/models.status` 또는 metadata | `not_loaded/loading/ready/incompatible/not_available` 문구 표시 |
| Active Adapter | active Provider와 `adapter_name` | header의 기존 Provider 정보 아래 표시 |
| Model Metadata | Base model과 revision의 안전한 축약 | 상세 펼침 영역 후보; 로컬 경로·hash 제외 |

- `ADAPTER_NOT_AVAILABLE`: “사용 가능한 Adapter가 설정되지 않았습니다.”
- `ADAPTER_INCOMPATIBLE`: “설정된 Adapter가 현재 Runtime과 호환되지 않습니다.”
- 알 수 없는 세부 원인을 추측하거나 자동으로 Base Qwen을 선택하지 않는다.
- frontend type은 optional metadata로 추가해 mock/base-qwen response와 하위 호환을 유지한다.

## 9. 구현 Task와 완료 조건

### Task 1 — Adapter Manifest

- 상태: `implemented_synthetic_validated`
- frozen dataclass/schema, strict JSON loader, duplicate-key 차단, path containment와 synthetic fixture 구현
- valid synthetic manifest, malformed/unknown/path traversal과 자료형·hash·시간 오류 단위 테스트 통과
- artifact 존재·checksum 내용·실제 후보 eligibility 검증은 Task 2로 분리

### Task 2 — Adapter Validator

- 상태: `implemented_synthetic_validated`
- config·weight·metadata·generation config·training result의 file type, size, checksum과 strict core schema 검증
- safetensors header만 streaming parse하고 pickle·merged/full-model artifact를 거부
- manifest와 Adapter config·metadata 사이의 Base·Tokenizer·Template·evaluation·training lineage cross-check
- synthetic unit test를 통과했으며 실제 Base snapshot·Tokenizer·PEFT load 검증은 Task 3 이후로 유지

### Task 3 — Adapter Loader

- local-only Base load 재사용, `PeftModel.from_pretrained(..., is_trainable=false)`, single-flight lazy load와 cleanup 구현
- `peft` exact version을 inference dependency에 고정하고 manifest runtime tuple과 검증
- 완료 조건: synthetic CPU double로 partial publish·retry·fallback이 없고 close가 모든 참조를 해제함

### Task 4 — Provider Integration

- `DohaLMAdapterProvider` placeholder를 Loader-backed Provider로 교체
- Registry/settings/lifespan startup preflight, 상태와 error reason 연결
- 기존 BaseQwenProvider generation/stream lifecycle을 공통화할지는 최소 중복 범위에서 결정
- 완료 조건: no manifest는 기존 `ADAPTER_NOT_AVAILABLE`, mismatch는 `ADAPTER_INCOMPATIBLE`, valid preflight는 `not_loaded`

### Task 5 — API Test

- `/ready`, `/models`, `/chat`, `/chat/stream`의 unavailable/incompatible/lazy/ready 회귀
- schema 하위 호환, safe error, path·hash·traceback 비노출, SSE terminal event 1개 검증
- 완료 조건: 기존 mock/base-qwen test와 신규 Adapter CPU integration test 모두 통과

### Task 6 — Frontend

- optional runtime metadata type, Adapter status/version 표시, 두 Adapter error message 추가
- chat hook과 SSE parser는 계약 변경이 없는 한 수정하지 않음
- 완료 조건: 기존 UI test 통과와 not-available/incompatible/ready 상태 component test 추가

### Task 7 — GPU·E2E

- 사용자가 별도로 승인·지정한 단일 Adapter 후보와 immutable manifest로만 실행
- GPU load, active Adapter, non-empty chat, SSE, cancellation, 후속 요청, unload와 VRAM 회수 검증
- Browser E2E에서 Adapter version/status, streaming, stop, retry, reset 확인
- 완료 조건: 모든 artifact identity가 일치하고 회귀가 통과해야 `implemented_verified` 후보가 됨

## 10. 예상 변경 파일

Task 1 파일은 구현됐고, 나머지는 후속 구현 계획이다.

### 새 파일 후보

```text
src/inference/adapter_manifest.py                    implemented
src/inference/adapter_validation.py                  implemented
src/inference/adapter_loader.py
tests/inference/test_adapter_manifest.py             implemented
tests/inference/test_adapter_validation.py           implemented
tests/fixtures/adapter_manifest/synthetic-not-for-runtime/adapter-manifest.json  implemented
tests/test_adapter_loader.py
tests/test_adapter_provider.py
```

### 수정 파일 후보

```text
src/inference/base.py
src/inference/registry.py
src/inference/model_loader.py
src/inference/providers/dohalm_adapter.py
src/inference/providers/__init__.py
server/core/config.py
server/main.py
server/api/v1/health.py
server/api/v1/models.py
server/schemas/health.py
server/schemas/model.py
tests/test_inference_provider.py
tests/test_server_health.py
tests/test_server_models.py
tests/test_server_chat.py
tests/test_server_chat_stream.py
requirements-inference.txt
pyproject.toml
frontend/lib/types.ts
frontend/lib/errors.ts
frontend/hooks/use-model-status.ts
frontend/components/model/model-status.tsx
frontend/tests/api-client.test.ts
frontend/tests/ui.test.tsx
frontend/e2e/base-qwen-chat.spec.ts
```

[검증 필요] 공통 Base/Adapter runtime 추출 파일과 실제 Adapter E2E spec 이름은 Task 3에서 중복 정도를 확인한 뒤
최소 변경으로 확정한다. Base Qwen E2E는 삭제하거나 약화하지 않는다.

## 11. 위험 요소와 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 아직 배포 후보 Adapter가 없음 | valid manifest를 완성할 수 없음 | synthetic fixture로 Loader를 구현하고 실제 GPU/E2E는 후보 승인 뒤 실행 |
| v0.2 evaluation recovery pending | 잘못된 후보 승격 | `deployment_ready=false`와 evaluation fingerprint/eligibility 불일치 시 차단 |
| 학습·runtime dependency drift | load 성공 후 동작 차이 | exact version tuple, safetensors와 synthetic/generation post-load smoke |
| Tokenizer 또는 Template drift | prompt/label 경계 불일치 | file inventory와 template 문자열을 별도 hash로 검증 |
| partial load 후 READY 노출 | 잘못된 요청 처리·VRAM 누수 | 지역 객체 조립 후 atomic publish, 실패 cleanup, 자동 retry 금지 |
| Base Provider로 silent fallback | Adapter 검증 실패 은폐 | active Adapter Provider는 두 Adapter 오류만 반환하고 registry 전환 금지 |
| API metadata 과다 노출 | 로컬 경로·계보 정보 노출 | 공개 allowlist와 safe DTO, path/checksum 원문 제외 |
| Base/Adapter 코드 중복 | lifecycle 회귀 | 검증된 generation·stream helper 재사용, 조기 대규모 refactor 금지 |
| 8GB VRAM 부족 | Adapter load OOM | load 전 floor 검사, concurrency 1, no offload, 명시적 실패와 회수 |

## 12. 구현 시작 권장 순서

1. 공개 API additive schema와 Adapter 후보 eligibility 승인 경계를 먼저 검토한다.
2. Task 1 manifest와 Task 2 static validator의 synthetic 검증 결과를 유지한다.
3. Task 3 Loader를 test double로 검증하고 실제 Base·Tokenizer·Template·dependency 검증, 실패 cleanup·single-flight를 고정한다.
4. Task 4 Provider를 연결해 unavailable/incompatible/not_loaded 상태를 API 밖에서도 먼저 검증한다.
5. Task 5 API 회귀를 통과한 뒤 Task 6의 최소 Frontend 상태 표시를 추가한다.
6. 마지막에만 사용자가 승인한 실제 Adapter로 Task 7 GPU·Browser E2E를 실행한다.

[확정] 다음 구현 작업은 **Task 3 — Adapter Loader**다. Task 1·2의 strict schema와 static validator는 구현됐지만,
실제 Adapter READY와 `implemented_verified` 판정은 immutable 후보·평가 eligibility와
GPU/E2E 근거가 모두 있어야 한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | Task 2 정적 Adapter Artifact Validator, safetensors header parser, lineage·generation 검증과 synthetic 회귀 반영 |
| 2026-08-05 | Task 1 immutable Adapter Manifest·strict JSON loader·정적 schema/path 검증과 42개 synthetic test 반영 |
| 2026-08-04 | 현재 Provider·API·Frontend와 QLoRA artifact 계보를 기준으로 fail-closed Adapter Runtime 설계와 구현 Task 작성 |
