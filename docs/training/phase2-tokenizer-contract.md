# DohaLM Phase 2 토크나이저 상세 계약

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `approved` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [Phase 1 데이터 계약](../data/phase1-data-contract.md), [데이터셋 후보 등록부](../data/dataset-candidate-registry.md), [구조 분석 요약](../data/analysis/dataset-analysis-summary.md), [데이터셋 승인 로그](../data/dataset-approval-log.md), [평가 제외 목록](../data/evaluation-exclusion-list.md), [토크나이저 설계](./tokenizer-design.md), [핵심 개발 기능명세서](../architecture/core-development-feature-specification.md), [ADR-003](../decisions/ADR-003-tokenizer-method.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | 별도 사용자 승인 후 [사전학습 계획](./pretraining-plan.md)과 Gate 7 검증 |
| 구현 전 필수 여부 | Phase 2 구현 전 예 |

- [확정] 이 문서는 Phase 2 구현에 적용할 corpus 입력, SentencePiece 학습 설정, vocabulary, special token, 산출물, fingerprint, encode/decode, 평가와 호환성 계약의 단일 기준이다.
- [확정] 문서 상태 `approved`는 2026-07-26 사용자 최종 승인과 Gate 3 통과를 반영하며 Gate 7 또는 모델 학습 승인을 의미하지 않는다.
- [확정] Gate 1~6은 `passed`, Gate 7은 `planned`이며 Phase 1 DATA-001~016은 `verified`다.
- [확정] SentencePiece `0.2.2` 의존성과 [synthetic smoke pipeline](./tokenizer-smoke.md)은 구현·검증됐다.
- [확정] AIHUB-71748 제한 Training corpus, 16,000 vocabulary 후보 비교와 운영 v2 Unigram 8개 산출물은 구현·검증·승인됐다.

## 2. 목적과 범위

Phase 2는 다음 기능을 구현하고 검증할 준비를 한다.

| 기능 ID | 범위 | 계약 상태 |
|---|---|---|
| TOK-001 | corpus 입력 검증 | `review` |
| TOK-002 | SentencePiece 학습 | `review` |
| TOK-003 | vocabulary size 16,000 검증 | `review` |
| TOK-004 | special token ID 검증 | `review` |
| TOK-005 | encode | `review` |
| TOK-006 | decode | `review` |
| TOK-007 | round-trip 검사 | `review` |
| TOK-008 | tokenizer fingerprint | `review` |
| TOK-009 | 한국어 분할 통계 | `review` |
| TOK-010 | unknown·fallback 통계 | `planned` |
| TOK-011 | tokenizer artifact 저장 | `review` |
| TOK-012 | tokenizer 변경 호환성 검사 | `review` |

- [제외] 실제 corpus 다운로드·승인, 실제 토크나이저 학습, 데이터 tokenization·binary packing, 모델·학습·SFT·API·Frontend·DB·Docker·CI 구현은 이번 문서 작업의 범위가 아니다.
- [확정] Phase 2 MVP는 SentencePiece Unigram만 구현한다. BPE, WordPiece, 형태소 분석기·공백·문자 단위 방식과 외부 pretrained tokenizer 재사용은 제외한다.

## 3. Vocabulary 계약

- [확정] 운영 `DohaLM-Tiny` 토크나이저의 vocabulary는 special token을 포함해 정확히 16,000개다.
- [확정] 유효 ID는 연속된 `0..15,999`이며 piece와 ID는 각각 중복될 수 없다.
- [확정] 실제 `tokenizer.model`의 총 piece 수를 검사하며 trainer 인자만으로 통과 처리하지 않는다.
- [확정] 운영 후보는 `hard_vocab_limit=true`를 기본 계약으로 사용하고 16,000개를 충족하지 못하면 `TOKENIZER_VOCAB_SIZE_MISMATCH`로 실패한다.
- [가정] synthetic fixture smoke에서는 corpus 규모에 맞춘 별도 작은 vocabulary를 허용한다. 이 산출물은 운영 후보·모델 호환 artifact로 사용할 수 없다.

## 4. Special token 계약

승인된 [ADR-003](../decisions/ADR-003-tokenizer-method.md)을 우선해 다음 8개 token과 ID를 고정한다.

| ID | 실제 token | 용도 | 상태 |
|---:|---|---|---|
| 0 | `<pad>` | padding | [확정] |
| 1 | `<unk>` | unknown | [확정] |
| 2 | `<bos>` | sequence 시작 | [확정] |
| 3 | `<eos>` | sequence 종료 | [확정] |
| 4 | `<\|system\|>` | system 발화 시작 | [확정] |
| 5 | `<\|user\|>` | user 발화 시작 | [확정] |
| 6 | `<\|assistant\|>` | assistant 발화 시작 | [확정] |
| 7 | `<\|end\|>` | 개별 발화 종료 | [확정] |

- [확정] 표의 역슬래시는 Markdown 표기용이며 실제 문자열에는 포함되지 않는다.
- [확정] ID 4~7은 분할되지 않는 user-defined symbol로 등록하고 학습 후 실제 할당 순서와 단일 piece 여부를 검증한다.
- [확정] special token은 일반 piece로 대체되거나 normalization으로 변경돼서는 안 된다.
- [확정] encode의 자동 BOS/EOS 삽입과 decode의 special token 보존·제거는 명시적 옵션으로만 수행한다.
- [검증 필요] 첨부 요청의 우선 예시였던 `<mask>`, `<sep>`, `<user>`, `<assistant>`는 ADR-003과 충돌하므로 채택하지 않았다. 이 매핑을 바꾸려면 ADR 재검토가 필요하다.
- [검증 필요] 일반 corpus에 예약 문자열이 나타나면 special token으로 해석한다. literal escape 방식은 Phase 2 이후에 결정한다.

## 5. Corpus 입력 계약

- [확정] 입력은 [Phase 1 데이터 계약](../data/phase1-data-contract.md)을 통과한 cleaned dataset artifact만 허용한다.
- [확정] 실제 corpus subset은 [후보 등록부](../data/dataset-candidate-registry.md)와 [승인 로그](../data/dataset-approval-log.md)에서 `approved_tokenizer_development` 또는 `approved_tokenizer_candidate` 상태를 받은 경우에만 허용한다.
- [확정] 현재 등록된 AI Hub 후보 5개의 tokenizer 승인은 모두 `pending`이며 approved tokenizer corpus는 0개다.
- [확정] 2026-07-23 구조 분석은 ZIP·형식 분포만 확인했으며 ZIP 내부 text field와 schema를 확인하지 않았으므로 corpus 승인 근거로 단독 사용할 수 없다.
- [확정] AIHUB-71748 [안전 표본 dry-run](../data/analysis/AIHUB-71748-sampling.md)은 안전 entry 0건·추출 0건이므로 tokenizer corpus 입력이나 승인 근거가 아니다.
- [확정] 기본 학습 입력은 승인된 `train.jsonl`의 `text_normalized`다.
- [확정] `records.jsonl`은 통계 또는 명시적으로 승인된 목적에서만 허용하며 split·누수 목적을 manifest에 기록한다.
- [제외] `data/raw/`, `rejections.jsonl`, `duplicates.jsonl`, `validation.jsonl`, `test.jsonl`, 미승인 corpus, `pii_status != clear`, `license_status != approved`인 corpus를 직접 학습 입력으로 사용하지 않는다.
- [확정] 입력 text는 UTF-8이어야 하고 accepted record만 포함해야 한다. 빈 corpus는 실패한다.

## 6. Corpus 승인과 계보 조건

다음 조건을 모두 만족하지 못하면 TOK-001에서 학습을 차단한다.

1. [확정] Phase 1 pipeline 산출물이다.
2. [확정] `license_status=approved`, `approval_status=approved`, `pii_status=clear`다.
3. [확정] dataset fingerprint와 source·artifact manifest가 존재한다.
4. [확정] manifest와 입력 artifact checksum이 재계산 결과와 일치한다.
5. [확정] exact duplicate 제거와 직접 split leakage 검사를 통과했다.
6. [확정] 실제 사용 split, record 수, 문자 수와 byte 수가 corpus manifest에 기록된다.

## 7. Corpus 규모 단계

| 단계 | 목적 | 권장 범위 | 운영 artifact 사용 |
|---|---|---|---|
| Smoke | trainer·artifact·encode/decode 동작 확인 | 직접 작성한 synthetic 10~100 records | 금지 |
| Development | 설정 비교·한국어 통계·초기 후보 | 약 10~50 MiB 이상 | [검증 필요] 개발 후보만 |
| Candidate | Gate 3 비교 후보 | 약 100~500 MiB 이상 | [검증 필요] 승인 결과에 따름 |
| Final | 최종 운영 후보 학습 | 승인된 사전학습 분포를 대표하는 corpus | 사용자 승인 필요 |

- [가정] 위 규모는 계획 범위이지 Gate의 절대 합격선이 아니다.
- [검증 필요] 실제 record·byte 상한과 최종 corpus 규모는 데이터 확보 후 정한다.

## 8. 결정론적 샘플링과 source 혼합

- [확정] sampling은 고정 seed, stable `record_id`, dataset fingerprint를 사용하며 입력 순서·OS·CWD에 독립적이어야 한다.
- [확정] Python 내장 `hash()`는 프로세스별 결과가 달라질 수 있으므로 금지한다.
- [확정] 권장 ranking key는 UTF-8 바이트의 `SHA-256(seed || record_id)`이며 연결 방식과 canonical encoding을 resolved config에 고정한다.
- [검증 필요] `max_records`, `max_bytes`와 실제 sampling 크기는 corpus 승인 뒤 정한다.

여러 source를 혼합할 때 manifest에 다음을 기록한다.

| 필드 | 의미 |
|---|---|
| `source_name` | 사람이 식별하는 source 이름 |
| `dataset_id`, `dataset_version` | registry 식별자 |
| `source_fingerprint` | 승인 artifact fingerprint |
| `input_record_count`, `input_character_count` | sampling 전 규모 |
| `sampled_record_count`, `sampled_character_count` | sampling 후 규모 |
| `configured_weight` | 설정된 혼합 weight |
| `actual_contribution_ratio` | 실제 문자 또는 record 기여율과 분모 |

- [검증 필요] source별 최종 weight와 지배 비율 합격선은 실제 분포 검토 후 정한다.

## 9. Unicode와 whitespace 계약

- [확정] 학습 입력은 Phase 1이 생성한 NFC `text_normalized`다.
- [확정] SentencePiece의 `normalization_rule_name`은 `identity`로 고정해 추가 NFKC 계열 의미 변화를 피한다.
- [확정] corpus fingerprint는 SentencePiece에 전달되는 NFC 문자열과 연결한다.
- [검증 필요] `identity`에서도 SentencePiece의 whitespace marker, 문장 시작 공백, 연속 공백, 줄바꿈과 빈 줄 표현을 fixture와 후보 corpus에서 확인한다.
- [확정] tokenizer wrapper가 연속 공백이나 줄바꿈을 임의로 축약해서는 안 된다.
- [검증 필요] SentencePiece 옵션만으로 원문의 모든 whitespace를 보존하기 어렵거나 vocabulary 효율과 충돌하면 실패 사례를 보존하고 후보 비교 뒤 결정한다.

## 10. Character coverage와 byte fallback

| 항목 | 기준선 후보 | 비교 후보 | 최종 상태 |
|---|---|---|---|
| `character_coverage` | `[후보] 0.9995` | `0.9999`, `1.0` | [검증 필요] corpus 통계와 사용자 승인 |
| `byte_fallback` | `[후보] false` | `true` | [검증 필요] 후보 비교 후 결정 |

- [확정] coverage 비교는 한국어 완성형 음절, 한자, 영문, 숫자, 문장부호, 기술 기호, 이모지, 희귀 문자와 vocabulary 효율을 포함한다.
- [확정] byte fallback을 켜면 byte piece가 16,000 vocabulary 일부를 사용하므로 실제 piece 수와 일반 한국어 분할 품질을 함께 본다.
- [확정] fallback 활성화 여부와 UNK rate는 별도 지표로 보고한다.

## 11. Unknown 처리와 통계

- [확정] `<unk>`의 ID는 1이다.
- [확정] 전체 token 수, UNK 수·비율, UNK 포함 record 수·비율과 문자 유형별 사례를 기록한다.
- [확정] 원문 전체는 평가 artifact에 복사하지 않고 제한된 안전한 preview 또는 Unicode code point·범주 통계만 보존한다.
- [검증 필요] UNK rate 정량 합격선은 실제 corpus 전에는 정하지 않는다.

## 12. SentencePiece 학습 설정 계약

| 설정 | 값·상태 |
|---|---|
| `model_type` | [확정] `unigram` |
| `vocab_size` | [확정] `16000` |
| `normalization_rule_name` | [확정] `identity` |
| `pad_id`, `unk_id`, `bos_id`, `eos_id` | [확정] `0`, `1`, `2`, `3` |
| `user_defined_symbols` | [확정] ADR-003의 ID 4~7 문자열, 순서 검증 필수 |
| `character_coverage` | [후보] `0.9995`; 최종 미정 |
| `byte_fallback` | [후보] 기준선 `false`, 비교 `true` |
| `hard_vocab_limit` | [확정] 운영 후보 `true`; 작은 fixture 예외 |
| `split_digits`, `split_by_unicode_script`, `split_by_whitespace`, `split_by_number` | [검증 필요] |
| `max_sentence_length`, `input_sentence_size`, `seed_sentencepiece_size` | [검증 필요] |
| `shuffle_input_sentence`, `num_threads` | [검증 필요] 결정론 실험 후 결정 |
| `control_symbols` | [검증 필요] 기본 사용 필요성 없음; user-defined와 동시 사용 방식 검증 |

- [확정] SentencePiece `0.2.2` synthetic smoke에서 user-defined symbol이 입력 순서대로 ID 4~7을 받고 단일 symbol로 유지됨을 검사했다.
- [확정] trainer 실행 후 모든 resolved option을 기록하며 라이브러리 기본값에 암묵적으로 의존하지 않는다.

## 13. Random seed와 결정론 수준

다음 정보를 항상 기록한다.

`Python seed`, corpus sampling seed, SentencePiece seed·shuffle 관련 값, `num_threads`, SentencePiece/Python/OS version, Git SHA, corpus fingerprint, resolved tokenizer config.

| 수준 | Gate 3 기대 |
|---|---|
| 입력 corpus 결정론 | 같은 승인 입력에서 동일 canonical corpus manifest |
| 설정 결정론 | 같은 명시 설정에서 동일 resolved config checksum |
| sampling 결정론 | 입력 순서·CWD·OS 경로와 무관한 동일 record 집합·순서 |
| artifact checksum 결정론 | [확정] 승인 bundle identity에는 bitwise checksum을 요구하고 별도 경로 재학습에는 functional reproduction 기준을 적용 |
| piece 목록 결정론 | 동일 환경·version·thread에서 ID·piece·score 목록 일치 |
| encode 결과 결정론 | 동일 model과 입력에서 ID·piece 결과 일치 |

- [확정] SentencePiece 학습의 플랫폼 간 bitwise 동일성을 근거 없이 보장하지 않는다.
- [확정] Artifact identity는 승인 bundle의 model/vocab checksum, tokenizer fingerprint와 manifest checksum으로 판정한다.
- [확정] Functional reproduction은 corpus/config fingerprint, SentencePiece version, vocabulary·special ID, encode ID digest, synthetic probe와 실제 표본 UNK·round-trip 지표가 모두 일치해야 한다.
- [확정] 출력 경로별 trainer metadata 때문에 model binary SHA-256만 다른 경우 위 기능 항목이 모두 같으면 functional reproduction을 통과한 것으로 인정한다. 새 binary는 별도 artifact이며 운영 사용 전 재승인한다.

## 14. Artifact 구조와 무결성

- [가정] 권장 논리 경로는 `artifacts/tokenizers/<tokenizer_id>/<tokenizer_version>/`이다. 실제 저장 위치는 [산출물 및 설정 정책](../governance/artifact-and-configuration-policy.md)에 따라 외부 artifact root를 사용할 수 있다.
- [확정] binary와 대용량 artifact는 Git에서 추적하지 않는다.

필수 산출물은 다음 8개다.

1. `tokenizer.model`
2. `tokenizer.vocab`
3. `tokenizer-config.yaml`
4. `tokenizer-manifest.json`
5. `tokenizer-statistics.json`
6. `tokenizer-evaluation.json`
7. `corpus-manifest.json`
8. `training-log.txt`

선택 산출물은 `special-tokens.json`, `compatibility-report.json`이다.

- [확정] staging directory에서 전부 생성한 뒤 load, checksum, piece 수, mapping, fingerprint와 encode/decode smoke를 검증하고 최종 경로에 atomic publish한다.
- [확정] 실패하면 최종 경로에 부분 artifact가 남지 않아야 하며 기존 version을 덮어쓰지 않는다.

## 15. Tokenizer manifest schema

`tokenizer-manifest.json`은 최소 다음 필드를 가진다.

| 필드 | 계약 |
|---|---|
| `schema_version` | manifest schema version |
| `tokenizer_id`, `tokenizer_version`, `status` | tokenizer 식별·상태 |
| `created_at`, `git_sha` | 생성 시각·코드 revision |
| `python_version`, `sentencepiece_version` | 실행 환경 |
| `model_type`, `vocab_size`, `actual_piece_count` | 방식·요청·실제 piece 수 |
| `special_tokens` | token 문자열→ID mapping |
| `normalization_rule`, `character_coverage`, `byte_fallback` | 문자 처리 설정 |
| `training_seed`, `num_threads` | 결정론 관련 설정 |
| `corpus_dataset_ids`, `corpus_fingerprints` | 입력 데이터 계보 |
| `corpus_record_count`, `corpus_character_count`, `corpus_byte_count` | 입력 규모 |
| `resolved_config_checksum` | 적용 설정 checksum |
| `model_checksum`, `vocab_checksum` | 핵심 artifact checksum |
| `tokenizer_fingerprint` | 호환성 식별자 |

- [확정] artifact 경로가 필요한 경우 artifact root 상대 POSIX 경로만 기록한다.
- [확정] 절대 경로, 사용자명과 머신명은 fingerprint 입력에서 제외한다.

## 16. Tokenizer fingerprint

- [확정] fingerprint는 `sha256:<64 lowercase hex>` 형식이다.
- [확정] canonical JSON 또는 동등한 명시적 직렬화 규칙을 사용하고 key 정렬·UTF-8·숫자 표현을 schema에 고정한다.
- [확정] 입력은 tokenizer schema version, model type, vocab size, ID 순서의 piece·ID·score, special mapping, normalization, coverage, fallback, SentencePiece version, resolved config의 결정론적 필드와 정렬된 corpus fingerprint 목록이다.
- [확정] `created_at`, 절대·임시 경로, 실행 시간, 로그 timestamp, 사용자명과 머신명은 제외한다.
- [확정] 실행 시각만 바뀌어도 fingerprint가 달라지는 구현은 실패다.

## 17. Encode 계약

| 항목 | 계약 |
|---|---|
| 입력 | 문자열 1개 또는 문자열 목록 |
| 최소 출력 | token ID 목록과 piece 문자열 목록 |
| `add_bos` | 기본 `false` |
| `add_eos` | 기본 `false` |
| `truncation` | 기본 `false` |
| `max_length` | 기본 `null`; 양의 정수만 허용 |
| padding | [제외] tokenizer MVP에서 자동 수행하지 않고 batch 단계가 담당 |

- [확정] 단일 입력의 ID와 piece 길이는 같고 모든 ID가 `0..15,999` 범위여야 한다.
- [확정] `max_length`를 초과하고 `truncation=false`이면 조용히 자르지 않고 `TOKENIZER_ENCODE_ERROR`로 실패한다.
- [확정] list 입력은 입력 순서와 각 record 경계를 보존한다.

## 18. Decode 계약

| 항목 | 계약 |
|---|---|
| 입력 | token ID 목록 |
| 출력 | 문자열 |
| ID 검증 | 음수와 `>=16000`, 정수가 아닌 ID 거부 |
| 빈 목록 | 빈 문자열 반환 후보를 구현 테스트로 고정 |
| `skip_special_tokens` | [후보] 기본 `false` |

- [확정] 잘못된 ID는 `TOKENIZER_INVALID_TOKEN_ID`, decode 실패는 `TOKENIZER_DECODE_ERROR`로 구분한다.
- [확정] round-trip 평가는 special token이 없는 일반 text를 기본으로 한다.
- [검증 필요] 빈 목록과 `skip_special_tokens` 기본값은 wrapper API 승인 전 최종 확정한다.

## 19. Round-trip 계약

- [확정] exact round-trip은 `decode(encode(text)) == text`로 정의한다.
- [확정] normalized round-trip은 Phase 1 NFC·줄바꿈 정책으로 양쪽을 비교 정규화한 결과의 일치다.
- [확정] 일반 한국어, 영문 혼합, 숫자·날짜, 문장부호, 이모지, 연속 공백, 줄바꿈, 희귀 문자와 special token 문자열을 별도 범주로 평가한다.
- [확정] exact 실패와 normalized 실패를 구분하고 입력 전체 대신 안전한 최소 재현 사례·Unicode code point 정보를 보존한다.
- [검증 필요] 정량 합격선은 corpus 후보 실험 전에 임의로 만들지 않는다.

## 20. Token 길이와 한국어 분할 통계

- [확정] 토크나이저는 모델 context length 256과 독립적으로 전체 sequence를 encode할 수 있어야 한다.
- [확정] tokenizer 평가 단계에서 무조건 256 token으로 잘라 corpus 통계를 왜곡하지 않는다.

필수 길이 통계:

`문자당 token`, `record당 token`, 평균, 중앙값, p90, p95, p99, 최댓값, 256 token 초과 record 수·비율.

필수 한국어·혼합 통계:

`전체 문자 수`, `전체 token 수`, 평균 문자/token, token/문자, token/어절, 한국어 음절 token 비율, 단일 문자 piece 비율, 2자 이상 한국어 piece 비율, 공백 marker piece 비율, 숫자·영문·문장부호 piece 통계, 이모지·희귀 문자 처리, UNK rate.

- [확정] `어절`은 단순 whitespace split 기준이며 형태소 정확도로 표현하지 않는다.

## 21. Piece 품질 검사

다음 목록과 집계 기준을 `tokenizer-statistics.json`에 기록한다.

- 상·하위 빈도 piece와 사용되지 않은 piece
- 단일 문자, 숫자 전용, 문장부호 전용, 공백 marker piece
- 영문 전용, 한글 전용, 혼합 script piece
- 비정상 control 문자 piece

- [확정] 빈도는 학습 corpus를 완성된 후보 tokenizer로 다시 encode해 계산한다.
- [확정] 개별 원문 전체는 통계 artifact에 저장하지 않는다.

## 22. Special token 검증

1. [확정] 8개 token이 모두 존재한다.
2. [확정] ID 0~7과 문자열이 ADR-003에 정확히 일치한다.
3. [확정] ID·문자열 중복이 없다.
4. [확정] 일반 text encode에서 예약 token이 임의 생성되지 않는다.
5. [확정] 명시 입력 시 각 token이 단일 special piece다.
6. [확정] decode의 보존·skip 옵션이 계약대로 동작한다.
7. [확정] 저장·새 process load 후 mapping이 같다.
8. [확정] model config의 `pad_id`와 loss masking 계약에 연결된다.

## 23. 호환성 계약

| 수준 | 의미 |
|---|---|
| `compatible` | piece ID mapping과 encode 의미가 같고 기존 checkpoint에 적용 가능 |
| `conditionally_compatible` | mapping은 같지만 metadata·평가·consumer 조건 확인이 필요 |
| `breaking` | 기존 embedding/checkpoint 의미와 호환되지 않음 |

비교 필드는 vocab size, special 문자열·ID, normalization, 전체 piece ID mapping, corpus fingerprint, SentencePiece version, byte fallback과 character coverage다.

다음 변경은 `breaking`이다.

- special token 문자열 또는 ID 변경
- 기존 piece ID의 대규모 변경
- vocabulary size, normalization 또는 byte fallback 변경
- 동일 tokenizer version에 서로 다른 fingerprint

- [확정] 새 tokenizer를 기존 checkpoint에 임의 적용하지 않는다.
- [확정] tokenizer fingerprint를 model config와 checkpoint manifest에 필수로 기록한다.

## 24. Tokenizer ID와 version 규칙

- [가정] ID 후보는 `dohalm-ko-unigram`, 초기 version 예시는 `0.1.0`이다. 이번 문서는 실제 release·tag·version을 생성하거나 확정하지 않는다.
- [가정] SemVer를 적용한다면 piece mapping이 없는 manifest·통계 교정은 PATCH, corpus·설정 변경으로 mapping이 달라지면 MINOR, special token·normalization·방식 변경은 MAJOR 후보로 분류한다.
- [검증 필요] 프로젝트 전체 SemVer 정책과 tokenizer 독립 version 적용은 [버전 계획](../project/version-plan.md)에서 최종 결정한다.
- [확정] fingerprint가 달라졌는데 같은 version으로 overwrite하는 것은 금지한다.

## 25. 오류 계약

숫자형 오류 코드는 확정하지 않는다. 안전 메시지에는 원문·절대 경로·사용자명·credential을 포함하지 않는다.

| 오류 코드 | 단계 | 전체 실패 | 재시도 | 로그 | 안전한 메시지 | 민감 원문 저장 |
|---|---|---|---|---|---|---|
| `TOKENIZER_CORPUS_NOT_FOUND` | corpus | 예 | 입력 수정 후 | error | 승인 corpus를 찾을 수 없습니다. | 아니요 |
| `TOKENIZER_CORPUS_NOT_APPROVED` | corpus | 예 | 승인 후 | error | corpus 승인 조건을 충족하지 않습니다. | 아니요 |
| `TOKENIZER_CORPUS_CHECKSUM_MISMATCH` | corpus | 예 | 원인 해결 후 | error | corpus 무결성 검증에 실패했습니다. | 아니요 |
| `TOKENIZER_INVALID_CONFIG` | config | 예 | 설정 수정 후 | error | 토크나이저 설정이 유효하지 않습니다. | 아니요 |
| `TOKENIZER_TRAINING_FAILED` | training | 예 | 원인 해결 후 | error | 토크나이저 학습에 실패했습니다. | 아니요 |
| `TOKENIZER_VOCAB_SIZE_MISMATCH` | verification | 예 | 재학습 후 | error | 실제 vocabulary 크기가 계약과 다릅니다. | 아니요 |
| `TOKENIZER_SPECIAL_TOKEN_MISMATCH` | verification | 예 | 설정·재학습 후 | error | special token 매핑이 계약과 다릅니다. | 아니요 |
| `TOKENIZER_ARTIFACT_WRITE_ERROR` | publish | 예 | 저장공간·권한 해결 후 | error | 토크나이저 산출물을 게시할 수 없습니다. | 아니요 |
| `TOKENIZER_ARTIFACT_MISSING` | load | 예 | 올바른 bundle 확보 후 | error | 필수 토크나이저 산출물이 없습니다. | 아니요 |
| `TOKENIZER_ARTIFACT_CORRUPTED` | load | 예 | 정상 bundle 복구 후 | error | 토크나이저 산출물이 손상되었습니다. | 아니요 |
| `TOKENIZER_FINGERPRINT_MISMATCH` | compatibility | 예 | 올바른 version 선택 후 | error | 토크나이저 fingerprint가 일치하지 않습니다. | 아니요 |
| `TOKENIZER_ENCODE_ERROR` | encode | 요청 실패 | 입력·옵션 수정 후 | warning | 입력을 token으로 변환할 수 없습니다. | 아니요 |
| `TOKENIZER_DECODE_ERROR` | decode | 요청 실패 | 입력 수정 후 | warning | token을 문자열로 변환할 수 없습니다. | 아니요 |
| `TOKENIZER_INVALID_TOKEN_ID` | decode | 요청 실패 | ID 수정 후 | warning | 유효하지 않은 token ID입니다. | 아니요 |
| `TOKENIZER_ROUND_TRIP_FAILED` | evaluation | 후보 판정 실패 | 설정·후보 변경 후 | warning | round-trip 평가가 계약을 충족하지 않습니다. | 안전한 최소 사례만 |
| `TOKENIZER_INCOMPATIBLE` | compatibility | 예 | 호환 bundle 선택 후 | error | 모델과 호환되지 않는 토크나이저입니다. | 아니요 |

## 26. 설정 계약 후보

다음은 향후 schema 논의를 위한 후보이며 실제 YAML·schema를 변경하지 않는다. ADR-003의 special token을 사용한다.

```yaml
tokenizer:
  tokenizer_id: dohalm-ko-unigram       # [검증 필요] 후보
  tokenizer_version: 0.1.0              # [검증 필요] 예시
  model_type: unigram                    # [확정]
  vocab_size: 16000                      # [확정]
  corpus:
    input_artifacts: []                  # [검증 필요]
    use_split: train                     # [확정]
    sample_seed: 42                      # [검증 필요] 후보
    max_records: null                    # [검증 필요]
    max_bytes: null                      # [검증 필요]
  normalization:
    rule_name: identity                  # [확정]
  training:
    character_coverage: 0.9995           # [후보]
    byte_fallback: false                 # [후보] 기준선
    hard_vocab_limit: true               # [확정] 운영 후보
    num_threads: null                    # [검증 필요]
    input_sentence_size: null            # [검증 필요]
    shuffle_input_sentence: null         # [검증 필요]
    max_sentence_length: null            # [검증 필요]
  special_tokens:
    pad: {token: "<pad>", id: 0}
    unk: {token: "<unk>", id: 1}
    bos: {token: "<bos>", id: 2}
    eos: {token: "<eos>", id: 3}
    system: {token: "<|system|>", id: 4}
    user: {token: "<|user|>", id: 5}
    assistant: {token: "<|assistant|>", id: 6}
    end: {token: "<|end|>", id: 7}
  encoding:
    add_bos: false
    add_eos: false
    truncation: false
  output_dir: artifacts/tokenizers         # [검증 필요] 논리 경로 후보
```

## 27. Synthetic fixture 계약

- [확정] 직접 작성한 한국어 중심 10~200 records, 전체 5 MiB 미만만 허용한다.
- [확정] test-only이며 학습 데이터나 운영 tokenizer artifact 생성에 사용할 수 없다.
- [확정] 실제 개인정보·고객 데이터·credential·실제 비밀 URL은 금지한다.
- [확정] 일반·짧은·긴 한국어, 영문 혼합, 숫자, 날짜, 가상 URL, 코드 조각, 문장부호, 이모지, 한자, 연속 공백, 줄바꿈, NFC 조합 차이, 희귀 Unicode, special token 문자열, 빈 문자열과 공백 전용 입력을 포함한다.
- [확정] 이번 문서 작업에서는 fixture를 생성하지 않는다.

## 28. 필수 테스트 계약

| 영역 | 필수 검사 |
|---|---|
| Corpus | 승인 상태·manifest/checksum/fingerprint, train만 사용, validation/test·rejection·duplicate 차단 |
| Config | Unigram, 16,000, ID 0~7, identity, coverage 범위, fallback 후보, seed·명시 설정 |
| Artifact | model·vocab, piece 수, checksum, fingerprint, atomic publish, overwrite·손상 차단 |
| Encode/decode | 한국어·영문·숫자·이모지·줄바꿈·special·빈 입력·잘못된 ID·max length·truncation |
| Determinism | 동일 corpus/config, 입력 순서, 다른 CWD, Windows/POSIX 경로, piece·encode·fingerprint 비교 |
| Compatibility | 동일 fingerprint, special·vocab·normalization·fallback 변경 matrix |

- [확정] 모든 테스트는 정상 경로와 실패 경로의 오류 코드·안전 메시지·부분 산출물 부재를 함께 확인한다.
- [검증 필요] actual checksum bitwise 동일성과 품질 지표 합격선은 후보 실행 결과로 결정한다.

## 29. Candidate 비교 계획

| 항목 | Candidate A | Candidate B |
|---|---|---|
| 방식 | Unigram | Unigram |
| Vocabulary | 16,000 | 16,000 |
| Normalization | identity | identity |
| Character coverage | [후보] 0.9995 | [후보] 동일 승인값 |
| Byte fallback | false | true |

비교 지표는 실제 piece 수, UNK rate, round-trip 실패, 문자/token, token/어절, 256 token 초과 비율, 한국어 다문자 piece 비율, 희귀 문자·이모지 복원, artifact 크기와 학습 시간이다.

- [확정] AIHUB-71748 Training 승인 corpus 비교 결과에 따라 `operating-16k-v2/unigram-16k`를 운영 tokenizer로 선택한다. BPE는 비교 후보로만 유지한다.

## 30. Gate 3 완료 기준

Gate 3은 2026-07-26 사용자 최종 승인으로 `passed`다. 통과 근거는 다음과 같다.

- TOK-001~012 구현과 SentencePiece dependency 검토·승인
- synthetic fixture test와 승인 development corpus 검증
- corpus manifest·fingerprint, 2개 이상 후보 비교
- 운영 후보 vocabulary 16,000, ADR-003 special token 8개와 ID 0~7 일치
- encode/decode·round-trip, UNK·fallback, 한국어 분할 통계
- artifact checksum·tokenizer fingerprint·atomic publish·호환성 보고
- Windows 검증, 추적 금지 artifact 위반 0건, 사용자 승인

- [확정] 전체 대규모 pretraining corpus 확보는 Gate 3와 별도일 수 있으나 최종 운영 tokenizer는 실제 사전학습 분포를 대표하는 승인 corpus로 다시 검증해야 한다.
- [확정] [AIHUB-71748 16k 후보 평가](./aihub-71748-operating-tokenizer-evaluation.md)는 v1 무결성, v2 Unigram/BPE 실제 표본 UNK 0%, exact·ID round-trip 100%, 19개 synthetic probe 실패 0건을 확인했다.
- [확정] 별도 경로 재학습은 vocab checksum·표본 encode ID가 일치했고 출력별 trainer metadata만 binary fingerprint 차이를 만들었다. 사용자는 이를 functional reproduction으로 승인하고 v2 Unigram을 최종 운영 tokenizer로 선택했다.
- [확정] Gate 3 통과는 tokenizer 단계 완료만 의미하며 Gate 7, Pretraining, Tiny Overfit과 모델 학습은 계속 미승인이다.

## 31. DATA→TOK→MODEL 계보

```text
Phase 1 dataset fingerprint
→ tokenizer corpus manifest
→ tokenizer resolved config
→ tokenizer artifact checksum
→ tokenizer fingerprint
→ model config
→ checkpoint manifest
```

- [확정] `DohaLM-Tiny`는 vocabulary 16,000, context 256과 tied embedding/LM Head를 사용한다.
- [확정] tokenizer piece 수와 model vocab size, special ID와 model config, pad ID와 loss mask가 일치해야 한다.
- [확정] tokenizer fingerprint가 없는 checkpoint는 완전한 호환성 검증을 통과할 수 없다.

## 32. 위험과 대응

| 위험 | 상태 | 대응 |
|---|---|---|
| 실제 corpus 미확보·분포 편향 | `open` | 단계별 승인 corpus와 source 기여 통계 |
| 라이선스·PII 문제 | `mitigating` | Phase 1 승인·checksum·PII clear 차단 |
| NFKC 의미 변화·whitespace 손실 | `mitigating` | NFC+identity, round-trip·공백 fixture |
| special ID·16,000 불일치 | `open` | trainer 후 artifact 직접 검사 |
| SentencePiece 비결정성 | `open` | version/thread/seed 기록과 다층 결정론 비교 |
| fallback vocab 잠식·희귀 문자 UNK | `open` | A/B 후보와 UNK·piece 품질 통계 |
| 평가 누수 | `mitigating` | train split만 학습 입력으로 허용 |
| model vocab·checkpoint 비호환 | `open` | fingerprint·compatibility gate |
| artifact 손상·version 혼동 | `open` | checksum·atomic publish·overwrite 금지 |

## 33. 미결정 사항

### 33.1 구현 전에 결정

- [확정] Synthetic smoke의 SentencePiece dependency는 `0.2.2`로 `pyproject.toml`과 `requirements.txt`에 동일하게 고정한다.
- [확정] 운영 tokenizer ID·version은 `operating-16k-v2/unigram-16k`이며 실제 위치는 `configured_external_root` 아래 승인 manifest의 논리 경로로 해석한다.
- [확정] 운영 bundle의 `num_threads=1`, `shuffle_input_sentence=false`, `input_sentence_size=1000000`, `max_sentence_length=16384`, `seed_sentencepiece_size=1000000` 설정을 고정한다.
- [검증 필요] wrapper의 빈 decode와 `skip_special_tokens` 최종 기본값
- [검증 필요] user-defined symbol ID 할당·normalization·whitespace의 실제 라이브러리 동작
- [검증 필요] special token literal escape 방식의 Phase 2 포함 여부

### 33.2 승인 corpus 실험 후 결정

- [확정] tokenizer 개발 corpus는 AIHUB-71748 Training의 `data_info[].contents`로 고정하며 source별 후속 Pretraining 혼합 비율은 별도 승인 대상으로 남긴다.
- [확정] 운영 tokenizer는 `character_coverage=1.0`, `byte_fallback=true`, `normalization_rule_name=identity`를 사용한다.
- [확정] 실제 표본 UNK 0%, exact·ID round-trip 100%와 synthetic probe 실패 0건을 Gate 3 품질 근거로 승인한다.
- [확정] final tokenizer version은 `operating-16k-v2`이며 artifact 공개·재배포는 승인하지 않는다.

## 34. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 사용자 최종 승인으로 v2 Unigram, artifact identity·functional reproduction 기준과 Gate 3 `passed`를 계약에 반영함 |
| 2026-07-26 | [검증 필요] byte fallback·whitespace 보존 v2 후보가 실제 표본 UNK 0%와 exact·ID round-trip 100%를 충족한 evidence를 반영하고 Gate 3 사용자 승인 대기로 유지함 |
| 2026-07-26 | [검증 필요] AIHUB-71748 제한 corpus와 Unigram/BPE 16k 후보 비교 결과를 연결하고 round-trip·UNK 보완 전 Gate 3 `planned`를 유지함 |
| 2026-07-24 | [확정] SentencePiece 0.2.2와 synthetic TOK-001~012 smoke 구현을 반영하되 운영 tokenizer·승인·Gate 3은 미완료로 유지함 |
| 2026-07-23 | [확정] TOK-001~012의 corpus·SentencePiece·vocabulary·artifact·fingerprint·API·평가·호환성 계약을 작성하고 Gate 3 기준을 정의함 |
| 2026-07-23 | [확정] 후보 등록부·승인 로그를 corpus 승인 근거로 연결하고 현재 approved tokenizer corpus 0개를 명시함 |
