# DohaLM Phase 1 데이터 계약

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [핵심 개발 기능명세서](../architecture/core-development-feature-specification.md), [데이터 전략](./data-strategy.md), [데이터 전처리 정책](./preprocessing.md), [데이터셋 레지스트리](./dataset-registry.md), [데이터 라이선스 정책](./data-license-policy.md), [데이터 분할 및 누수 방지 정책](./data-split-and-leakage-policy.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | Phase 1 데이터 최소 파이프라인 구현과 테스트, [Gate 2 검증](../quality/development-roadmap.md) |
| 구현 전 필수 여부 | Phase 1 구현 전 예 |

- [확정] 이 문서는 Phase 1의 입력, 레코드, checksum, manifest, 정규화, exact 중복 제거, split, 승인·라이선스·개인정보, 산출물과 실패 처리에 관한 단일 구현 계약이다.
- [확정] 전략·승인 원칙은 기존 데이터 문서와 ADR-004가, 기능 ID·구현 상태는 핵심 개발 기능명세서가 담당한다.
- [확정] 문서 생명주기 상태 `review`와 기능 상태는 별개다. DATA-001~016은 모두 `review`이며 구현·검증되지 않았다.
- [확정] 이 문서는 외부 학습 데이터를 선정하거나 승인하지 않는다. 현재 승인된 실제 학습 데이터는 없다.

## 2. 목적과 Phase 1 범위

### 2.1 포함 기능

| 기능 ID | 기능 | 이 문서의 계약 |
|---|---|---|
| DATA-001 | 입력 파일 탐색 | 승인된 저장소 상대경로에서 허용 확장자를 결정론적으로 열거 |
| DATA-002 | 지원 입력 형식 판별 | `.txt`, `.jsonl` 확장자와 실제 parse 가능 여부 확인 |
| DATA-003 | 원본 불변 검사 | 처리 전후 원본 byte checksum 비교 |
| DATA-004 | checksum 생성 | SHA-256 file/raw record/normalized record checksum |
| DATA-005 | source manifest 생성 | JSON `source-manifest.json` 생성·검증 |
| DATA-006 | record schema validation | JSONL 입력과 내부 canonical record 계약 검증 |
| DATA-007 | 텍스트 정규화 | UTF-8, LF, NFC 기반의 고정 순서 적용 |
| DATA-008 | 빈 문서 제거 | 사유가 있는 개별 거부 기록 |
| DATA-009 | 중복 탐지 | file/raw record/normalized text exact 중복만 처리 |
| DATA-010 | 문서 그룹 ID 생성 | 입력값 보존 또는 source 기반 결정론적 생성 |
| DATA-011 | deterministic split | SHA-256 기반 group 단위 배정 |
| DATA-012 | split leakage 검사 | group/checksum/record/source record 교차 검사 |
| DATA-013 | 정제 통계 생성 | tokenizer 비의존 통계 생성 |
| DATA-014 | 처리 계보 기록 | 입력·설정·단계·산출물·fingerprint 연결 |
| DATA-015 | 승인되지 않은 데이터 차단 | source·license·approval 상태 사전 검사 |
| DATA-016 | 개인정보·민감정보 격리 | `clear` 이외 상태 차단·격리 |

### 2.2 제외 범위

- [제외] 외부 데이터 자동 다운로드, 웹 크롤링, Hugging Face `datasets` 연동
- [제외] 대용량 병렬·분산·GPU 전처리, multiprocessing과 대용량 streaming 처리
- [제외] 고급 개인정보 자동 탐지, 언어 모델 기반 정제
- [제외] tokenizer 학습, token 단위 통계, 학습용 binary packing
- [제외] 근사 중복, MinHash, SimHash, embedding 유사도, 문장·문단 단위 부분 중복
- [제외] 데이터베이스, API, UI와 cloud storage 연동

## 3. 입력 탐색과 지원 형식

### 3.1 공통 입력 규칙

- [확정] 지원 확장자는 소문자 기준 `.txt`, `.jsonl` 두 가지뿐이다.
- [확정] `.csv`, `.json`, `.parquet`, `.xml`, `.html`, `.pdf`, `.docx`와 그 밖의 확장자는 `UNSUPPORTED_FORMAT`으로 전체 실행을 실패시킨다.
- [확정] 형식을 내용만으로 자동 추정하거나 다른 parser로 fallback하지 않는다. 확장자 검사와 해당 형식의 parse 성공을 모두 요구한다.
- [확정] 입력 경로는 저장소 상대 POSIX 경로로 정규화하고 절대경로, `..`를 통한 root 이탈과 symlink 등으로 해석된 root 이탈을 차단한다.
- [확정] 파일 탐색 결과는 정규화된 상대경로의 Unicode code point 사전순으로 고정한다. CWD와 OS 구분자에 따라 순서가 달라져서는 안 된다.

### 3.2 UTF-8 `.txt` 계약

- [확정] UTF-8만 허용한다. UTF-8 BOM은 허용하지만 file checksum 계산 후 decode 단계에서 제거한다.
- [확정] UTF-16, CP949, EUC-KR과 잘못된 UTF-8은 `INVALID_ENCODING`으로 전체 실행을 실패시킨다.
- [제외] 자동 인코딩 탐지는 수행하지 않는다.
- [확정] 파일 하나를 레코드 하나로 처리하며 줄마다 레코드를 만들지 않는다.
- [확정] 본문 내부 줄바꿈은 보존하고 줄바꿈 문자만 정규화 규칙에 따라 LF로 통일한다.
- [확정] `source_name`은 승인된 source 등록 정보에서 얻고 `source_path`는 저장소 상대 POSIX 경로를 사용한다.
- [확정] `source_record_id`는 `source_path`와 file checksum의 canonical serialization에 대한 SHA-256으로 생성한다.

### 3.3 JSONL 입력 schema

```json
{
  "id": "sample-001",
  "text": "한국어 테스트 문장입니다.",
  "source": "fixture",
  "group_id": "group-001",
  "metadata": {}
}
```

| 구분 | 필드 |
|---|---|
| 필수 | `id`, `text`, `source` |
| 선택 | `group_id`, `metadata` |
| 허용하지 않는 최상위 필드 | 위 다섯 필드 이외의 모든 필드 |

- [확정] UTF-8 JSON object 하나를 한 줄에 기록한다. 빈 줄과 JSON object가 아닌 값은 `INVALID_JSONL`로 처리한다.
- [확정] 알 수 없는 최상위 필드는 `UNKNOWN_FIELD`로 개별 레코드를 거부한다. 확장 정보는 `metadata` 객체 안에 둔다.
- [확정] JSONL의 `source`는 승인된 source 식별자와 일치해야 한다. 승인된 source 범위 밖의 값은 `UNAPPROVED_SOURCE`로 전체 실행을 실패시킨다.

## 4. 입력 필드 validation

| 필드 | 계약 | 위반 처리 |
|---|---|---|
| `id` | 문자열, trim 후 비어 있지 않음, 최대 256자, Unicode 제어문자 금지, 대소문자 구분 | 타입·형식 위반은 개별 거부; 파일·dataset 전체 중복은 `DUPLICATE_RECORD_ID` 전체 실패 |
| `text` | 정규화 전 문자열 필수, NUL 금지, 정규화 후 비어 있지 않음 | 개별 거부. 최대 문자 수 초과는 `TEXT_TOO_LONG` |
| `source` | 문자열, trim 후 비어 있지 않음, 최대 256자, 출처 식별 가능 | 형식 위반은 개별 거부, 미승인은 전체 실패 |
| `group_id` | 문자열 또는 `null`, trim 후 빈 값은 미지정, 최대 256자, 제어문자 금지 | 형식 위반은 개별 거부 |
| `metadata` | JSON object, 생략 시 `{}`, JSON 직렬화 가능, 비밀정보 금지 | 객체가 아니거나 허용 깊이 위반 시 개별 거부 |

- [확정] JSON의 `null`은 `text` 또는 필수 문자열 필드의 유효한 값이 아니다.
- [확정] `id`, `source`, 제공된 `group_id`에는 C0/C1 control과 Unicode `Cc` 범주 문자를 허용하지 않는다.
- [검증 필요] `data.max_text_chars`의 기본값과 `metadata` 최대 중첩 깊이는 구현 전에 확정한다.
- [확정] `metadata`에는 password, API key, access token, credential과 그 밖의 비밀정보를 저장하지 않는다.

## 5. 내부 canonical record

모든 승인 입력은 다음 필드를 갖는 하나의 내부 record로 변환한다.

```json
{
  "record_id": "sha256:...",
  "source_record_id": "sample-001",
  "source_name": "fixture",
  "source_path": "data/raw/fixture/sample.jsonl",
  "group_id": "group-001",
  "text_raw": "한국어 테스트 문장입니다.",
  "text_normalized": "한국어 테스트 문장입니다.",
  "file_checksum": "sha256:...",
  "raw_record_checksum": "sha256:...",
  "normalized_record_checksum": "sha256:...",
  "metadata": {},
  "license_status": "approved",
  "approval_status": "approved",
  "pii_status": "clear",
  "processing_status": "accepted",
  "rejection_reasons": []
}
```

- [확정] `text_raw`는 decode와 BOM 제거 후 얻은 정규화 전 문자열이다. 줄바꿈·Unicode·공백 정규화 전 값을 보존한다.
- [확정] `text_normalized`는 8단계 정규화 완료 문자열이다.
- [확정] `processing_status`는 최소 `accepted`, `rejected`, `duplicate`를 구분한다.
- [확정] 승인되어 dedup 대표로 남은 record만 `records.jsonl`과 split 파일에 기록한다. 거부·중복 record는 전용 artifact에 기록한다.

## 6. 결정론적 ID

### 6.1 JSONL

- [확정] 입력 `id`를 trim 후 `source_record_id`로 보존한다.
- [확정] 내부 `record_id`는 `source_name`, `source_path`, `source_record_id`, `raw_record_checksum` 객체의 canonical serialization을 SHA-256으로 계산한다.

### 6.2 TXT

- [확정] `source_record_id`는 `source_path`, `file_checksum` 객체의 canonical serialization을 SHA-256으로 계산한다.
- [확정] `record_id`는 JSONL과 동일한 구성 필드와 방식으로 계산한다.

### 6.3 공통

- [확정] 생성 ID는 `sha256:<64자리 소문자 hexadecimal>` 형식이다.
- [확정] 경로는 저장소 상대 POSIX 형식으로 정규화하며 절대경로를 ID 입력에 사용하지 않는다.
- [확정] 동일 입력은 Windows·Linux와 CWD에 관계없이 동일 ID를 생성해야 한다.
- [제외] UUID v4와 Python 내장 `hash()`처럼 실행마다 달라질 수 있는 값을 사용하지 않는다.

## 7. Checksum과 canonical serialization

### 7.1 Checksum 종류

| 종류 | 입력 | 목적 |
|---|---|---|
| file checksum | 원본 파일 byte 전체 | 원본 무결성·파일 exact 중복 |
| raw record checksum | `source_record_id`, `source_name`, `group_id`, `text_raw`, `metadata`의 canonical object | 원본 record exact 중복 |
| normalized record checksum | 최소 `text_normalized`만 포함한 canonical object | source·ID와 무관한 정규화 text exact 중복 |

- [확정] 알고리즘은 SHA-256이고 표기는 `sha256:<64자리 소문자 hexadecimal>`이다.
- [확정] file checksum은 BOM 제거, decode, 줄바꿈 변환과 모든 정규화 전에 원본 bytes 그대로 계산한다.
- [확정] normalized checksum은 source와 ID를 포함하지 않는다. 정규화 text가 같으면 출처가 달라도 exact duplicate다.

### 7.2 Canonical serialization

- [확정] JSON 의미 기준 UTF-8과 `ensure_ascii=false`에 해당하는 문자 보존 방식을 사용한다.
- [확정] object key는 Unicode code point 기준으로 정렬하고 separator는 쉼표와 콜론 뒤 공백이 없는 고정 형식을 사용한다.
- [확정] NaN과 양·음의 Infinity는 금지한다.
- [확정] 줄바꿈은 LF이며 serialized byte stream 끝에는 newline 하나만 둔다.
- [확정] checksum 대상의 field 집합과 값 변환은 schema version으로 고정한다. 구현체의 비결정적 object 표현을 사용하지 않는다.

## 8. 원본 불변성

- [확정] `data/raw/`의 파일은 읽기 전용으로 취급하며 내용 덮어쓰기, 이름 변경, 자동 삭제, 인코딩 변환과 줄바꿈 변환을 금지한다.
- [확정] pipeline은 처리 시작 전에 모든 입력 file checksum을 기록하고 산출물 publish 직전에 다시 계산한다.
- [확정] 처리 전후 checksum 또는 파일 집합이 달라지면 `RAW_FILE_MUTATED`로 전체 실행을 실패시킨다.
- [확정] 원본 mutation이 발견된 실행의 산출물은 정상 dataset version으로 publish하지 않는다.

## 9. Source manifest

### 9.1 위치와 최상위 schema

- [확정] manifest는 JSON이며 파일명은 `source-manifest.json`이다.
- [확정] 경로는 `data/cleaned/<dataset_id>/<dataset_version>/source-manifest.json`이다.

| 필수 최상위 필드 | 의미 |
|---|---|
| `schema_version` | manifest·canonical schema version |
| `dataset_id`, `dataset_version` | dataset 식별자와 불변 version |
| `pipeline_version` | 처리 규칙·구현 version |
| `created_at` | timezone이 명시된 UTC ISO 8601 운영 시각 |
| `git_sha` | 실행 코드의 전체 Git SHA |
| `source_count`, `record_count` | source 수와 입력 record 수 |
| `accepted_count`, `rejected_count`, `duplicate_count` | dedup 후 승인, 개별 거부, 중복 제외 record 수 |
| `split_counts` | `train`, `validation`, `test`별 record 수 |
| `license_status`, `approval_status` | dataset 수준 상태 |
| `split_seed`, `normalization_version` | 분할·정규화 식별 정보 |
| `checksum_algorithm` | `sha256` |
| `sources`, `artifacts` | source·산출물 목록 |

- [확정] `record_count = accepted_count + rejected_count + duplicate_count`가 성립해야 한다. 여러 중복 유형에 해당해도 제거된 record 한 개는 `duplicate_count`에서 한 번만 센다.
- [확정] `created_at`은 실행마다 달라질 수 있으므로 dataset fingerprint 입력에서 제외한다.

### 9.2 `sources` 항목

각 항목은 `source_name`, `source_path`, `format`, `size_bytes`, `file_checksum`, `record_count`, `accepted_count`, `rejected_count`, `license_status`, `approval_status`, `pii_status`를 모두 포함한다.

### 9.3 `artifacts` 항목

각 항목은 `artifact_type`, `relative_path`, `checksum`, `record_count`를 모두 포함한다.

- [확정] self-referential checksum을 피하기 위해 `source-manifest.json` 자체는 `artifacts` 배열에서 제외하고 나머지 필수 산출물을 등록한다.

### 9.4 경로 규칙

- [확정] 모든 manifest 경로는 저장소 상대 POSIX 경로다.
- [확정] 절대경로와 Windows 역슬래시를 저장하지 않는다.
- [확정] `created_at`은 UTC ISO 8601과 timezone을 명시한다. 예시 형식은 `2026-07-23T00:00:00Z`다.

## 10. Dataset fingerprint

- [확정] dataset fingerprint는 다음 값을 canonical serialization한 뒤 SHA-256으로 계산한다.
  - `schema_version`, `dataset_id`, `dataset_version`, `pipeline_version`, `normalization_version`, `split_seed`
  - 상대경로로 정렬한 입력 file checksum 목록
  - `record_id`로 정렬한 승인 canonical record의 normalized checksum 목록
  - `record_id`와 split 이름으로 정렬한 split mapping
- [확정] fingerprint 형식은 `sha256:<64자리 소문자 hexadecimal>`이다.
- [확정] `created_at`, 절대경로, machine·사용자명, 임시 디렉터리와 log 위치는 fingerprint 입력에서 제외한다.

## 11. 텍스트 정규화

정규화 순서는 다음과 같이 고정한다.

1. [확정] 원본 bytes를 엄격한 UTF-8로 decode한다.
2. [확정] 문자열 시작의 UTF-8 BOM을 제거한다.
3. [확정] NUL 문자를 검사하고 발견 시 거부한다.
4. [확정] CRLF와 CR을 LF로 통일한다.
5. [확정] Unicode NFC를 적용한다.
6. [확정] 각 줄 끝의 horizontal whitespace를 제거한다. 본문 내부 공백은 변경하지 않는다.
7. [확정] 파일 끝의 연속 LF는 최대 하나로 축약한다. 원문에 끝 LF가 없으면 새로 추가하지 않는다.
8. [확정] 정규화 후 빈 text인지 검사한다.

- [확정] 한글, 영문 대소문자, 문장부호, 숫자, emoji, 본문 내부 줄바꿈과 본문 내부 연속 공백을 보존한다.
- [제외] NFKC, 소문자화, 문장부호·숫자·emoji 제거, HTML 자동 제거, 맞춤법 교정, 형태소 분석, 문장 재작성과 전체 whitespace 축약을 적용하지 않는다.
- [확정] 정규화 규칙 변경은 `normalization_version` 변경과 새 dataset version을 요구한다.

## 12. 빈 문서와 schema 거부

- [확정] `text`가 `null`, 비문자열, 정규화 후 길이 0, 공백·줄바꿈만 포함, NUL 포함 또는 decode 실패인 record는 승인 record가 될 수 없다.
- [확정] JSONL의 빈 text, 필수 필드 누락, 필드 타입·형식 오류와 미지원 최상위 필드는 개별 record 거부 후 계속할 수 있다.
- [확정] `.txt`의 decode 실패는 파일 수준 오류이므로 전체 실행을 실패시킨다.
- [확정] 모든 개별 거부는 `rejections.jsonl`에 기록하며 조용히 삭제하지 않는다.
- [확정] 최종 `accepted_count`가 0이면 전체 실행을 실패시킨다.

## 13. Exact 중복 처리

### 13.1 중복 유형

| 유형 | 판정 |
|---|---|
| `FILE_DUPLICATE` | file checksum 동일 |
| `RAW_RECORD_DUPLICATE` | raw record checksum 동일 |
| `NORMALIZED_TEXT_DUPLICATE` | normalized record checksum 동일 |

- [확정] Phase 1은 위 exact 중복만 처리한다.
- [확정] 중복 우선순위는 file → raw record → normalized text다. 먼저 판정된 유형을 대표 제거 사유로 사용하되 추가 일치 정보는 보고할 수 있다.
- [확정] 대표 record는 `source_path`, `source_record_id`, `record_id`의 순서로 사전 정렬한 첫 record다.
- [확정] 중복 record는 `duplicates.jsonl`에 남기고 승인 record·split에서는 제외한다.
- [제외] near·semantic 중복은 Phase 1 완료 조건이 아니며 경고로 암묵 처리하지도 않는다.

## 14. `group_id`

- [확정] 입력 `group_id`가 있으면 trim 후 사용한다. 빈 문자열은 미지정으로 취급하고 제어문자와 256자 초과를 거부한다.
- [확정] 미지정 `group_id`는 `source_name`, `source_path` 객체의 canonical serialization을 SHA-256으로 계산한다.
- [확정] 같은 입력 파일에서 파생된 모든 record는 기본적으로 같은 자동 group을 사용한다.
- [확정] JSONL record가 완전히 독립적이라는 별도 승인 계약이 없으므로 Phase 1에서는 record ID를 자동 group ID로 사용하지 않는다.
- [확정] 생성 group ID 형식은 `sha256:<64자리 소문자 hexadecimal>`이다.

## 15. Deterministic split

### 15.1 이름과 비율 검증

- [확정] split 이름은 `train`, `validation`, `test`만 사용한다.
- [확정] `group_id` 단위로 배정하며 같은 group과 같은 normalized checksum은 하나의 split에만 존재해야 한다.
- [확정] 비율은 설정에서 받으며 각 값은 0 이상 1 이하, 합은 명시된 수치 허용 오차 안에서 1, `train_ratio > 0`이어야 한다.
- [검증 필요] split 합 비교의 허용 오차와 `validation_ratio` 또는 `test_ratio`가 0인 설정을 허용할지는 구현 전에 확정한다.
- [확정] split 기본 비율을 이 문서에서 정하지 않는다.

### 15.2 배정 방식

- [확정] seed를 고정된 문자열 표현으로 정규화한 뒤 UTF-8 `seed + "\n" + group_id`의 SHA-256을 계산한다.
- [확정] digest의 앞 8 bytes를 unsigned big-endian 정수로 해석하고 `2^64`로 나눈 `[0, 1)` 값을 누적 비율 경계와 비교한다.
- [확정] group 목록·record 입력 순서, OS와 CWD는 배정에 영향을 주지 않는다.
- [제외] Python 내장 `hash()`와 무작위 순회 순서를 사용하지 않는다.
- [검증 필요] seed 설정값의 최종 type과 canonical 문자열 규칙은 실제 config schema와 함께 확정한다.

## 16. Split leakage 검사

다음 중 하나라도 여러 split에서 발견되면 `SPLIT_LEAKAGE`로 전체 실행을 실패시킨다.

- [확정] 동일 `group_id`
- [확정] 동일 `normalized_record_checksum`
- [확정] 동일 `record_id`
- [확정] 동일 `(source_path, source_record_id)` source record

- [확정] 누수 검사는 split artifact publish 전에 수행하고 경고만 남긴 채 진행하지 않는다.
- [제외] near·semantic leakage 자동 검사는 Phase 1 범위가 아니다. 상위 정책의 향후 요구를 폐기하지 않으며 후속 단계에서 별도로 구현한다.

## 17. Phase 1 산출물

기준 경로는 `data/cleaned/<dataset_id>/<dataset_version>/`이며 다음 파일이 모두 필요하다.

| 파일 | 계약 |
|---|---|
| `records.jsonl` | 승인되고 dedup된 전체 canonical record |
| `train.jsonl` | train canonical record |
| `validation.jsonl` | validation canonical record |
| `test.jsonl` | test canonical record |
| `source-manifest.json` | source·count·artifact manifest |
| `rejections.jsonl` | 개별 거부 기록 |
| `duplicates.jsonl` | exact 중복 mapping |
| `statistics.json` | tokenizer 비의존 정제 통계 |
| `lineage.json` | 입력→단계→출력 계보와 fingerprint |
| `resolved-data-config.yaml` | 실제 적용된 데이터 설정 snapshot |

- [확정] JSONL은 한 줄에 JSON object 하나, UTF-8, LF, 끝 newline 하나, NaN·Infinity 금지 규칙을 따른다.
- [확정] `records.jsonl`과 split 파일은 `record_id` 사전순으로 기록하고 동일 canonical schema를 사용한다.
- [확정] 0건 split을 허용하는 설정이 승인된 경우에도 빈 UTF-8 JSONL 파일을 만들고 `split_counts`와 일치시킨다.
- [확정] 대용량·실제 데이터 산출물은 `.gitignore` 정책에 따라 Git에 추적하지 않는다.

## 18. 보조 artifact schema

### 18.1 `rejections.jsonl`

| 필드 | 계약 |
|---|---|
| `source_path` | 저장소 상대 POSIX 경로 |
| `source_record_id` | 알 수 없으면 `null` |
| `record_id` | 생성 전 실패이면 `null` |
| `stage` | 실패한 processing step 이름 |
| `reason_code`, `reason_message` | 안정 문자열 코드와 민감정보 없는 설명 |
| `raw_record_checksum` | 계산 전 실패이면 `null` |
| `created_at` | UTC ISO 8601 운영 시각 |

- [확정] 원문 전체는 저장하지 않는다. 제한 preview가 필요하면 길이·마스킹·접근 정책을 설정으로 승인한 뒤 사용한다.

### 18.2 `duplicates.jsonl`

필수 필드는 `duplicate_type`, `duplicate_record_id`, `canonical_record_id`, `checksum`, `source_path`, `source_record_id`다. `duplicate_type`은 `FILE_DUPLICATE`, `RAW_RECORD_DUPLICATE`, `NORMALIZED_TEXT_DUPLICATE` 중 하나다.

### 18.3 `statistics.json`

필수 필드는 `schema_version`, `dataset_id`, `dataset_version`, `source_count`, `input_record_count`, `accepted_record_count`, `rejected_record_count`, `duplicate_record_count`, `split_counts`, `character_count`, `byte_count`, `empty_rejection_count`, `schema_rejection_count`, `pii_rejection_count`, `license_rejection_count`, `approval_rejection_count`다.

- [확정] token 수와 tokenizer 의존 통계는 포함하지 않는다.
- [확정] count 정의는 manifest와 일치해야 하며 결정론적 필드는 재실행 시 같아야 한다.

### 18.4 `lineage.json`

필수 필드는 `schema_version`, `dataset_id`, `dataset_version`, `pipeline_version`, `git_sha`, `resolved_config_checksum`, `input_artifacts`, `output_artifacts`, `processing_steps`, `dataset_fingerprint`다.

각 `processing_steps` 항목은 `step_name`, `step_version`, `input_count`, `output_count`, `rejected_count`를 포함한다.

## 19. 라이선스·승인·개인정보 상태

### 19.1 라이선스

| 상태 | 처리 |
|---|---|
| `approved` | 해당 목적의 Phase 1 처리 허용 |
| `pending`, `rejected`, `unknown` | `UNAPPROVED_LICENSE`로 전체 실행 차단 |

### 19.2 사용 승인

| 상태 | 처리 |
|---|---|
| `approved` | 해당 dataset version·목적의 처리 허용 |
| `pending`, `rejected` | `UNAPPROVED_SOURCE`로 전체 실행 차단 |

- [확정] 승인은 source 단위를 기본으로 한다. record 단위 승인은 향후 호환 가능한 확장 후보이며 Phase 1 MVP에 포함하지 않는다.
- [확정] fixture는 프로젝트가 직접 작성한 test-only 자료로 등록하고 학습·tokenizer corpus 승인이 아님을 명시한다.

### 19.3 개인정보·민감정보

| 상태 | 처리 |
|---|---|
| `clear` | 처리 허용 |
| `suspected`, `confirmed`, `unknown` | `PII_NOT_CLEAR`로 격리하고 전체 실행 차단 |

- [확정] 단순 정규식 탐지는 보조 신호일 뿐 `clear` 승인 근거가 아니다.
- [검증 필요] 개인정보 자동 탐지 방식, 사람 검토 범위와 제한 저장 위치는 후속 결정 사항이다.

## 20. 테스트 fixture 계약

- [확정] UTF-8 `.txt`와 UTF-8 `.jsonl`만 허용한다. invalid UTF-8 거부용 fixture는 의도된 raw byte 예외다.
- [확정] 전체 10~100 record, 개별 파일 1 MiB 미만, 전체 fixture 5 MiB 미만으로 제한한다.
- [확정] 프로젝트가 직접 작성한 한국어 중심 문장만 사용하며 일부 영어·숫자·emoji를 포함할 수 있다.
- [확정] 실명, 전화번호, email, 주소, 주민등록번호, 계좌번호, password, API key, access token, 실제 대화 기록과 실제 고객 데이터를 금지한다.
- [확정] 외부 데이터 복사와 학습·tokenizer corpus 사용을 금지한다.

필수 검증 사례는 정상 TXT, 정상 JSONL, UTF-8 BOM, 빈 text, whitespace-only text, invalid UTF-8, 필수 field 누락, unknown field, 중복 ID, 중복 raw record, 정규화 후 중복, 동일·서로 다른 group, 미승인 source, license `unknown`, PII `suspected`, NUL, Windows CRLF, NFC 차이와 입력 순서 변경이다.

- [확정] 이 문서 작업에서는 fixture를 생성하지 않는다.

## 21. 향후 설정 계약

다음 key는 구현용 설정 후보이며 이번 작업에서 YAML 또는 Phase 0 schema를 변경하지 않는다.

```text
data.dataset_id
data.dataset_version
data.input_paths
data.allowed_formats
data.output_dir
data.encoding
data.unicode_normalization
data.max_text_chars
data.split.seed
data.split.train_ratio
data.split.validation_ratio
data.split.test_ratio
data.license_status
data.approval_status
data.pii_policy
data.reject_unknown_fields
data.write_empty_split_files
```

- [확정] 계약값은 `allowed_formats=[.txt,.jsonl]`, `encoding=UTF-8`, `unicode_normalization=NFC`, unknown top-level field 거부, 빈 split file 기록이다.
- [검증 필요] 실제 config schema 위치·계층, 최대 text 기본값, split seed type·비율·허용 오차와 metadata 깊이는 구현 전에 확정한다.
- [확정] 최종 적용 설정은 `resolved-data-config.yaml`로 저장하고 checksum을 lineage에 연결한다.

## 22. 문자열 오류 코드

| 오류 코드 | 의미 | 기본 범위 |
|---|---|---|
| `UNSUPPORTED_FORMAT` | 지원하지 않는 확장자·형식 | 전체 실패 |
| `FILE_NOT_FOUND` | 입력 파일 없음 | 전체 실패 |
| `FILE_READ_ERROR` | 파일 읽기 실패 | 전체 실패 |
| `INVALID_ENCODING` | UTF-8 decode 실패·금지 encoding | 전체 실패 |
| `RAW_FILE_MUTATED` | 처리 전후 원본 변경 | 전체 실패 |
| `INVALID_JSONL` | JSON parse 또는 JSONL 구조 오류 | 전체 실패 |
| `UNKNOWN_FIELD` | 허용하지 않는 최상위 field | record 거부 |
| `MISSING_REQUIRED_FIELD` | 필수 field 누락 | record 거부 |
| `INVALID_FIELD_TYPE` | field type·형식 위반 | record 거부 |
| `DUPLICATE_RECORD_ID` | id가 파일·dataset 안에서 중복 | 전체 실패 |
| `EMPTY_TEXT` | 정규화 후 빈 text | record 거부 |
| `TEXT_TOO_LONG` | 설정 최대 문자 수 초과 | record 거부 |
| `NUL_CHARACTER` | NUL 포함 | record 거부 |
| `UNAPPROVED_SOURCE` | source·approval 미승인 | 전체 실패 |
| `UNAPPROVED_LICENSE` | license 미승인 | 전체 실패 |
| `PII_NOT_CLEAR` | PII 상태가 `clear` 아님 | 전체 실패·격리 |
| `DUPLICATE_RECORD` | exact duplicate | 중복 보고·제외 |
| `INVALID_SPLIT_RATIO` | 비율 validation 실패 | 전체 실패 |
| `SPLIT_LEAKAGE` | split 간 직접 누수 | 전체 실패 |
| `ARTIFACT_WRITE_ERROR` | atomic 산출물 쓰기 실패 | 전체 실패 |
| `CHECKSUM_MISMATCH` | 계산·검증 checksum 불일치 | 전체 실패 |
| `MANIFEST_MISMATCH` | manifest와 artifact 불일치 | 전체 실패 |

- [확정] 오류 코드는 중복 없이 문자열로 사용한다.
- [검증 필요] Python exception class와 CLI 노출 형식·숫자 종료 코드는 구현 단계에서 정한다. 숫자형 데이터 오류 코드는 이 문서에서 확정하지 않는다.

## 23. 실패 처리

### 23.1 전체 실행 실패

- [확정] 입력 읽기 실패, 미지원 형식, 잘못된 encoding, JSONL parse 실패 또는 schema 정의 자체가 유효하지 않음
- [확정] 원본 mutation, 중복 record ID, 미승인 source·license·approval, PII 비-`clear`
- [확정] split 비율 오류·leakage, artifact 쓰기·checksum·manifest 불일치
- [확정] 모든 record 처리 후 `accepted_count == 0`

### 23.2 기록 후 계속 가능한 record 처리

- [확정] 빈 text, 필수 field 누락, field type·형식 오류, unknown top-level field와 최대 text 길이 초과는 rejection에 기록하고 다음 record를 검사할 수 있다.
- [확정] exact duplicate는 duplicate artifact에 기록하고 대표 record만 유지한다.
- [확정] 전체 실패가 확정되면 최종 dataset version을 publish하지 않는다. 오류 원인과 제한된 진단 정보는 보존한다.

## 24. Atomic artifact write

- [확정] 최종 dataset version과 같은 filesystem의 sibling staging 경로에 모든 파일을 작성한다.
- [확정] 파일을 flush하고 내구성이 요구되는 환경에서는 fsync 또는 OS가 제공하는 동등 절차를 적용한 뒤 checksum과 schema를 검증한다.
- [확정] 모든 검증이 성공한 경우에만 staging 경로를 최종 version 경로로 atomic rename·replace한다.
- [확정] Windows와 Linux에서 지원되는 같은 volume의 원자적 파일·디렉터리 교체 방식을 사용하고, 지원되지 않으면 명시적으로 실패한다.
- [확정] 최종 경로가 이미 존재하면 overwrite하지 않고 실패한다. overwrite 기능은 Phase 1에서 제외한다.
- [확정] 실패한 staging 산출물이 정상 dataset version으로 보이거나 일부 최종 파일만 남아서는 안 된다.

## 25. 재실행 계약

- [확정] 동일 입력 bytes, resolved 설정, pipeline version과 Git SHA에서는 `records.jsonl`, split 내용·배정, 모든 content checksum, dataset fingerprint, statistics와 lineage의 결정론적 field가 같아야 한다.
- [확정] `created_at`, 실행 시간, log timestamp와 staging 임시경로는 달라질 수 있다.
- [확정] 운영 시각을 포함한 artifact byte checksum과 시각 비의존 dataset fingerprint를 구분한다.
- [확정] 같은 dataset ID·version의 최종 경로가 존재하면 실패하며 기존 결과를 변경하지 않는다.

## 26. Gate 2 검증 기준

Gate 2 상태는 이 문서 작성으로 변경되지 않으며 [개발 로드맵](../quality/development-roadmap.md)의 `planned`를 유지한다. 통과에는 최소 다음 증거가 모두 필요하다.

- [검증 필요] DATA-001~016 구현과 전체 unit test 통과
- [검증 필요] 허용 fixture 기반 integration test와 `.txt`·`.jsonl` 정상 처리
- [검증 필요] 원본 불변, SHA-256 file/raw/normalized checksum과 manifest 검증
- [검증 필요] canonical record, exact dedup과 결정론적 group split 검증
- [검증 필요] group·checksum·record·source record leakage 0건
- [검증 필요] rejection, duplicate, statistics, lineage와 resolved config 생성·상호 count 일치
- [검증 필요] 미승인 source·license·approval과 PII 비-`clear` 차단
- [검증 필요] 동일 입력 재실행 결과 일치, 입력 순서·CWD·Windows 경로 독립성
- [검증 필요] atomic write 실패 시 부분 최종 artifact 없음, 기존 version overwrite 차단
- [검증 필요] 추적 금지 산출물 0건, 모든 필수 test 통과와 사용자 승인

## 27. 미결정 사항

### 27.1 구현 전에 결정

- [검증 필요] 최대 text 문자 수 기본값과 metadata 최대 중첩 깊이
- [검증 필요] split seed type, 비율 합 허용 오차, 기본 비율과 validation/test 0 허용 여부
- [검증 필요] 실제 config schema 위치와 pipeline package·Python class·CLI 명령 이름
- [검증 필요] schema·pipeline·normalization의 최초 version 문자열과 ID 명명 규칙

### 27.2 실제 데이터 또는 후속 Phase에서 결정

- [검증 필요] 실제 외부 dataset과 license·목적별 승인
- [검증 필요] near duplicate와 개인정보 자동 탐지 방식
- [검증 필요] 대용량 streaming·multiprocessing 처리
- [검증 필요] tokenizer 학습, 학습용 packing과 token 단위 통계

## 28. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] Phase 1 DATA-001~016의 입력·schema·SHA-256·manifest·NFC·exact dedup·group split·산출물·오류·Gate 2 계약 작성 |
