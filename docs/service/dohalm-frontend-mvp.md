# DohaLM Next.js Frontend MVP

- 문서 상태: `review`
- 최종 검토일: 2026-08-03
- Frontend 버전: `0.1.0`
- Backend 계약: [FastAPI 백엔드 MVP](./dohalm-backend-mvp.md)

## 범위와 구조

[확정] 이 MVP는 FastAPI의 MockProvider 또는 승인된 local-only Base Qwen Provider와 실제 HTTP·SSE로 통신하는 메모리 기반 단일 페이지 채팅 UI다. DohaLM Adapter, Dataset, Tokenization, Training, 인증, DB와 배포는 범위 밖이다.

```text
app/                 App Router page, layout, global error boundary
components/chat/     header, message list, composer, generation settings
components/model/    API와 active Provider 상태
components/ui/       최소 공용 UI primitive
hooks/               chat과 model status 상태
lib/                 API client, SSE parser, types, errors, constants
tests/               API, SSE, hook, UI 단위·통합 테스트
```

상태는 React hooks에만 보관하며 새로고침하면 초기화된다. LocalStorage, 전역 상태 라이브러리, WebSocket, Markdown/HTML renderer는 사용하지 않는다.

## 설치와 실행

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Backend는 저장소 루트에서 별도로 실행한다.

```powershell
python -m pip install -r requirements-api.txt
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:3000`을 연다. Backend CORS 설정에는 실제 Frontend origin이 명시적으로 포함되어야 한다.

## 환경변수

| 변수 | 기본값 | 목적 |
|---|---|---|
| `NEXT_PUBLIC_DOHALM_API_BASE_URL` | `http://127.0.0.1:8000` | FastAPI base URL |
| `NEXT_PUBLIC_DOHALM_STREAMING_ENABLED` | `true` | SSE 사용 여부 |
| `NEXT_PUBLIC_DOHALM_DEFAULT_MAX_NEW_TOKENS` | `256` | 생성 토큰 기본값 |

개인 경로와 비밀정보는 `.env.local`에서만 관리한다. 컴포넌트는 URL을 직접 조합하지 않고 `lib/api-client.ts`만 사용한다.

## Backend 연동

| API | UI 사용 |
|---|---|
| `GET /health` | API online/offline |
| `GET /ready` | active Provider readiness |
| `GET /api/v1/models` | Provider·model 상태 표시 |
| `POST /api/v1/chat` | streaming 비활성 일반 Chat |
| `POST /api/v1/chat/stream` | 기본 SSE Chat |

`/health` 성공과 `/ready` 503을 구분한다. 모델 목록은 정보 표시 전용이며 요청별 Provider 전환 기능은 제공하지 않는다.

## Chat과 Streaming

- user와 완료된 assistant message만 다음 요청 이력에 포함한다.
- error, cancelled, 빈 streaming placeholder는 이력에서 제외한다.
- SSE parser는 UTF-8 경계, chunk 경계, 여러 `data` line, unknown event를 처리한다.
- `start`, 여러 `delta`, 정확히 하나의 `done` 또는 `error`를 허용한다.
- 종료 이벤트 이후 event는 상태에 다시 반영하지 않는다.
- 중단과 component unmount는 같은 `AbortController`를 취소한다.
- 자동 재시도는 없으며 명시적 재시도만 같은 payload와 설정을 다시 사용한다.

## UI와 접근성

- dark 기본의 중앙 채팅 레이아웃과 mobile/tablet 반응형 배치
- API·Provider 상태, empty state, message status, Request ID 표시
- Enter 전송, Shift+Enter 줄바꿈, IME 조합 중 Enter 방지
- aria label, aria-live, focus-visible, disabled 상태와 색 이외의 상태 문구
- 답변은 `white-space: pre-wrap` plain text로만 표시하며 HTML을 삽입하지 않는다.

## 검증

```powershell
npm run lint
npm run typecheck
npm run test
npm run build
npm audit --audit-level=high
```

통합 smoke에서는 Frontend와 Backend를 동시에 실행하고 page 200, CORS, health, readiness, models, 일반 Chat과 SSE
`start/delta/done`을 확인한다. Base Qwen Chrome E2E는 실제 streaming, 중단, 후속 retry, 새 대화, 오류·재시도와
390px viewport를 검증한다. 모델 응답 문구는 고정하지 않고 non-empty와 상태 전이만 검사한다.

## 현재 제한

```yaml
frontend_mvp: implemented
active_provider: mock_default_base_qwen_explicitly_verified
conversation_storage: memory_only
authentication: absent
actual_model_provider: base_qwen_local_only_verified
model_weight_loaded: true_in_explicit_smoke_only
gpu_inference_started: true_in_explicit_smoke_only
training_started: false
deployment: not_started
```

후속 작업은 별도 승인된 Base Qwen Provider 또는 DohaLM Adapter 연결과 실제 브라우저 상호작용 검증이다.
