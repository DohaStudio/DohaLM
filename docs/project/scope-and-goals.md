# DohaLM 범위와 목표

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- [확정] 이 문서는 프로젝트 범위와 목표를 정의하며 구현 완료를 의미하지 않습니다.

## 1. 전체 목표

DohaLM의 목표는 직접 구현 Foundation 연구와 별도 reusable model 계보를 검증하고, 외부 프로젝트가 안정적으로 사용할 수 있는
모델·Runtime·API·SDK·manifest·통합 문서를 제공하는 것입니다. 기준 하드웨어는 단일 `RTX 3060 Ti 8GB`입니다.

## 2. 포함 범위

### Phase 1 — Foundation Model Development

- 라이선스·계보가 기록된 Dataset과 Tokenizer
- PyTorch Decoder-only Transformer 직접 구현
- DohaLM-Tiny Base pretraining, Candidate A/B/C, EOS 진단
- Base evaluation, candidate selection과 Foundation Base
- 별도 parent 결정에 따른 Foundation Instruct 연구 계보

승인 Tiny 사양은 [모델 아키텍처](../architecture/model-architecture.md)와
[ADR-002](../decisions/ADR-002-tiny-model-architecture.md)를 따릅니다. Candidate B가 current baseline이며 Candidate C는
contract design만 완료된 experimental successor입니다.

### Phase 2 — Reusable Model and Runtime

- Qwen Base 또는 Instruct 기반 Korean·General SFT
- QLoRA Adapter 또는 merged model과 평가
- versioned DohaLM Model artifact, manifest, validator와 loader
- inference runtime과 provider lifecycle

이 Phase는 Phase 1 Candidate의 자동 파생물이 아닙니다. 상세 계약은
[Reusable Model Strategy](./reusable-model-strategy.md)를 따릅니다.

### Phase 3 — Distribution and Integration

- runtime server와 REST·Streaming API
- Python SDK
- Integration Guide와 local versioned release
- 모델·Runtime 호환성과 release identity

상세 범위는 [Distribution and Integration](./distribution-and-integration.md)을 따릅니다.

## 3. 성공 기준

- Foundation Candidate의 Dataset·Tokenizer·config·checkpoint·evaluation lineage가 재현 가능합니다.
- 승인된 reusable model artifact가 manifest와 checksum으로 식별되고 fail-closed Runtime에서 로드됩니다.
- REST·Streaming과 Python SDK가 동일한 versioned model contract를 소비합니다.
- 별도 저장소의 Reference Application이 Integration Guide에 따라 DohaLM을 호출할 수 있습니다.
- 구현되지 않았거나 승인되지 않은 항목을 완료로 표시하지 않습니다.

정량 합격선은 기존 승인 평가 문서와 코드만 재사용하며 임의로 만들지 않습니다.

## 4. 제외 범위

- ChatGPT 대체 또는 상용 수준 성능·가용성·SLA 보장
- A100·H100, 멀티 GPU와 7B 이상 from-scratch pretraining
- Docker, Kubernetes, Cloud와 운영 배포
- DohaMusic을 포함한 소비자 UI·도메인 비즈니스 로직
- 오디오·보컬·MIDI 생성
- 승인되지 않은 publication

## 5. 현재 미결정 사항

- Candidate C 단일 EOS 가설과 single-use 실행 승인
- Foundation Instruct parent에 관한 ADR-010 후속 결정
- eligible General Instruct Adapter candidate
- Python SDK 공개 표면과 versioned release 승인
- DohaLM-Small 상세 구조

현재 사실 상태는 [Current Project Status](./current-project-status.md)를 따릅니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | reusable LLM model provider 목표와 세 Phase의 포함·제외·성공 기준으로 재구성 |
| 2026-08-04 | 당시 구현 상태와 배포 제외 범위 반영 |
