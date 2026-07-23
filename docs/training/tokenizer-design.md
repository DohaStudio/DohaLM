# DohaLM 토크나이저 설계

- 문서 상태: `review`
- 마지막 검토일: 2026-07-23

## 1. 목적과 범위

- [확정] 한국어 사전학습 및 SFT에 사용할 SentencePiece 토크나이저를 직접 학습한다.
- [확정] vocabulary size는 special token을 포함해 16,000이다.
- [확정] 외부 완성 모델의 토크나이저를 핵심 토크나이저로 사용하지 않는다.
- [확정] 현재 토크나이저 모델과 학습 데이터는 존재하지 않으며 아래 내용은 구현 기준이다.
- [확정] Phase 2의 구체적 입력·설정·산출물·API·평가 계약은 [Phase 2 토크나이저 상세 계약](./phase2-tokenizer-contract.md)을 따른다.

## 2. 학습 방식

| 항목 | 설계 | 상태 |
|---|---|---|
| 도구 | SentencePiece | [확정] |
| Vocabulary Size | 16,000 | [확정] |
| 기본 알고리즘 | Unigram | [확정] |
| 입력 단위 | 승인된 Phase 1 `train.jsonl`의 `text_normalized` | [확정] |
| Character coverage | 미정 | [검증 필요] 말뭉치 문자 통계 후 확정 |
| Unicode 정규화 | Phase 1 NFC 입력 + SentencePiece `identity` | [확정] Phase 2 상세 계약 |
| Byte fallback | 미정 | [검증 필요] unknown 비율과 vocab 영향 비교 |
| 학습 corpus 크기 | 미정 | [검증 필요] 데이터 전략 문서 선행 필요 |

- [확정] Unigram 선택은 한국어 형태 경계를 미리 고정하지 않고 subword 후보를 학습하기 위한 프로젝트 기본 설계다.
- [검증 필요] 동일한 학습 표본에서 BPE와 unknown 비율, 평균 token 수 및 압축률을 비교할 수 있다. 변경 시 실험 기록 또는 ADR을 남긴다.

## 3. Special token 규약

16,000 vocabulary 안에 다음 token을 포함한다.

| ID | Token | 용도 | 상태 |
|---:|---|---|---|
| 0 | `<pad>` | batch padding | [확정] |
| 1 | `<unk>` | 미등록 문자·조각 | [확정] |
| 2 | `<bos>` | sequence 시작 | [확정] |
| 3 | `<eos>` | sequence 종료 | [확정] |
| 4 | `<\|system\|>` | system message 시작 | [확정] |
| 5 | `<\|user\|>` | user message 시작 | [확정] |
| 6 | `<\|assistant\|>` | assistant message 시작 | [확정] |
| 7 | `<\|end\|>` | 개별 message 종료 | [확정] |

- [확정] role 및 message 종료 token은 분할되지 않는 user-defined symbol로 등록한다.
- [확정] ID는 학습 명령에서 명시하고 학습 후 자동 테스트로 확인한다.
- [확정] tokenizer model, vocab, 학습 설정 및 special-token mapping을 한 버전 단위로 관리한다.
- [검증 필요] Markdown 표시의 escape 문자는 문서 표기를 위한 것이며 실제 token 문자열에는 역슬래시가 없다.

## 4. 텍스트 정규화 원칙

- [확정] 원문과 정제문을 분리해 보존하고 변환 계보를 기록한다.
- [확정] 한글, 라틴 문자, 숫자 및 일반 문장부호를 근거 없이 제거하지 않는다.
- [확정] Phase 1의 LF·NFC·행 끝 horizontal whitespace 제거를 적용하고 본문 내부 연속 공백·줄바꿈은 보존한다.
- [확정] 개인정보와 라이선스 검증을 통과하지 못한 텍스트는 tokenizer 학습에도 사용하지 않는다.
- [확정] SentencePiece 내부 NFKC 계열 정규화는 적용하지 않고 `identity`를 사용한다.
- [검증 필요] `identity`에서도 SentencePiece whitespace marker가 호환 문자, 수식, 특수문자와 공백 표현에 미치는 영향을 표본 검토한다.
- [검증 필요] 줄바꿈을 문서 경계로 사용할지 별도 경계 token을 둘지는 데이터 전처리 설계에서 정한다.

## 5. 토크나이저 입출력 계약

| 연산 | 입력 | 출력 | shape/형식 |
|---|---|---|---|
| `encode` | 한국어 문자열 | token ID sequence | `[T]`, 각 ID는 `0 <= id < 16,000` |
| batch encode | 문자열 목록 | record별 token IDs와 pieces | 가변 길이 목록; padding은 모델 batch 단계 |
| `decode` | token ID sequence | 문자열 | special token 처리 규칙 적용 |
| model input | token IDs | PyTorch integer tensor | `[B, T]`, `torch.long` |

- [확정] 모델 embedding 입력은 문자열이 아니라 token ID tensor다.
- [확정] tokenizer는 context 제한과 독립적으로 전체 sequence를 encode하며 `DohaLM-Tiny` 입력 block을 구성할 때 `T <= 256`을 적용한다. `DohaLM-Small`의 최대 512는 검토안이다.
- [확정] truncation은 tokenizer 내부에서 조용히 수행하지 않고 데이터 구성 단계에서 명시한다.

## 6. 사전학습 문서 구성

- [확정] 각 문서는 `<bos>`로 시작하고 `<eos>`로 끝낸다.
- [확정] context window를 만들 때 서로 다른 문서를 단순 연결한다면 경계에 최소 `<eos><bos>`를 둔다.
- [검증 필요] 고정 길이 packing 방식과 마지막 조각 처리 방식은 [사전학습 계획](./pretraining-plan.md) 및 데이터 전처리 문서에서 확정한다.
- [제외] 사전학습 일반 텍스트에 SFT role token을 임의 삽입하지 않는다.

## 7. SFT 대화 템플릿

### 7.1 단일 대화

실제 token 문자열 기준 템플릿은 다음과 같다.

```text
<bos><|system|>{system}<|end|><|user|>{user}<|end|><|assistant|>{assistant}<|end|><eos>
```

- [확정] `{system}`이 없는 데이터에는 프로젝트 기본 system 문구를 사용할지 system segment를 생략할지 데이터셋 단위로 고정한다.
- [검증 필요] 기본 system 문구는 SFT 데이터 정책 수립 후 확정한다.

### 7.2 다중 대화

```text
<bos><|system|>{system}<|end|>
<|user|>{user_1}<|end|><|assistant|>{assistant_1}<|end|>
<|user|>{user_2}<|end|><|assistant|>{assistant_2}<|end|><eos>
```

표시용 줄바꿈은 가독성을 위한 것이다. 실제 직렬화에서 줄바꿈을 추가할지는 하나의 규칙으로 고정하고 tokenizer 테스트 fixture에 원문과 token ID를 보존한다.

### 7.3 추론 prompt

```text
<bos><|system|>{system}<|end|><|user|>{user}<|end|><|assistant|>
```

- [확정] 모델은 assistant marker 다음 token부터 생성한다.
- [확정] `<|end|>` 또는 `<eos>`가 생성되면 응답을 종료한다.
- [확정] 학습과 추론은 동일한 직렬화 함수를 사용한다.

## 8. SFT loss mask와 padding

- [확정] system, user, role marker 및 padding target은 `ignore_index`로 설정한다.
- [확정] assistant 본문과 assistant의 `<|end|>` 및 마지막 `<eos>`는 loss 대상에 포함한다.
- [확정] attention에는 causal mask와 `<pad>` key padding mask를 함께 적용한다.
- [확정] label shift 이후에도 loss mask가 정확한 target 위치와 정렬되어야 한다.
- [검증 필요] 다중 turn에서 모든 assistant 답변을 학습할지 마지막 답변만 학습할지는 SFT 데이터셋별로 기록한다. 기본안은 모든 assistant 답변이다.

## 9. 평가와 합격 조건

- [검증 필요] vocab size와 special token ID가 설계와 일치한다.
- [검증 필요] `decode(encode(text))`가 정규화 정책 범위 안에서 의미를 보존한다.
- [검증 필요] 한국어, 영문, 숫자, 공백, emoji, 한자 및 특수문자 표본의 unknown 비율을 기록한다.
- [검증 필요] 평균 문자당 token 수, token 길이 분포 및 256-token 초과 비율을 데이터 유형별로 기록한다.
- [검증 필요] role token이 항상 단일 ID이고 템플릿 round-trip 테스트가 통과한다.
- [검증 필요] 구체적인 허용 임계치는 corpus 통계 없이 임의로 확정하지 않는다.

## 10. 저장 및 버전 관리 항목

- [확정] SentencePiece `.model`과 `.vocab`
- [확정] 전체 trainer argument와 입력 데이터 fingerprint
- [확정] special-token 문자열·ID mapping
- [확정] 정규화, 전처리 및 sampling 설정
- [확정] SentencePiece 버전, seed 지원 여부 및 실행 환경
- [확정] 품질 평가 결과와 알려진 실패 사례
- [확정] 산출물 hash 및 생성 일시

## 11. 검토 필요 사항

- [검증 필요] character coverage, byte fallback 및 identity normalization의 whitespace 실제 동작
- [검증 필요] tokenizer 학습 corpus와 표본 추출 방식
- [검증 필요] 문서 packing 및 경계 처리
- [검증 필요] 기본 system message와 실제 줄바꿈 직렬화

## 12. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] Phase 2 상세 계약을 연결하고 NFC 입력·SentencePiece identity 및 tokenizer/batch 책임 경계를 동기화함 |
