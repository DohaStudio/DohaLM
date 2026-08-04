# DohaLM Instruct 문서 안내

- 문서 상태: `review`
- 마지막 검토일: 2026-08-04
- 기준 문서: [README](../../README.md)
- 전략: [Instruct Strategy](./instruct-strategy.md)

## 1. 범위

이 디렉터리는 서로 다른 두 계보의 기록을 보존합니다.

- **Foundation Instruct**: ADR-010에 따른 Candidate B 기반 `DohaLM Instruct Tiny v1` 설계. 학습과 artifact는 미생성입니다.
- **Runtime General Instruct Adapter**: Qwen Base 기반 QLoRA 데이터·학습·평가 이력. 코드와 외부 실행 기록은 있지만 현재 Runtime에는 연결되지 않았습니다.

두 계보의 parent, 이름, 완료 상태와 실행 권한을 합치지 않습니다.

## 2. 현재 요약

| 영역 | 상태 | 현재 의미 |
|---|---|---|
| Foundation Instruct 설계 | `design_complete` | schema·prompt·evaluation·safety·readiness 설계 |
| Foundation Instruct 실행 | `not_approved` | Candidate B 파생 model artifact 없음 |
| AIHUB-71748 SFT Processing | `completed_run_0015` | 조건부 선정 목적의 처리 이력; 재처리 포괄 승인 아님 |
| Runtime v0.1 | `implemented_not_integrated` | Qwen tokenization, QLoRA Adapter와 독립 평가 이력 |
| Runtime v0.2 | `implemented_not_integrated` | weighted 2-epoch 학습 완료 기록; 평가 recovery·배포 판정 분리 |
| Runtime v0.3 | `blocked` | Dataset full 생성 전, Tokenization publish 실패 보존; 재시도 미승인 |
| Adapter Loader | `planned` | 서비스 Provider는 fail-closed placeholder |
| Tool Calling | `planned` | 전략 문서만 있고 실행 Runtime 없음 |

## 3. 권장 읽기 순서

### Foundation Instruct 설계

1. [Instruct Strategy](./instruct-strategy.md)
2. [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)
3. [Instruction Dataset Strategy](./instruction-dataset-strategy.md)
4. [Instruction Schema](./instruction-schema.md)
5. [Prompt Template](./instruction-prompt-template.md)
6. [Instruction Evaluation](./instruction-evaluation.md)
7. [Instruction Safety](./instruction-safety.md)
8. [Instruction Readiness](./instruction-readiness.md)

### Dataset Processing 계보

AIHUB-71748의 상세 Terms·Schema·PII·Duplicate·Leakage·Approval·Run 이력은
[전체 문서 인덱스](../index.md)의 `instruct/` 항목을 따릅니다. 현재 기준 결과는 Run 0015 처리 완료이며,
Run 0001~0014는 현재 계획이 아닌 감사·실패 계보입니다.

핵심 진입점:

- [Dataset Selection Decision](./aihub-71748-selection-decision.md)
- [Dataset Readiness](./aihub-71748-readiness.md)
- [Processing Backend](./processing-backend.md)
- [Processing Manifest](./aihub-71748-processing-manifest.md)

### Runtime General Instruct Adapter

1. [v0.1 Tokenization Readiness](./dohalm-v0.1-tokenization-readiness.md)
2. [v0.1 QLoRA Training](./dohalm-v0.1-qlora-training.md)
3. [v0.1 Stall Diagnostic](./dohalm-v0.1-qlora-stall-diagnostic.md)
4. [v0.1 Independent Evaluation](../evaluation/dohalm-v0.1-qlora-evaluation.md)
5. [v0.1 Decoding Evaluation](../evaluation/dohalm-v0.1-decoding-evaluation.md)
6. [v0.2 Weighted Tokenization](./dohalm-v0.2-weighted-tokenization-readiness.md)
7. [v0.2 QLoRA Training](./dohalm-v0.2-qlora-training.md)
8. [v0.2 Evaluation Recovery](./dohalm-v0.2-evaluation-recovery.md)
9. [v0.3 Tokenization Readiness](./dohalm-v0.3-tokenization-readiness.md)
10. [v0.3 Publish Failure](./dohalm-v0.3-tokenization-publish-failure.md)

## 4. 실행 경계

- 처리·학습·평가 이력은 다음 실행의 자동 승인으로 재사용하지 않습니다.
- 외부 Dataset·checkpoint·Adapter는 Git에 추가하거나 자동 탐색하지 않습니다.
- Adapter 선정, deployment eligibility와 Runtime Loader 연결은 각각 별도 완료 조건입니다.
- QLoRA Adapter를 Foundation Candidate B 계보로 재명명하거나 Base weight에 merge하지 않습니다.
- Memory, RAG, Tool Calling과 Agent는 2차 목표입니다.
- Docker, Kubernetes, Cloud와 운영 배포는 현재 범위 밖입니다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-04 | Foundation Instruct와 Qwen Runtime Adapter 계보 분리, 상세 Run 중복을 인덱스 링크로 축약 |
| 2026-07-30 | AIHUB-71748 Processing 및 QLoRA 문서 진입점 확장 |
