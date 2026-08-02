# DohaLM Frontend

Next.js App Router와 React hooks로 구성한 개발용 채팅 MVP다. 현재 FastAPI의 `MockProvider`만 사용하며 model weight, Adapter 또는 GPU를 로드하지 않는다.

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
