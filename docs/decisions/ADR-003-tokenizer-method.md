# ADR-003: SentencePiece Unigram 토크나이저 방식

- 문서 상태: `approved`
- 결정일: 2026-07-23
- 구현 상태: [확정] `operating-16k-v2/unigram-16k` 구현·검증·운영 승인 완료
- 기준 설계: [DohaLM 토크나이저 설계](../training/tokenizer-design.md)
- 관련 모델 결정: [ADR-002: DohaLM-Tiny 모델 아키텍처](./ADR-002-tiny-model-architecture.md)

## 결정 배경

DohaLM은 한국어 언어모델을 랜덤 초기화부터 직접 사전학습하므로 모델과 데이터에 맞는 토크나이저도 직접 학습해야 한다. `DohaLM-Tiny`의 Vocabulary Size 16,000과 SFT 대화 형식을 일관되게 지원할 토큰화 방식이 필요하다.

- [확정] 외부 완성 모델의 토크나이저를 핵심 토크나이저로 사용하지 않는다.
- [확정] tokenizer 산출물과 설정은 모델 checkpoint의 호환성 일부로 관리한다.
- [검증 필요] tokenizer 학습 corpus와 세부 문자 처리 설정은 데이터 라이선스와 corpus 통계에 의존한다.

## SentencePiece를 사용하는 이유

- [확정] raw text에서 subword vocabulary를 직접 학습할 수 있다.
- [확정] 한국어 공백만을 단어 경계로 가정하지 않고 문장을 subword sequence로 변환할 수 있다.
- [확정] model, vocabulary 및 trainer 설정을 산출물로 보존할 수 있다.
- [확정] special token ID와 user-defined symbol을 명시적으로 관리할 수 있다.
- [가정] 제한된 프로젝트 범위에서 tokenizer 학습·배포 인터페이스를 단순하게 유지할 수 있다.

## Unigram을 선택한 이유

- [확정] 여러 subword 분해 후보의 확률 모델을 학습하는 Unigram을 기본 알고리즘으로 사용한다.
- [가정] 한국어 형태 경계를 사전에 고정하지 않고 corpus 기반 subword 후보를 선택하는 데 적합하다.
- [확정] 동일 corpus와 설정에서 재학습·평가 가능한 기준 방식을 하나로 고정한다.
- [검증 필요] 실제 한국어 token 효율과 unknown 처리 품질은 corpus 기반 평가로 확인한다.

## BPE와의 비교

| 항목 | Unigram | BPE |
|---|---|---|
| 기본 원리 | 확률 모델에서 subword 집합을 가지치기 | 빈도 높은 symbol pair를 순차 병합 |
| 분해 후보 | 여러 후보와 확률을 모델링 가능 | 학습된 병합 규칙에 따른 결정적 분해 중심 |
| 구현 도구 | SentencePiece에서 지원 | SentencePiece에서 지원 |
| 프로젝트 결정 | [확정] 기본 방식으로 채택 | [제외] 현재 기본 방식으로 채택하지 않음 |
| 재검토 | corpus 평가가 나쁠 때 비교 실험 | 동일 표본·vocab으로 비교 후보 |

- [확정] BPE가 일반적으로 열등하다고 단정하지 않는다.
- [검증 필요] 재검토 시 동일한 학습·평가 corpus, Vocabulary Size 16,000과 special token 조건으로 unknown 비율, 평균 token 길이 및 downstream 영향을 비교한다.

## Vocabulary Size 16,000을 선택한 이유

- [확정] `DohaLM-Tiny`의 모델 사양과 기존 프로젝트 범위에서 Vocabulary Size 16,000이 이미 결정되었다.
- [확정] special token을 포함한 전체 vocabulary 수가 16,000이다.
- [확정] Tiny에서는 Token Embedding이 `16,000×384=6,144,000`개의 parameter를 차지하며 tied LM Head와 공유한다.
- [가정] 소형 모델의 parameter budget과 한국어 subword 표현력을 함께 고려한 출발점이다.
- [검증 필요] 16,000이 실제 corpus에서 최적인지는 token 길이 분포, unknown 처리 및 학습 결과로 검증한다.

## 직접 토크나이저를 학습한다는 원칙

- [확정] 라이선스 검토를 통과한 프로젝트 corpus로 SentencePiece model을 직접 학습한다.
- [확정] 학습 corpus fingerprint, 전체 trainer argument, SentencePiece 버전, special-token mapping과 산출물 hash를 기록한다.
- [확정] `.model`과 `.vocab`을 같은 tokenizer version으로 관리한다.
- [확정] 사전학습과 SFT 중간에 tokenizer 또는 token ID를 임의 변경하지 않는다.
- [확정] tokenizer가 바뀌면 embedding과 LM Head shape·의미 및 checkpoint 호환성을 재검토한다.

## 특수 토큰 목록

| ID | 실제 Token | 용도 | 상태 |
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
- [확정] 표 안의 역슬래시는 Markdown table escape이며 실제 token 문자열에는 포함되지 않는다.

## 운영 tokenizer 확정 설정

- [확정] 운영 version과 후보는 `operating-16k-v2/unigram-16k`다.
- [확정] AIHUB-71748 Training의 `data_info[].contents` 전용 승인 corpus를 사용한다.
- [확정] SentencePiece 0.2.2, vocabulary 16,000, `character_coverage=1.0`, `byte_fallback=true`, `normalization_rule_name=identity`, hard vocabulary limit를 사용한다.
- [확정] extra whitespace 제거와 dummy prefix를 끄고 whitespace-only piece를 허용하며 special token ID 0~7을 유지한다.
- [확정] 승인 bundle의 manifest/model/vocab checksum과 tokenizer fingerprint로 artifact identity를 판정한다.
- [확정] 별도 경로 재학습은 corpus/config fingerprint, SentencePiece version, vocabulary·special ID, encode ID digest와 품질 지표가 일치하면 functional reproduction으로 인정하되 새 binary의 운영 사용은 재승인한다.

## 아직 확정되지 않은 항목

- [검증 필요] 문서 packing 및 경계 처리의 세부 방식
- [검증 필요] 기본 system message와 실제 줄바꿈 직렬화
- [검증 필요] 다른 corpus 분포와 실제 모델 학습 단계의 downstream 품질 기준

## Character coverage 검증 계획

1. [검증 필요] 라이선스 승인 corpus의 Unicode code point와 문자군 분포를 집계한다.
2. [검증 필요] 한국어, 라틴 문자, 숫자, 한자, emoji 및 특수문자의 포함·제외 영향을 표본 검토한다.
3. [검증 필요] 후보 character coverage별 unknown 비율, vocabulary 구성 및 평균 token 길이를 비교한다.
4. [확정] corpus 통계 없이 값을 임의 확정하지 않는다.

## Normalization 검증 계획

1. [검증 필요] SentencePiece 후보 normalization rule의 실제 변환 예시를 저장한다.
2. [검증 필요] NFC/NFKC 계열 처리가 한글, 호환 문자, 수식, 단위 및 특수문자 의미에 미치는 영향을 비교한다.
3. [검증 필요] 정규화 전후 문자열과 `decode(encode(text))` 결과를 회귀 fixture로 관리한다.
4. [확정] 원문과 정제문은 분리해 보존하고 변환 계보를 기록한다.

## Byte fallback 검증 계획

1. [검증 필요] byte fallback off/on 후보를 동일 corpus와 vocabulary 조건에서 학습한다.
2. [검증 필요] 미등록 문자, emoji, 희귀 한자와 혼합 언어 표본의 unknown 비율을 비교한다.
3. [검증 필요] 평균 token 길이, vocabulary 사용량 및 비정상적으로 긴 byte sequence 사례를 기록한다.
4. [확정] 평가 결과 없이 활성화 여부를 결정하지 않는다.

## 데이터 라이선스 의존성

- [확정] tokenizer 학습도 데이터 사용에 해당하므로 corpus별 학습 허용 조건을 확인한다.
- [확정] 출처, 버전, 취득일, 라이선스, 사용 조건 및 재배포 가능 범위를 기록한다.
- [확정] 출처 또는 라이선스를 확인할 수 없는 corpus는 tokenizer 학습에 사용하지 않는다.
- [검증 필요] tokenizer `.model`과 `.vocab` 공개가 원본 데이터 조건에 미치는 영향을 데이터셋별로 검토한다.
- [검증 필요] 데이터 전략과 전처리 문서가 확정되기 전 실제 corpus 학습을 시작하지 않는다.

## 재검토 조건

- [검증 필요] special token이 단일 ID로 유지되지 않거나 ID mapping이 설계와 다르다.
- [검증 필요] 한국어 또는 필수 문자군에서 unknown 비율이나 token 길이가 허용하기 어려운 수준이다.
- [검증 필요] normalization이 의미 있는 정보를 손상한다.
- [검증 필요] byte fallback 비교 결과가 현재 선택의 변경 필요성을 보인다.
- [검증 필요] Vocabulary Size 16,000이 모델 품질 또는 sequence 효율의 명확한 병목으로 측정된다.
- [검증 필요] corpus 라이선스가 tokenizer 산출물의 사용·공개를 허용하지 않는다.
- [확정] 알고리즘, vocabulary 또는 special-token mapping 변경은 checkpoint 호환성 영향을 포함한 후속 ADR로 기록한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] v2 Unigram 운영 bundle, 세부 SentencePiece 설정, artifact identity·functional reproduction과 Gate 3 승인 결과를 반영함 |
| 2026-07-23 | [확정] SentencePiece Unigram, Vocabulary Size 16,000 및 special-token 정책을 결정으로 기록함 |
