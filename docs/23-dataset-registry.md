# DohaLM 데이터셋 레지스트리

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [데이터 전략](./06-data-strategy.md), [ADR-004](./decisions/ADR-004-data-governance.md) |
| 후속 문서 | [데이터 라이선스 정책](./24-data-license-policy.md), [데이터 전처리](./07-data-preprocessing.md), [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md) |
| 구현 전 필수 여부 | 예 |

- [확정] 이 문서는 등록 양식만 정의하며 실제 데이터셋을 등록하지 않는다.
- [확정] 레지스트리의 한 항목은 데이터셋 이름만이 아니라 특정 source version과 사용 조건을 식별한다.

## 2. 필드 정의

| 필드 | 의미 | 형식·기록 원칙 | 필수 | 미확정 처리 |
|---|---|---|---|---|
| `dataset_id` | 내부 고유 식별자 | 안정적이고 version과 혼동되지 않는 문자열 | 예 | 미확정 허용 안 함 |
| `name` | 사람이 읽는 데이터셋명 | 공식 명칭 우선 | 예 | 미확정 허용 안 함 |
| `source` | 원천 유형·위치 설명 | 제공 페이지·내부 반입 등 | 예 | 조사 중 표시 |
| `provider` | 제공 주체 | 공식 명칭 | 예 | `unknown`이면 승인 불가 |
| `source_url` | 공식 출처 URL | 검색 결과가 아닌 원문 링크 | 조건부 | 비공개 제공은 근거 위치 기록 |
| `acquired_at` | 취득 시각 | timezone 포함 날짜·시각 후보 | 승인 후 예 | 미취득이면 비움 |
| `version` | 원천 version | 제공자 version·snapshot 식별자 | 예 | 식별 불가 시 승인 보류 |
| `license` | 라이선스·이용조건명 | 공식 표기 | 예 | 불명확 시 승인 불가 |
| `license_url` | 조건 원문·공식 링크 | 취득 당시 내용을 함께 보존 | 예 | 비공개 조건은 보관 위치 |
| `commercial_use` | 상업적 이용 가능성 | `allowed`, `prohibited`, `conditional`, `unknown` | 예 | `unknown`이면 목적별 검토 |
| `modification_allowed` | 정제·변형 가능성 | 같은 enum | 예 | `unknown`이면 처리 금지 |
| `redistribution_allowed` | 원본·파생 데이터 재배포 | 같은 enum과 조건 설명 | 예 | `unknown`이면 재배포 금지 |
| `derived_model_release` | 파생 model weight 공개 가능성 | 같은 enum과 검토 근거 | 예 | `[법률 검토 필요]` 가능 |
| `attribution_required` | 출처 표시 의무 | boolean/conditional과 표시 문구 | 예 | 조건 미확정 |
| `language` | 언어·혼합 언어 | BCP 47 또는 명시적 목록 후보 | 예 | 실제 통계는 별도 |
| `domain` | 문서 주제·형식 | 다중 label 허용 후보 | 예 | `unknown` 허용, 승인 전 검토 |
| `raw_format` | 원본 형식 | 확장자가 아닌 실제 schema 포함 | 예 | 미취득 시 제공 명세 기준 |
| `raw_size` | 원본 byte 크기 | 실제 취득 후 계산 | 승인 후 예 | `[검증 필요]` |
| `document_count` | 논리 문서 수 | 문서 정의와 함께 기록 | 처리 후 예 | `[검증 필요]` |
| `estimated_token_count` | 특정 tokenizer 기준 추정 token | tokenizer ID·sampling 방법 포함 | 조건부 | `[검증 필요]` |
| `checksum` | 원본 무결성 값 | 알고리즘과 파일/묶음 범위 명시 | 취득 후 예 | 미취득이면 비움 |
| `personal_information_risk` | 개인정보 위험 | `low`, `medium`, `high`, `unknown` 후보와 근거 | 예 | 미검사 시 `unknown` |
| `harmful_content_risk` | 유해 콘텐츠 위험 | 동일한 위험 수준과 범주 | 예 | 미검사 시 `unknown` |
| `preprocessing_version` | 적용 전처리 version | 미처리 시 비움 | 처리 후 예 | 미처리 표시 |
| `split_version` | 적용 분할 version | 미분할 시 비움 | 분할 후 예 | 미분할 표시 |
| `status` | 데이터 생명주기 상태 | 정의된 상태값만 사용 | 예 | 미확정 허용 안 함 |
| `owner` | 검토·운영 책임자 | 사람 또는 역할 식별자 | 예 | 실제 운영 전 결정 |
| `notes` | 조건·예외·검토 근거 | 사실과 의견 상태 구분 | 아니요 | 빈 값 허용 |

- [검증 필요] 실제 저장 형식, schema validation과 ID 명명 규칙은 구현 전에 확정한다.
- [확정] `raw_size`, `document_count`, `estimated_token_count`는 측정 방법과 기준 version 없이 숫자만 기록하지 않는다.

## 3. 상태값

| 상태 | 의미 |
|---|---|
| `candidate` | 식별된 후보, 검토 전 |
| `reviewing` | 라이선스·품질·위험 검토 중 |
| `approved` | 특정 version·목적 사용 승인 |
| `rejected` | 사유를 기록하고 사용 제외 |
| `downloaded` | 승인 후 원본 취득·checksum 확인 |
| `processed` | 승인된 전처리·분할 완료 |
| `deprecated` | 신규 사용 중단, 기존 계보만 유지 |

- [확정] 상태 전이는 [데이터 전략](./06-data-strategy.md)의 조건을 따른다.
- [확정] `unknown` 라이선스는 `approved`로 전환할 수 없다.

## 4. 승인 절차

1. `candidate`: 식별 정보, 공식 출처와 version을 등록한다.
2. `reviewing`: 공식 이용조건을 보존하고 목적별 권한과 위험을 검토한다.
3. 품질·개인정보·유해성·누수 검토 결과와 승인자를 기록한다.
4. 근거가 충족되면 `approved`, 아니면 사유와 함께 `rejected`로 전환한다.
5. 승인된 version만 취득하고 checksum 확인 후 `downloaded`로 전환한다.
6. 전처리·분할 manifest와 품질 결과가 연결되면 `processed`로 전환한다.
7. 조건 변경·오류·대체가 있으면 `deprecated` 처리하고 영향 실험을 추적한다.

## 5. 가상 예시

> [가정] 아래는 schema 설명을 위한 완전한 가상 예시다. 실제 데이터셋, 제공자, URL 또는 승인 기록이 아니다.

```yaml
dataset_id: "example-korean-corpus"
name: "가상 한국어 말뭉치"
source: "문서 예시용 가상 출처"
provider: "가상 제공자"
source_url: "https://example.invalid/dataset"
acquired_at: null
version: "example-v0"
license: "검토 전 가상 조건"
license_url: "https://example.invalid/license"
commercial_use: "unknown"
modification_allowed: "unknown"
redistribution_allowed: "unknown"
derived_model_release: "unknown"
attribution_required: "conditional"
language: ["ko"]
domain: ["example"]
raw_format: "가상 JSONL schema"
raw_size: null
document_count: null
estimated_token_count: null
checksum: null
personal_information_risk: "unknown"
harmful_content_risk: "unknown"
preprocessing_version: null
split_version: null
status: "candidate"
owner: "미지정"
notes: "문서 양식 설명 전용이며 실제 사용 금지"
```

- [확정] 가상 예시는 권리와 품질이 확인되지 않았으므로 `candidate`이며 다운로드·학습 대상이 아니다.

## 6. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 데이터셋 registry 필드, 상태 전이, 승인 절차와 가상 예시 정의 |
