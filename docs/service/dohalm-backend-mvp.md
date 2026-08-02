# DohaLM FastAPI 백엔드 MVP

- 문서 상태: `review`
- 최종 검토일: 2026-08-03
- 서비스 버전: `0.1.0`
- 활성 기본 Provider: `mock`

## 범위와 구조

이 MVP는 Frontend가 사용할 HTTP·SSE 계약과 Provider 교체 경계를 검증한다. 실제 model weight,
Adapter, GPU 추론, Dataset, 학습·평가 파이프라인은 사용하지 않는다.

```text
FastAPI application
├── API routers
├── inference service
└── provider registry
    ├── MockProvider             ready
    ├── BaseQwenProvider         local-only lazy load
    └── DohaLMAdapterProvider    not_available placeholder
```

Provider는 application lifespan에서 한 번 생성되고 shutdown 때 `close()`된다. 알 수 없는 Provider는
startup에서 `UNKNOWN_INFERENCE_PROVIDER`로 fail closed된다.

## 설치와 실행

```powershell
python -m pip install -r requirements-api.txt
python -m pip install -e . --no-deps
uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

OpenAPI UI는 `http://127.0.0.1:8000/docs`, schema는 `/openapi.json`에서 확인한다. 이 MVP는
개발용 비인증 API이며 외부 네트워크나 운영 환경에 그대로 공개하지 않는다.

## 환경변수

| 변수 | 기본값 |
|---|---|
| `DOHALM_ENV` | `development` |
| `DOHALM_API_HOST` | `127.0.0.1` |
| `DOHALM_API_PORT` | `8000` |
| `DOHALM_API_PREFIX` | `/api/v1` |
| `DOHALM_CORS_ORIGINS` | `["http://localhost:3000"]` |
| `DOHALM_INFERENCE_PROVIDER` | `mock` |
| `DOHALM_REQUEST_TIMEOUT_SECONDS` | `60` |
| `DOHALM_STREAM_CHUNK_DELAY_MS` | `20` |
| `DOHALM_LOG_LEVEL` | `INFO` |
| `DOHALM_MODEL_CACHE_ROOT` | 설정 없음 |
| `DOHALM_ADAPTER_ROOT` | 설정 없음 |

로컬 경로는 `.env`에서만 지정하며 API 응답이나 로그에 노출하지 않는다.

## Endpoint

| Method | Path | 역할 |
|---|---|---|
| `GET` | `/health` | process liveness |
| `GET` | `/ready` | active Provider readiness |
| `GET` | `/api/v1/models` | 공개 가능한 Provider metadata |
| `POST` | `/api/v1/chat` | 일반 채팅 |
| `POST` | `/api/v1/chat/stream` | SSE 채팅 |

모든 응답은 `X-Request-ID`를 포함한다. 요청 ID는 안전한 `req_` 형식만 재사용하고 그 외에는 서버가
새로 발급한다.

## 일반 Chat 예제

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"DohaLM 테스트"}]}'
```

MockProvider는 같은 입력에 같은 한국어 응답을 반환하며 token usage는 `null`이다.

## SSE 예제

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"스트리밍 테스트"}]}'
```

정상 스트림은 `start`, 하나 이상의 `delta`, 정확히 하나의 `done` 순서다. 실패 시 `done` 대신
정확히 하나의 `error`가 발생한다. timeout과 client cancellation은 Provider task에 전파된다.

## Provider 교체

`DOHALM_INFERENCE_PROVIDER`는 `mock`, `base-qwen`, `dohalm-adapter`만 허용한다.
`base-qwen`은 고정 local snapshot을 첫 요청에서 한 번만 lazy load한다. Load 전 readiness는 503이며 load 후 일반 Chat과
SSE를 제공한다. 설정·실측·취소·메모리 정책은 [Base Qwen 로컬 Provider](./dohalm-base-qwen-provider.md)를 따른다.
`dohalm-adapter`는 배포 승인 Adapter를 자동 탐색하지 않고 `ADAPTER_NOT_AVAILABLE`을 반환한다.

## 보안 제한

- 요청당 message 50개, message당 8,000자, 전체 32,000자 제한
- generation 범위 검증과 1 MiB 기본 body 제한
- 명시적 CORS origin만 허용하고 credentials는 비활성
- prompt·전체 응답·환경변수·로컬 경로·traceback 비기록·비노출
- unsafe dynamic import, shell 실행, 자동 model/adapter 탐색 없음
- DB, 인증, 영구 대화 저장, Redis, Docker와 운영 배포는 범위 밖

## 현재 상태

```yaml
backend_mvp: implemented
mock_provider: ready
base_qwen_provider: implemented_local_only_lazy
dohalm_adapter_provider: placeholder_not_available
model_weight_loaded: true_in_explicit_smoke_only
gpu_inference_started: true_in_explicit_smoke_only
training_started: false
dataset_modified: false
```
