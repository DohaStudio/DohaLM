# Pilot Pretraining 테스트

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [Pilot Pretraining](../training/pilot-pretraining.md), [Pilot Corpus 준비](../data/pilot-corpus-preparation.md), [테스트 전략](./test-strategy.md) |
| 후속 문서 | 실제 Stage B Pilot 검증 기록, Gate 7 검토 |
| 구현 전 필수 여부 | 예 |

## 2. 자동 검증 범위

- [확정] corpus의 UTF-8·빈 입력·NUL·NFC·fingerprint·local-only·field 혼입을 검증한다.
- [확정] SentencePiece 16,000·Unigram·identity·hard limit·special ID·fingerprint 계약과 vocab 자동 축소 금지를 검증한다.
- [확정] SHA-256 split 결정론, duplicate 동일 split, EOS, continuous/record-boundary, drop/pad, `-100` label과 token 범위를 검증한다.
- [확정] 실제 PyTorch 모델·Trainer를 사용하는 CPU 5-step smoke에서 finite loss, checkpoint, gradient·throughput metric을 검증한다.
- [확정] 독립 validation의 no-grad·mode 복원·결정론과 checkpoint resume·dataset lineage 불일치 차단을 검증한다.
- [확정] 실제 SentencePiece smoke tokenizer로 encode → greedy generation → decode와 context 제한을 검증한다.

## 3. 실행 구분

- [확정] Stage A 테스트 fixture와 test output은 합성이며 Git에 실제 corpus·token artifact·모델을 추가하지 않는다.
- [검증 필요] Stage B에서는 실제 DohaLM-Tiny CUDA FP16 5-step smoke, 100-step 이하 Pilot, step 50 resume, 동일 prompt 전후 생성, checkpoint 크기, RTX 3060 Ti 8GB 처리량·peak VRAM을 별도 기록한다.
- [확정] 실제 Pilot이 실행되지 않은 상태를 학습 성공이나 Gate 7 통과로 표현하지 않는다.

## 4. 실패 조건

비유한 loss/gradient, OOM, tokenizer·corpus·split·packing fingerprint 불일치, validation 누수, 원문 artifact 노출, 100-step 초과, 공개 허용 flag, resume 불연속 중 하나라도 발생하면 실행을 중단하고 결과를 실패로 보존한다.
