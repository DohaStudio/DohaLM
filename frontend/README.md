# DohaLM Frontend

Next.js App Router와 React hooks로 구성한 개발용 채팅 MVP다. FastAPI의 `mock` 또는 승인된 로컬 `base-qwen` Provider와 동일한 HTTP·SSE 계약으로 통신한다.

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

기본 Backend 주소는 `http://127.0.0.1:8000`이다. 상세 계약과 검증 절차는 [Frontend MVP 문서](../docs/service/dohalm-frontend-mvp.md)를 따른다.

```powershell
npm run lint
npm run typecheck
npm run test
npm run build
```
