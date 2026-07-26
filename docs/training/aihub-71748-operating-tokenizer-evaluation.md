# AIHUB-71748 운영 16k tokenizer 보완 후보 평가

## 1. 문서 정보와 범위

| 항목 | 내용 |
|---|---|
| 문서 상태 | `approved` |
| 평가일 | 2026-07-26 |
| 범위 | AIHUB-71748 tokenizer development 전용 |
| 선행 문서 | [ADR-003](../decisions/ADR-003-tokenizer-method.md), [Phase 2 계약](./phase2-tokenizer-contract.md), [corpus manifest](../data/aihub-71748-tokenizer-corpus.manifest.yaml), [v2 요약 manifest](../data/aihub-71748-operating-tokenizer-v2.manifest.yaml) |
| Gate 영향 | 이 문서의 사용자 최종 승인으로 Gate 3 `passed`; 후속 별도 Tiny Overfit 승인으로 Gate 7도 `passed` |

- [확정] Pretraining·Overfit·SFT·RLHF·Preference·모델/GPU 학습은 실행하지 않았다.
- [확정] 기존 `operating-16k-v1`은 수정하지 않았다. v2는 별도 외부 디렉터리에 원자적으로 게시했다.
- [확정] 원본 ZIP과 승인 corpus를 읽기 전용으로 사용했으며 원문·실패 문자열을 문서나 평가 artifact에 저장하지 않았다.

## 2. 기존 corpus와 v1 무결성

| 항목 | 재검증 결과 |
|---|---:|
| Training 일반 원천 ZIP | 25 / 25 checksum 일치 |
| records | 107,226 |
| characters | 198,740,203 |
| bytes | 458,343,390 |
| corpus SHA-256 | `sha256:0c7119106261e9a8487b5e2e1ba76ba220761a2fdaeb14738e968b91fdbeeb00` |
| corpus fingerprint | `sha256:2812606509281c9246c56c5bad2efbcf53897a105b75e1843d61b2101891f28c` |
| 제외 subset | Validation·evaluation/benchmark·RLHF·SFT·metadata 미사용 |

`data_info[].contents`만 포함한 기존 corpus를 다시 만들지 않았다. v1 Unigram/BPE bundle도 각각 16,000 pieces, artifact checksum과 fingerprint 재계산을 통과했다.

## 3. 평가 표본과 재현 조건

동일한 Training corpus의 앞 10,000개 비어 있지 않은 물리적 줄을 네 후보 모두에 사용했다. random sampling은 없으므로 seed는 `null`이며, 줄의 원문 대신 length-prefixed content hash만 기록했다.

| 항목 | 값 |
|---|---|
| split | `Training` |
| sampling | `first_10000_nonempty_physical_lines` |
| records | 10,000 |
| sample fingerprint | `sha256:12e54cec6b04420deb5182b74b359b1b9e87edce1428d0e8444fd95ed832f8fa` |
| corpus fingerprint | `sha256:2812606509281c9246c56c5bad2efbcf53897a105b75e1843d61b2101891f28c` |
| 원문 저장 | 0건 |

## 4. v2 학습 설정

| 항목 | v2 Unigram | v2 BPE |
|---|---:|---:|
| model type | `unigram` | `bpe` |
| vocabulary | 16,000 | 16,000 |
| character coverage | 1.0 | 1.0 |
| byte fallback | `true` | `true` |
| normalization | `identity` | `identity` |
| hard vocab limit | `true` | `true` |
| special ID | ADR-003의 0~7 | ADR-003의 0~7 |
| remove extra whitespaces | `false` | `false` |
| add dummy prefix | `false` | `false` |
| escape whitespaces | `true` | `true` |
| allow whitespace-only pieces | `true` | `true` |
| whitespace as suffix | `false` | `false` |
| threads / shuffle | 1 / `false` | 1 / `false` |
| SentencePiece | 0.2.2 | 0.2.2 |

SentencePiece 0.2.2 API probe로 위 whitespace 옵션과 byte fallback의 지원을 확인했다. byte piece 256개는 16,000개 안에 포함되며 special ID를 변경하지 않았다.

## 5. Fingerprint와 checksum

| 후보 | tokenizer fingerprint | model SHA-256 | vocab SHA-256 | config fingerprint |
|---|---|---|---|---|
| v1 Unigram | `sha256:2106dcfbb1ba957da613530759825b95de9356739c55ae870c7cf3279ddd6616` | v1 bundle에서 재검증 | v1 bundle에서 재검증 | v1 bundle 참조 |
| v1 BPE | `sha256:68f9016104db6e2813c37beeecce6c045bb761e26ad22d693592c29a88d7555c` | v1 bundle에서 재검증 | v1 bundle에서 재검증 | v1 bundle 참조 |
| v2 Unigram | `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff` | `sha256:11e536f275b9377794a52c8f3f5fadfe358f631c4b7af51bf9e371d2124fff0a` | `sha256:9030a0cdc2fba938ac2a3fc8d0f7ae259d22b30ab22a2c57edb3d7cbcdfab11b` | `sha256:f436a33df5baba777a72fa70ef121ac610fbf1f50de18b4bdf5e1654adf40936` |
| v2 BPE | `sha256:362a5e9f8e99cb798884397e1b43e87e10f6d13907a9a1d6710e12c423e05822` | `sha256:023fcc4f688bb4f22a43892095f06f0f412acc6f384bbeee0e5c0749efe0cc08` | `sha256:c09d882311f5bd52a4c84f76308032e743ddb4986ac07bce8636889ccf82aa39` | `sha256:f09199ab0a85115fcded1dcfe219d35eca7c4641dcd9bc1903156cb6b4a17dc9` |

동일 config를 별도 경로에서 재학습한 결과 vocab checksum과 실제 표본 10,000건의 encode ID digest는 후보별로 일치했다. 반면 SentencePiece model binary에 출력별 trainer metadata가 포함되어 model SHA와 이를 포함하는 tokenizer fingerprint는 달랐다. 원본 v2 bundle 자체의 checksum·fingerprint 재계산은 일치하지만, 경로가 다른 재학습 binary까지 동일하다는 의미의 결정론은 입증되지 않았다.

## 6. 실제 corpus 표본 비교

속도는 동일 로컬 Windows 환경에서 순차 측정한 참고값이다. `characters/token`은 compression ratio와 같은 정의다.

| 지표 | v1 Unigram | v1 BPE | v2 Unigram | v2 BPE |
|---|---:|---:|---:|---:|
| vocabulary size | 16,000 | 16,000 | 16,000 | 16,000 |
| vocabulary coverage | 99.800695% | 99.796217% | 100% | 100% |
| UNK token | 0.199305% | 0.203783% | 0% | 0% |
| UNK 포함 line | 26.17% | 26.17% | 0% | 0% |
| exact round-trip | 72.35% | 72.35% | 100% | 100% |
| ID 안정성 | 75.09% | 75.09% | 100% | 100% |
| characters/token | 2.1654 | 2.2140 | 2.0729 | 2.1302 |
| tokens/character | 0.4618 | 0.4517 | 0.4824 | 0.4694 |
| 평균 tokens/line | 443.19 | 433.45 | 462.95 | 450.51 |
| token p50 / p95 / p99 | 113 / 1,833 / 3,071 | 111 / 1,795 / 2,993 | 118 / 1,912 / 3,204 | 115 / 1,877 / 3,101 |
| encode lines/s | 11,763 | 5,233 | 9,685 | 5,017 |
| decode lines/s | 3,412 | 2,420 | 5,930 | 3,518 |
| model bytes | 301,616 | 290,865 | 271,029 | 263,742 |
| vocab bytes | 331,383 | 279,319 | 298,621 | 250,392 |
| training seconds | 739.556 | 17.808 | 786.718 | 18.022 |
| 최대 process RSS | 과거 계측 없음 | 과거 계측 없음 | 2,633,977,856 bytes | 887,283,712 bytes |
| 한국어 다문자 piece | 78.8188% | 76.7938% | 59.4875% | 57.3750% |
| 단일 문자 piece | 14.7250% | 16.8938% | 34.8313% | 36.6875% |
| byte pieces | 0 | 0 | 256 | 256 |
| byte piece token 사용 | 0% | 0% | 0.001274% | 0.001310% |

v2는 무손실성과 희귀 문자 복원을 얻는 대신 v1보다 token 수가 약 4% 늘고 한국어 다문자 piece 비율이 낮아졌다. 두 v2 후보 중 BPE가 더 압축적이고 훨씬 빠르게 학습되지만, ADR-003 기준선과 encode 성능은 Unigram이 유리하다.

## 7. Synthetic probe와 실패 원인

일반·띄어쓰기 한국어, 연속/선행/후행 공백, 줄바꿈, 탭, 한영 혼합, 정수·날짜·소수, 영문·대소문자, 특수문자, 이모지, 확장·희귀 Unicode, 합성 URL·이메일·코드의 19개 비민감 probe를 사용했다.

| 결과 | v1 | v2 Unigram | v2 BPE |
|---|---:|---:|---:|
| probe 수 | 19 | 19 | 19 |
| UNK probe | 0 | 0 | 0 |
| exact round-trip 실패 | 집계 기준 통과 | 0 | 0 |
| ID 안정성 실패 | 집계 기준 통과 | 0 | 0 |

실제 표본의 v1 round-trip 실패 2,765건 중 2,617건은 UNK 대체가 동반됐고 148건은 whitespace 표현 차이였다. v2 실제 표본 10,000건의 분류는 `exact=10,000`이며 unknown 대체, whitespace, Unicode normalization, 기타 정보 손실 실패가 모두 0건이다. 실패 문자열이나 원문은 기록하지 않았다.

## 8. 최종 선택과 Gate 3 판정

- [확정] 사용자는 2026-07-26 `operating-16k-v2/unigram-16k`를 DohaLM의 최종 운영 16k tokenizer로 승인했다.
- [확정] v2 BPE는 비교·검증 산출물로 유지하지만 운영 기본값으로 선택하지 않는다.
- [확정] vocabulary 16,000, special ID 0~7, checksum/fingerprint, 동일 표본 A/B, Windows 평가, 원본 불변과 추적 금지 요건을 근거로 Gate 3을 `passed`로 변경한다.
- [확정] 이 승인은 Pretraining·모델 연결·Tiny Overfit·Gate 7·artifact 공개나 재배포를 허용하지 않는다.

### 8.1 재현성 판정 기준

- [확정] Artifact identity는 승인 bundle 자체의 model SHA-256, vocab SHA-256, tokenizer fingerprint와 manifest checksum으로 판정한다. 운영 및 후속 학습 설정은 이 승인 bundle을 그대로 참조해야 한다.
- [확정] Functional reproduction은 corpus fingerprint, training configuration fingerprint, SentencePiece version, vocabulary 크기·내용/checksum, special-token ID map, 10,000건 encode ID digest, synthetic probe, 실제 표본 UNK·round-trip 지표의 일치로 판정한다.
- [확정] 출력별 trainer metadata로 model binary SHA-256만 다르고 위 기능 항목이 모두 같으면 functional reproduction은 통과한다.
- [확정] Functional reproduction을 통과한 새 binary도 기존 승인 bundle과 동일 artifact로 간주하지 않으며 운영에 쓰려면 별도 승인이 필요하다.

## 9. Artifact 위치

논리 경로는 다음과 같으며 absolute path를 코드나 공개 설정에 하드코딩하지 않는다.

- v1: `configured_external_root/analysis/tokenizer-development/AIHUB-71748/operating-16k-v1/`
- v2: `configured_external_root/analysis/tokenizer-development/AIHUB-71748/operating-16k-v2/`
- v2 비교: `comparison-v1-v2.json`
- 평가 표본: `evaluation-sample.manifest.json`
- corpus 재검증: `source-corpus-verification.json`
- 메모리·재현 진단: `memory-validation/training-memory-validation.json`

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 사용자가 v2 Unigram을 최종 운영 tokenizer로 승인하고 artifact identity·functional reproduction 기준 및 Gate 3 `passed`를 확정함 |
| 2026-07-26 | [검증 필요] v1 무결성을 재검증하고 byte fallback·whitespace 보존 v2 Unigram/BPE를 동일 10,000건 표본과 19개 synthetic probe로 비교해 v2 Unigram을 Gate 3 승인 후보로 추천함 |
| 2026-07-26 | [검증 필요] v1 후보의 실제 표본 UNK·round-trip 차단 근거를 기록함 |
