# AIHUB-71748 안전 표본 추출 결과

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 관련 정책: [안전 표본 추출 정책](./safe-sampling.md)

## 분석 기준

- 실행 모드: `dry-run`
- Run ID: `dry-bc7bd30c4e3f0ca1`
- 요청 표본: 20개
- 파일당/전체 제한: 5 MiB / 50 MiB
- 허용 형식: JSON, JSONL, TXT, CSV, TSV
- [확정] ZIP entry 내용은 읽지 않았고 파일을 추출하지 않았다.

## Dry-run 결과

| 항목 | 결과 |
|---|---:|
| 조사 archive | 55 |
| `safe_for_sampling` | 0 |
| `partially_safe` | 0 |
| `unsafe` | 55 |
| 조사 entry | 1,610 |
| 안전 entry | 0 |
| 거부 entry | 1,610 |
| 선택 표본 | 0 |
| 실제 추출 | 0 |

## 거부 사유와 형식

- [확정] 1,610개 모두 `ABSOLUTE_ENTRY_PATH`로 거부됐다.
- 확장자 집계: JSON 1,609개, TXT 1개
- 제한 prefix 범주: 단일 JSON 파일형 918개, `외부데이터` 계열 573개, `RaG-데이터` 계열 119개
- [확정] 선행 `/`는 자동 제거하지 않았다.

## Schema 요약

- 상태: `not_run_dry_run`
- JSON schema signature: 0건
- JSONL·CSV·TSV·TXT parse: 0건
- [검증 필요] 안전하게 추출된 표본이 없어 schema를 확인하지 못했다.

## Text field 후보

- 미확인. 안전 표본 0개로 field profiler를 실행하지 않았다.

## Label·metadata field 후보

- 미확인. label 값을 일반 text로 간주하지 않는다.

## PII 경고

- field 이름과 원문을 확인하지 않았다. 미탐지는 PII 부재를 의미하지 않는다.

## 자동 추출 가능 여부

- `unsafe`: 현재 정책으로 자동 추출 가능한 entry가 없다.
- [확정] 실제 비-dry-run 명령은 실행하지 않았다.
- [확정] 위험 entry를 상대경로로 자동 정규화하는 기능은 구현하지 않았다.

## 수동 검토 필요 여부

- `manual_review_required`
- [검증 필요] 공식 package 구조와 선행 `/`의 의미를 확인하고, 별도의 명시적 mapping·격리 절차가 필요한지 사용자가 결정해야 한다.

## 후속 수동 mapping dry-run

관측성 개선 후 `manual-dry-8377d08464b6d194`를 실행했다.

| 항목 | 결과 |
|---|---:|
| `/외부데이터/` rule 매칭 | 573 |
| 해당 rule 안전·선택 | 1 |
| 파일 크기 초과 | 571 |
| Rule별 확장자 불일치 | 1 |
| `/RaG-데이터/` rule 매칭 | 0 |
| 미매칭 | 1,037 |
| 실제 추출 | 0 |

- [확정] 일반 sampler의 5 MiB 기본 제한은 변경하지 않았다.
- [확정] RaG sanitized group 119개는 실제 component의 공백·dash category 차이로 현재 rule과 불일치한다.
- [확정] 대용량 JSON 5개는 [제한 streaming 검사](./large-json-inspection.md)만 수행했으며 전체 파일을 추출하지 않았다.
- [확정] 후속 [ZIP JSON record 분석](./AIHUB-71748-record-sampling.md)은 총 32 MiB에서 2개 entry·3,489 record 경계를 관측했지만 원문 파일을 생성하지 않았다.
- [검증 필요] 제한 구조 관측은 실제 전체 schema 확정이 아니다.

## Tokenizer corpus 사용 가능 여부

- 현재 `사용 불가`다. 표본 추출 실패가 아니라 schema·PII·라이선스·목적별 승인이 미완료된 상태다.
- 이 dry-run 결과만으로 `approved_tokenizer_development`로 전환할 수 없다.

## 원본 불변성

| 검사 | 전후 결과 |
|---|---|
| ZIP 파일 수 | 55 → 55 |
| 총 byte | 17,256,335,769 → 17,256,335,769 |
| metadata digest | 일치 |
| 선택한 최소 ZIP SHA-256 | 일치 |
| source mutation | `false` |

Git 추적 문서에는 실제 로컬 절대경로와 선택 ZIP의 상대 파일명을 기록하지 않는다.

## 외부 산출물

최종 dry-run은 외부 `analysis/samples/AIHUB-71748/dry-bc7bd30c4e3f0ca1/`에 다음 집계 파일만 생성했다.

- `sample-manifest.json`
- `rejected-entries.json`
- `schema-summary.json`
- `run-summary.json`
- `manual-review-required.json`

`extracted/`는 생성되지 않았다.

## 현재 승인 상태

- `candidate_status: registered`
- `license_review_status: pending_terms_review`
- `approval.tokenizer/pretraining/sft/evaluation: pending`
- Gate 3: `planned`

## 다음 작업

1. 공식 package 설명과 경로 의미를 확인한다.
2. [명시적 수동 mapping 계약](./manual-path-mapping.md)과 [AIHUB-71748 mapping 후보](./AIHUB-71748-path-mapping.md)를 검토한다.
3. 승인 전에는 원문 추출·corpus 생성·토크나이저 학습을 진행하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] 대용량 JSON array의 제한 record 구조 관측과 원본 불변 결과를 연결함 |
| 2026-07-24 | [확정] 관측성 개선 수동 dry-run의 rule별 직접 집계, 추출 0건과 제한 streaming 후속 검사를 기록함 |
| 2026-07-24 | [확정] 구현된 별도 수동 mapping 계약과 pending 후보 검토 문서를 연결함 |
| 2026-07-23 | [확정] 최종 dry-run 55 archive·1,610 absolute entry 거부와 추출 0건·원본 불변 결과를 기록함 |
