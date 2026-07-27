# DohaLM 평가 계획

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `plan`, `reproducibility`
- 관련 결정: [ADR-005](../decisions/ADR-005-evaluation-and-experiment-policy.md)

## 목적과 범위

동일한 internal evaluation identity로 initial, Pilot, Candidate A mid/final을 재현 가능하게 비교한다. Gate 7은 memorization-only 그룹으로 분리한다. 현재 작업은 Candidate A Final Quick evaluation까지이며 Candidate B/C, 추가 학습, Resume, SFT와 공개를 포함하지 않는다.

## 실행 프로필

- `inspect`: 기본값. registry와 논리 경로, checksum/fingerprint/승인 상태만 확인한다.
- `quick`: 고정 seed로 128 sequence, synthetic generation과 16/32/64/128 continuation probe를 실행한다. 최대 600초다.
- `full`: 14,329 packed sequence 전체를 평가한다. 최대 900초다.
- `compare`, `report`: 완료된 외부 manifest를 읽는 interface이며 학습을 시작하지 않는다.

Quick/Full은 `--execute`와 새 evaluation ID가 없으면 실행하지 않는다. 기존 output은 덮어쓰지 않는다.

## 성공 기준

Artifact/dataset/tokenizer/config identity 검증, token-weighted perplexity, Top-k, position-aware, generation, continuation, stability, fingerprint와 atomic checksum output을 구현한다. Candidate A Final Quick가 10분 안에 완료되고 checkpoint/model fingerprint가 전후 동일해야 framework 구현 완료로 판단한다. 성능 수치의 높고 낮음은 framework 성공과 별개다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | 구현 프로필, 실행 경계와 성공 기준 반영 |
