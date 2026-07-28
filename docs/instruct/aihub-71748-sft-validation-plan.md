# AIHUB-71748 SFT 원문 비출력 검증 계획

- 문서 상태: `review`
- 최종 검토일: 2026-07-28
- 실행 상태: `not_executed`
- Dataset 선택: `not_selected`
- 관련 문서: [이용조건 검토](./aihub-71748-sft-terms-review.md), [AI Hub 후보 검토](./aihub-dataset-candidate-review.md), [Instruction Schema](./instruction-schema.md)

## 1. 목적과 범위

이 문서는 AIHUB-71748의 `SFTdata`와 `SFTlabel`에 대한 향후 join, schema, PII, 중복, 누수와 품질
검증 계약을 정의한다. 이번 작업에서는 어떤 scan도 실행하지 않고 record·문자열·ZIP payload를 읽지 않는다.

```yaml
components:
  general_corpus:
    current_scope: excluded
    role: base_or_cpt
  sft_data:
    current_scope: validation_candidate
  sft_label:
    current_scope: validation_candidate
  rm_data:
    current_scope: excluded
    role: future_preference_or_reward_model
  ppo_data:
    current_scope: excluded
    role: future_alignment
```

Validation, evaluation, benchmark, RM, PPO와 일반 말뭉치는 SFT 검증 입력에서 제외한다.

## 2. 원문 비출력 정책

이전 AI Hub 5종 inventory 과정에서 AIHUB-653 TSV 첫 행 원문 일부가 터미널에 일시 출력된 경계 위반이
1회 있었다. 저장·문서화·원본 변경은 없었지만 같은 문제가 재발하지 않도록 실제 검증 승인의 필수 계약으로
다음을 적용한다.

### 금지 출력

- record 전체, 문자열 값, 질문·답변, 앞뒤 문맥과 일부 문자열
- exception message의 원문, debug `repr`, dataframe `head`
- JSON pretty print, shell 기본 내용 출력, 실패 payload dump
- 탐지된 PII, hash 입력, 정규화 전후 text

### 허용 출력

- 파일·record 수, byte 크기, field 이름, 자료형
- null·empty·whitespace 개수와 문자열 길이 통계
- SHA-256, ID hash, Unicode category 집계
- join 성공·실패, duplicate·collision·category 집계와 오류 코드

문자열 field는 메모리에서 최소한으로 처리하고 출력 대신 `length`, salted/contracted `sha256`, Unicode
category count, empty와 whitespace 여부만 계산한다. 로그 formatter와 exception boundary는 synthetic fixture로
원문 비노출을 먼저 검증한다.

## 3. 실행 전 불변 조건

1. 원본 package의 55 ZIP checksum inventory와 전체 digest가 기존 manifest와 일치한다.
2. external dataset root가 Git 밖이며 원본 read-only와 출력 경로 분리가 확인된다.
3. Training의 SFT source/label만 allowlist하고 Validation과 다른 component는 denylist한다.
4. 실행 도구와 resolved policy의 Git commit·fingerprint를 고정한다.
5. 출력 schema는 집계만 허용하고 record text field를 구조적으로 거부한다.
6. 각 scan의 별도 승인이 모두 존재하며 미소비·미만료 상태다.
7. 실패 시 partial report를 격리하고 원문을 포함하지 않는 failure manifest만 허용한다.

하나라도 실패하면 ZIP payload read 전 `status: blocked`로 종료한다.

## 4. Join integrity 계획

join key 1차 후보는 기존 제한 schema에서 관찰된 `data_id`다. 실제 key 이름과 자료형은 별도
`schema_inspection` 승인에서 재확인하고, 원본 ID는 출력하지 않으며 keyed hash로만 비교한다.

검사 항목:

- key 자료형, null, empty, duplicate
- one-to-one, one-to-many, many-to-one
- orphan data, orphan label, duplicate label
- split 간 key overlap, 파일·category 간 collision
- join 전후 record count, join loss와 결정론적 ordering
- 입력 archive 순서를 바꾼 반복 실행에서 집계·fingerprint 일치

```yaml
join_integrity:
  data_records: null
  label_records: null
  unique_data_keys: null
  unique_label_keys: null
  matched_keys: null
  orphan_data_keys: null
  orphan_label_keys: null
  duplicate_data_keys: null
  duplicate_label_keys: null
  one_to_one_ratio: null
  status: not_executed
```

join loss가 0이 아니거나 관계가 one-to-one으로 확인되지 않으면 mapping 승인을 중단한다. 허용 오차는
`threshold_not_approved`다.

## 5. Schema 검증 계획

확인 대상 field category:

- instruction, question, input, context
- answer, output, system
- category, domain, source
- record ID, conversation ID, turn ID, split
- quality label, safety label

```yaml
mapping_candidate:
  instruction: source_instruction_or_question
  input: optional_context
  output: target_answer
  system: null
  metadata:
    provider: AI_Hub
    dataset_id: 71748
    component: SFT
    source_record_id: original_identifier
    category: original_category
    split: original_split
```

현재 관찰 후보는 source `question`, label `answer.contents`, join `data_id`다. 이 mapping은 승인된 schema가
아니며 실제 변환 파일을 생성하지 않는다. metadata는 prompt/output에 serialize하지 않는다.

## 6. PII 검사 계획

대상 유형은 이름, 전화번호, 이메일, 주소, 주민등록번호, 계좌·카드·차량번호, URL, IP, 사용자·기관 내부
ID, 의료·금융·법률 정보, 세부 위치와 성별·나이·지역 결합이다.

검사 단계:

1. synthetic PII fixture로 detector와 로그 비노출 계약 검증.
2. allowlisted SFT 문자열 field만 streaming scan.
3. pattern·NER·민감 keyword를 유형별 집계하고 원문은 저장하지 않음.
4. false positive review는 별도 승인된 격리 환경과 비공개 담당자에게만 허용.
5. 의심 record는 keyed hash와 reason code로 quarantine 후보화하고 학습 입력에서 Fail Closed.

```yaml
pii_scan:
  files_scanned: null
  records_scanned: null
  suspected_name_count: null
  suspected_phone_count: null
  suspected_email_count: null
  suspected_address_count: null
  suspected_id_number_count: null
  suspected_financial_count: null
  suspected_medical_count: null
  suspected_other_count: null
  status: not_executed
```

PII clear threshold와 검토 표본 수는 `threshold_not_approved`다. 탐지 원문이나 일부 문자열도 출력하지 않는다.

## 7. 중복 검사 계획

### Exact duplicate

- 동일 key
- 동일 question hash
- 동일 answer hash
- 동일 question-answer pair hash

### Normalized duplicate

Unicode NFC, 앞뒤 공백 제거, 연속 공백 축약과 줄바꿈 정규화를 후보로 한다. 정규화 결과는 저장하거나
출력하지 않고 versioned algorithm fingerprint와 hash만 기록한다.

### Near duplicate

MinHash, SimHash, character n-gram과 token n-gram을 후보로 비교한다. Tokenizer 의존 방식을 사용할 경우
운영 tokenizer identity를 manifest에 고정한다. similarity threshold는 `threshold_not_approved`다.

출력은 duplicate group·영향 record·split/category 간 중복·동일 질문/다른 답변·다른 질문/동일 답변 수와
algorithm fingerprint로 제한한다.

## 8. Leakage와 contamination 계획

검사 대상:

- train/validation/test overlap
- 같은 문서에서 파생된 질문의 split 분산과 paraphrase
- answer leakage, prompt 또는 metadata에 정답 포함
- 공개 benchmark 문항·정답·해설 유사성
- Candidate A/B evaluation prompt와 DohaLM Evaluation Framework 입력의 중복

검사 순서는 내부 exact hash, normalized hash, group/source ID, 승인된 benchmark registry exact/near 비교다.
Validation과 evaluation 원문 접근은 SFT scan 승인과 별개의 승인으로 분리한다.

```yaml
benchmark_contamination:
  benchmark_registry: incomplete
  execution_status: blocked
```

benchmark registry가 완성·승인되기 전 contamination scan 완료나 dataset 적격 판정을 선언하지 않는다.

## 9. 품질 검사 계획

- empty instruction/answer, null field와 malformed JSON
- 깨진 Unicode, replacement character와 control character
- 지나치게 짧거나 긴 답변, 질문과 무관한 답변
- 동일 답변 반복, boilerplate, URL-only, HTML
- 코드·JSON fence 불균형
- unsafe answer, refusal mismatch, hallucination-like answer와 label inconsistency

구조·길이·형식 검사는 자동 집계할 수 있지만 relevance, safety와 hallucination 판정은 승인된 rubric과 제한된
human review가 필요하다. 모든 수치 기준은 `threshold_not_approved`다.

## 10. Report와 저장 계약

- 원본은 외부 root에서 read-only로 사용하고 수정·이동·삭제하지 않는다.
- 결과 report는 Git 외부 제한 경로에 atomic publish한 뒤 집계 manifest의 Git 등록 가능성을 별도 검토한다.
- report schema는 aggregate count, fingerprint, status와 오류 코드만 허용한다.
- raw ID, text, matched fragment, normalized text, PII context와 sample file은 생성하지 않는다.
- 재실행은 같은 input/policy/tool fingerprint에서 동일 aggregate fingerprint를 생성해야 한다.
- partial·failure artifact의 보존·삭제는 실행 승인에서 명시하고 자동 재시도하지 않는다.

## 11. Required approvals

```yaml
required_approvals:
  - dataset_component_access
  - zip_stream_read
  - schema_inspection
  - join_integrity_scan
  - pii_scan
  - duplicate_scan
  - leakage_scan
  - benchmark_registry_access
  - report_write
```

각 항목은 목적·field·component·split·record 상한·출력 경로·만료·소비 방식을 명시해야 한다. 하나의 승인이
다른 scan을 자동 승인하지 않으며, 승인 누락 시 payload read 전에 종료한다.

## 12. 실행 순서

```text
terms evidence
  -> immutable package verification
  -> synthetic no-output test
  -> schema inspection
  -> join integrity
  -> PII scan
  -> duplicate scan
  -> approved benchmark leakage scan
  -> quality aggregation
  -> human review decision
  -> separate dataset selection approval
```

이 순서는 계획이며 실행 승인이 아니다. 앞 단계 실패 시 이후 단계는 시작하지 않는다.

## 13. 성공·실패 판정

계획 단계 완료 조건은 검사 항목, 원문 비출력 계약, 승인 경계와 report schema가 문서화되는 것이다. 실제
dataset 적격 조건은 아직 승인되지 않았다.

- Join·PII·duplicate·leakage·quality threshold: `threshold_not_approved`
- Benchmark registry: `incomplete`
- Dataset selection: `not_selected`
- Scan result: `not_executed`

## 14. Readiness

```yaml
AIHUB_71748_SFT:
  terms_review: verification_required
  schema_plan: completed
  join_validation: not_executed
  pii_validation: not_executed
  duplicate_validation: not_executed
  leakage_validation: not_executed
  quality_validation: not_executed
  approval_status: not_approved
overall:
  dataset: not_selected
  dataset_processing: not_approved
  sft_backend: not_started
  sft_training: not_approved
  execution_allowed: false
```

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | AIHUB-71748 SFT component의 원문 비출력 join·schema·PII·중복·누수·품질 검증 및 별도 승인 계약 작성 |
