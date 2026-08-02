# DohaLM Base Qwen 로컬 추론 Provider

- 문서 상태: `review`
- 마지막 검토일: 2026-08-03
- 대상 모델: `Qwen/Qwen2.5-1.5B-Instruct`
- 고정 revision: `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`
- 선행 문서: [FastAPI 백엔드 MVP](./dohalm-backend-mvp.md), [Frontend MVP](./dohalm-frontend-mvp.md)

## 범위와 안전 경계

`BaseQwenProvider`는 FastAPI의 기존 Chat·SSE schema를 유지하며 고정된 로컬 snapshot만 읽는다. `local_files_only=true`,
`trust_remote_code=false`를 강제하고 model ID와 revision이 승인값과 다르면 시작 전에 차단한다. Snapshot 절대경로,
prompt·response 원문과 token ID는 API·로그에 기록하지 않는다.

DohaLM Adapter, Dataset, Tokenization, QLoRA 학습, checkpoint와 model merge는 이 구현의 범위 밖이다. Base Qwen은
DohaLM 학습 결과가 아니라 서비스 경로 검증용 upstream Instruct 모델이다.

## 지원 환경과 선택 결과

| 항목 | 검증 결과 |
|---|---|
| OS | Windows 11 + WSL2 local cache |
| Python | 3.12 |
| PyTorch | 2.7.1+cu118 |
| Transformers | 4.57.6 |
| Accelerate | 1.12.0 |
| BitsAndBytes | 0.48.2 |
| SentencePiece | 0.2.2 |
| GPU | NVIDIA GeForce RTX 3060 Ti 8GB |
| 선택 runtime | 명시적 `bf16` |
| 기본 config | `nf4`; 자동 fallback 없음 |

사전 가용 VRAM 6,445MiB에서 BF16 allocation을 제한적으로 검증했다. Model 상주 allocated VRAM은
3,087,429,120 bytes, 실제 streaming peak는 3,103,098,880 bytes였고 parameter device는 전부 CUDA였다.
CPU·disk·META offload와 OOM은 없었다. Provider 종료 후 cuBLAS workspace와 CUDA cache까지 정리되어 allocated와
reserved memory가 모두 64MiB 미만으로 회수됐다. NF4는 설정과 loader를 지원하지만 이번 통합 smoke의 선택값이 아니며
자동 fallback으로 사용하지 않는다.

고정 snapshot의 `model.safetensors` SHA-256은
`dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee`로 원본과 로컬 실행 사본이 일치했다.
실행 사본은 Git 외부에만 두며 경로는 `.env`에서만 지정한다.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DOHALM_BASE_MODEL_ID` | `Qwen/Qwen2.5-1.5B-Instruct` | 승인된 model ID |
| `DOHALM_BASE_MODEL_REVISION` | 고정 revision | 승인된 commit revision |
| `DOHALM_BASE_MODEL_SNAPSHOT` | 없음 | 완전한 로컬 snapshot; `.env` 전용 |
| `DOHALM_BASE_MODEL_QUANTIZATION` | `nf4` | `nf4` 또는 `bf16`; 자동 변경 없음 |
| `DOHALM_BASE_MODEL_DEVICE` | `cuda:0` | 승인된 단일 GPU |
| `DOHALM_MAX_CONCURRENT_GENERATIONS` | `1` | generation semaphore 크기 |
| `DOHALM_MODEL_LOAD_TIMEOUT_SECONDS` | `300` | lazy load 대기 상한 |
| `DOHALM_GENERATION_TIMEOUT_SECONDS` | `120` | 생성과 semaphore 대기 상한 |
| `DOHALM_MODEL_UNLOAD_ON_SHUTDOWN` | `true` | shutdown model·tokenizer 해제 |
| `DOHALM_MINIMUM_FREE_VRAM_MIB` | `5500` | load 직전 fail-closed 기준 |

실행 시 `DOHALM_INFERENCE_PROVIDER=base-qwen`을 함께 지정한다. 실제 경로는 `.env.example`에 넣지 않는다.

## Lifecycle과 상태

Load policy는 `lazy`다. Startup은 weight를 읽지 않으며 첫 generate 또는 stream 요청 하나만 load task를 만든다.
상태 lock은 `not_loaded → loading → ready`, `loading → error`, `ready → unloading → not_loaded`를 보호한다.
Lazy load 전 `/ready`는 503이고 `/api/v1/models`는 `not_loaded`, load 후에는 각각 200과 `ready`를 반환한다.

동시 generation 기본값은 1이다. 두 번째 요청은 semaphore에서 대기하며 API timeout을 넘으면 504 또는 SSE error로
종료한다. 요청마다 model을 unload하지 않는다. Shutdown은 active generation 종료를 기다린 뒤 model·tokenizer 참조,
Python garbage와 CUDA cache를 회수한다.

## Prompt와 생성

입력은 role과 앞뒤 공백만 정규화한 뒤 tokenizer의 공식 `apply_chat_template(..., tokenize=false,
add_generation_prompt=true)`로 구성한다. 임의 system prompt는 추가하지 않는다. EOS는 151645, pad는 151643이며
`use_cache=true`와 `torch.inference_mode()`를 사용한다.

- `temperature == 0`: `do_sample=false`, request의 temperature·top_p를 generation kwargs에서 제외한다.
- `temperature > 0`: `do_sample=true`와 request temperature·top_p를 전달한다.
- Prompt token을 output에서 제거하고 실제 prompt·completion token 수만 usage로 반환한다.
- EOS면 `stop`, token 상한이면 `length`, client abort면 `cancelled`로 판정한다.
- Decode 결과가 빈 문자열이어도 실제 token usage와 finish reason을 가진 정상 empty result로 유지한다.

## Streaming·취소·Timeout

Streaming은 `TextIteratorStreamer`, 단일 non-daemon worker thread와 cancellation `threading.Event`를 사용한다.
Client abort 또는 timeout은 stopping criteria를 켜고 worker join을 끝낸 뒤 semaphore를 반환한다. Worker 예외는 async
계층으로 전달되며 API는 기존 `start → delta+ → done` 또는 `start → error` 계약을 유지한다. 완료 전에 worker를 join해
finish reason race와 orphan thread를 차단한다.

## 실행

```powershell
python -m pip install -r requirements-inference.txt
Copy-Item .env.example .env
# .env에 DOHALM_INFERENCE_PROVIDER, DOHALM_BASE_MODEL_SNAPSHOT과 명시적 quantization을 설정
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Frontend는 [Frontend MVP](./dohalm-frontend-mvp.md)의 개발 명령을 사용한다. API schema와 frontend client 계약은
MockProvider와 동일하다.

## 검증 결과

- CPU synthetic: lazy load, 단일 load, failure sanitization, greedy/sampling mapping, official template, timeout,
  cancellation join, semaphore 반환, streaming과 unload 통과
- GPU marker: BF16 load, Korean non-empty generate, usage, CUDA-only device, streaming, abort, 후속 요청, unload 통과
- FastAPI: lazy 전후 readiness와 models, 일반 chat 200, 실제 usage, SSE start/delta/done, 경로 비노출 통과
- Chrome E2E: page, Base Qwen 상태, 실제 streaming, 중단, 후속 retry, 새 대화, 오류·재시도, 390px viewport 통과
- 로그: request/provider/model ID와 수치 metadata만 기록하고 prompt·response·snapshot 경로는 기록하지 않음

## 현재 상태

```yaml
base_qwen_provider:
  implemented: true
  local_only: true
  load_policy: lazy
  selected_runtime: bf16
  api_smoke: passed
  browser_smoke: passed
dohalm_adapter_loaded: false
tokenization_started: false
training_started: false
deployment: not_started
```
