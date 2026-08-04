# DohaLM Instruct Strategy

- 문서 상태: `review`
- 마지막 검토일: 2026-08-04
- 기준 문서: [README](../../README.md)
- 관련 결정: [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. 두 Instruct 계보

DohaLM에는 목적과 parent가 다른 두 Instruct 계보가 있습니다.

| 구분 | Foundation Instruct | Runtime General Instruct Adapter |
|---|---|---|
| 트랙 | Foundation Model 연구 | Runtime/Application |
| Parent | Candidate B Final | 고정 `Qwen/Qwen2.5-1.5B-Instruct` revision |
| 형태 | 별도 DohaLM derivative 후보 | QLoRA PEFT Adapter |
| 결정 근거 | ADR-010 | v0.1~v0.3 QLoRA·평가 실행 문서 |
| 현재 상태 | `design_complete`, artifact 없음 | backend·실행 이력 존재, Runtime 미연결 |
| Runtime 사용 | 없음 | Adapter Loader 구현·선정 전까지 없음 |

Qwen Adapter를 `DohaLM Instruct Tiny v1`로 부르지 않고, Candidate B 기반 설계가 있다는 이유로 Qwen Runtime Adapter가
완료됐다고 보지 않습니다.

## 2. Foundation Instruct

ADR-010의 범위는 Candidate B를 immutable parent로 하는 instruction-following derivative 설계입니다.

- Parent mutation과 Base 재명명 금지
- Dataset, prompt serialization, assistant-only mask, EOS, SFT와 evaluation을 별도 승인
- Chat은 승인된 Foundation Instruct를 parent로 하는 후속 연구
- 학습, model artifact, Runtime 연결과 publication은 미완료·미승인

이 설계의 상세 schema·safety·readiness는 [Instruct 문서 안내](./README.md)에 보존합니다.

## 3. Runtime General Instruct Adapter

1차 Runtime 목표는 Qwen Base 위의 General Instruct Adapter를 선택하고 실제 Loader로 연결하는 것입니다.

```text
Qwen Base revision
  → approved SFT dataset/tokenization
  → QLoRA training
  → evaluation and candidate selection
  → deployment eligibility
  → fail-closed Adapter Loader
  → Chat API / Streaming
```

현재 학습·평가 backend와 v0.1/v0.2 실행 이력은 있지만, 저장소 Runtime에는 배포 승인 Adapter가 없습니다.
[Adapter Runtime 설계](../service/dohalm-adapter-runtime.md)는 완료됐지만
`src/inference/providers/dohalm_adapter.py`는 아직 placeholder이며 generate/stream 요청을 `ADAPTER_NOT_AVAILABLE`로 차단합니다.

### 완료 조건

General Instruct Adapter를 Runtime 완료로 표시하려면 다음이 모두 필요합니다.

1. 단일 후보 Adapter와 Base revision·dataset·config·evaluation fingerprint 고정
2. 명시적 deployment eligibility 판정
3. 경로 자동 탐색 없이 설정된 artifact의 checksum·Base compatibility 검증
4. load/generate/stream/cancel/unload와 VRAM 회수 검증
5. Base Qwen 대비 회귀·safety 결과와 한계 기록

QLoRA 학습 완료만으로 위 조건을 충족하지 않습니다.

## 4. Prompt와 후속 기능 경계

- 현재 Base Qwen 경로는 tokenizer의 공식 chat template를 사용합니다.
- 독립 Prompt Engine의 template version, system policy, token budget와 Adapter별 template 매핑은 아직 설계·구현 대상입니다.
- Tool Calling 문서는 전략 초안이며 실제 tool schema 실행이나 권한 Runtime은 없습니다.
- Memory, RAG, Tool Calling, Agent는 2차 목표이고 General Instruct Runtime 완료 뒤 진행합니다.

## 5. 제외 범위

- Base 또는 Adapter merge와 같은 이름으로 artifact 교체
- 자동 checkpoint/Adapter 탐색과 무근거 fallback
- RLHF·DPO·PPO와 숨은 chain-of-thought 수집
- 실제 tool 자동 실행
- Docker, Kubernetes, Cloud와 운영 배포

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-04 | fail-closed Adapter Runtime 설계 문서와 구현 미착수 상태 연결 |
| 2026-08-04 | Candidate B 기반 Foundation Instruct와 Qwen 기반 Runtime General Instruct Adapter를 분리 |
| 2026-07-28 | Candidate B immutable parent 기반 Instruct 설계 작성 |
