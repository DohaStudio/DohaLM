# AIHUB-71748 tokenizer development 검토 계획

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `approved` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [로컬 package manifest](./aihub-71748-local-package.manifest.yaml), [ZIP checksum inventory](./aihub-71748-zip-checksums.manifest.yaml), [데이터셋 승인 로그](./dataset-approval-log.md), [데이터셋 라이선스 검토](./dataset-license-review.md), [ADR-004](../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | 별도 사용자 승인 후 PII·저작권·누수 검토, Adapter·tokenizer development 승인 결정 |
| 구현 전 필수 여부 | AIHUB-71748 tokenizer development 승인 전 예 |

- [확정] 사용자는 2026-07-26 `AIHUB-71748`의 tokenizer 목적을 `approved_tokenizer_development`로 승인했다. 범위는 Training의 `data_info[].contents`를 사용한 최소 corpus와 운영 16k 후보 2개 개발·비교까지다.
- [확정] 학생·비상업적 연구 및 개인 학습 범위의 라이선스 상태는 `approved_student_noncommercial`이며 상업적 이용과 원본·파생 데이터 재배포는 승인되지 않았다.
- [확정] 승인된 최소 schema 확인은 [검토 결과](./analysis/AIHUB-71748-tokenizer-schema-review.md)에 기록했으며 실제 문자열 값 출력·저장은 0건이다.
- [확정] tokenizer 전용 Adapter, corpus 생성, SentencePiece Unigram/BPE 16k 후보 학습·비교만 허용한다. Pretraining·SFT·Preference·모델/GPU 학습과 Gate 7 변경은 계속 금지한다.

## 2. 현재 기준선

| 항목 | 상태 |
|---|---|
| 로컬 package | `downloaded_restricted` |
| Registry | `reviewing` |
| License | `approved_student_noncommercial` |
| Commercial / 원본·파생 재배포 | `not_approved` |
| Tokenizer 목적 | `approved_tokenizer_development` |
| 그 밖의 목적별 승인 | `pending` |
| Adapter | `approved_tokenizer_development_only` |
| `source_manifest_eligible` | `false` |
| 원본 ZIP | 55개, 17,256,335,769 bytes, 개별 SHA-256 기록 완료 |
| 취득일·제공자 version·owner | 미확정 |

## 3. 검토 질문과 완료 증거

| 검토 항목 | 확인 질문 | 필요한 증거 | 미충족 시 상태 |
|---|---|---|---|
| 라이선스 범위 | 학생·비상업 연구와 개인 학습 경계를 벗어나지 않는가 | `approved_student_noncommercial` 결정과 상업·재배포 차단 상태 | 범위 이탈 시 사용 차단 |
| tokenizer development 적합성 | 승인된 범위에서 일반 말뭉치와 파생 artifact를 안전하게 다룰 수 있는가 | text field·PII·누수·저장 위치와 목적별 승인 | `under_review`, corpus·학습 차단 |
| PII 위험 | 일반 말뭉치의 자유서술 text와 metadata에 식별정보가 있는가 | 별도 승인된 최소 표본 정책, 검사 기준·결과, 사람 검토 기록 | `under_review`, corpus 차단 |
| 평가·누수 위험 | Validation, 공개 QA·instruction, 평가 후보가 tokenizer 입력에 섞이는가 | subset 분리 규칙, benchmark exclusion 목록, exact·near contamination 계획 | `under_review`, Validation 전체 제외 |
| 사용할 text field | 일반 corpus의 순수 원문 field가 무엇이며 label·role·instruction과 분리되는가 | 최소 schema에서는 `data_info[].contents` 후보 확인, archive 간 일관성 추가 검토 | `under_review`, Adapter 차단 |
| 최소 schema 범위 | Training·Validation 비교가 승인 상한을 지켰는가 | 각 1 ZIP·1 JSON·3 Record, 총 6 Record, 문자열 값 출력 0 | 완료, 확대 검토는 별도 승인 |
| 후속 표본 방식 | package 대표성과 PII·누수를 어떻게 제한 검토하는가 | Training 일반 말뭉치만 결정론적 층화, 수치 상한·seed·보존 기간 별도 승인 | `[검증 필요]`, 추가 표본 차단 |
| 원문·파생 데이터 보존 | 원본 불변과 Git 제외를 어떻게 보장하는가 | 외부 root 기반 저장 정책, checksum 전후 비교, 보존·삭제 책임자 | `under_review`, 파생 산출물 생성 차단 |

## 4. 제한 표본 후속안

최소 schema 확인은 완료됐으며 이 절은 다음 사용자 승인을 위한 확대 검토 계획만 정의한다.

1. `approved_student_noncommercial` 범위와 상업·재배포 금지를 모든 후속 산출물에 유지한다.
2. `Training/01.원천데이터`의 일반 말뭉치 후보만 대상으로 두고 `Validation`, RLHF, 라벨링, SFT, RM, PPO와 평가 후보는 기본 제외한다.
3. `data_info[].contents`를 유일한 tokenizer text 후보로 두되 다른 archive의 schema 일관성과 PII·권리 검토 전 확정하지 않는다.
4. 표본은 archive 상대경로, 구어체·문어체 source 유형과 archive 크기 구간을 기준으로 결정론적으로 층화한다.
5. 이번 개발 corpus는 상대경로 순 25개 Training 일반 원천 ZIP에 각각 최대 8,192 records·20 MiB를 적용하고, record 최대 4 MiB와 NFC 정규화·정확 중복 제거를 사용한다. 이는 후보 비교를 위한 결정론적 층화 상한이며 전체 corpus 대표성의 최종 확정이 아니다.
6. 승인된 경우에도 원문은 외부 root 아래 격리된 ignored 경로에서만 취급하고 저장소에는 비민감 소형 manifest와 집계만 기록한다.

## 5. 저장·계보 원칙

- 원본 기준 경로는 로컬 설정이 가리키는 `extracted/AIHUB-71748`이며 수정·이동·삭제·이름 변경하지 않는다.
- 후속 파생 데이터 후보 위치는 로컬 설정의 외부 root 아래 `analysis/tokenizer-development/AIHUB-71748/`로 제한한다. 이 상대경로는 계획이며 생성 승인이 아니다.
- 절대경로는 코드·공개 설정·추적 문서에 기록하지 않는다.
- 원본 ZIP 55개의 개별 SHA-256은 [checksum inventory](./aihub-71748-zip-checksums.manifest.yaml)를 기준으로 삼고, 처리 승인이 생기면 전후 동일성을 검증한다.
- 실제 취득일, 제공자 package version과 데이터 owner는 증빙 확인 전 `null` 또는 `unknown`으로 유지한다. filesystem timestamp를 취득일로 대체하지 않는다.
- 필수 취득 계보와 목적별 승인이 충족되기 전 `source_manifest_eligible: false`를 유지한다.

## 6. Fail Closed 전이 조건

다음 조건을 이번 사용자 승인에 따라 tokenizer development에 한해서 적용한다. 범위를 벗어나거나 checksum이 달라지면 즉시 Fail Closed로 복귀한다.

- 학생·비상업 연구·개인 학습 범위 유지와 상업·재배포 차단 확인
- 미확정 취득 계보·source별 저작권 위험 기록
- PII·저작권·평가 누수 검토 범위와 책임자 승인
- 일반 corpus subset과 `data_info[].contents` field 확정
- 제한 표본의 수치 상한·층화·seed·보존 기간 승인
- 외부 ignored 출력 경로와 원본 전후 checksum 검증 절차 확인
- Adapter 활성화, corpus 생성과 tokenizer 학습을 각각 별도 승인 대상으로 유지

조건이 하나라도 미충족이거나 checksum·파일 집합이 달라지면 즉시 중단하고 `under_review` 또는 더 제한적인 상태를 유지한다. Gate 3과 Gate 7 상태는 이 검토로 변경하지 않는다.

## 7. 다음 승인 요청 항목

1. `contents`의 PII·저작권 위험을 확인할 추가 최소 표본 범위
2. 제한 표본의 `max_records`, `max_bytes`, archive별 상한, seed와 보존 기간
3. PII 검사 방식과 사람이 볼 수 있는 최소 범위
4. Training 내 평가·benchmark 유래 record의 contamination 검사 계획
5. Adapter 활성화와 tokenizer development의 별도 목적별 승인

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] 학생·비상업 라이선스 상태, 최소 6 Record 값 비노출 schema 결과, `contents` 후보, Validation 제외와 PII 후속 계획을 반영함 |
| 2026-07-26 | [확정] AIHUB-71748 tokenizer 목적을 비승인 `under_review` 후보로 관리하기 위한 공식 조건·PII·누수·field·표본·저장·Fail Closed 검토 계획을 작성함 |
