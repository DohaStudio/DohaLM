# AIHUB-71748 tokenizer 최소 schema 검토 결과

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-26 |
| 선행 문서 | [Tokenizer development 검토 계획](../aihub-71748-tokenizer-development-review-plan.md), [구조 분석](./AIHUB-71748.md), [데이터 거버넌스 ADR](../../decisions/ADR-004-data-governance.md) |
| 후속 문서·작업 | PII 제한 검토 승인, Adapter·corpus·tokenizer development 목적별 승인 |
| 구현 전 필수 여부 | AIHUB-71748 tokenizer development 승인 전 예 |

- [확정] 이 검토는 사용자가 승인한 최소 schema metadata 확인이며 실제 문자열 값을 출력하거나 저장하지 않았다.
- [확정] 학생·비상업적 연구 및 개인 학습 라이선스 상태는 `approved_student_noncommercial`이다.
- [확정] 이 최소 schema 검토 당시 tokenizer 목적은 `under_review`였다. 2026-07-26 후속 사용자 승인으로 현재는 `approved_tokenizer_development`이며 Training `contents` 전용 Adapter·corpus·후보 학습에만 적용된다.

## 검사 상한과 실제 범위

| 항목 | 승인 상한 | 실제 |
|---|---:|---:|
| Training ZIP | 1 | 1 |
| Validation ZIP | 1 | 1 |
| ZIP당 JSON | 1 | 1 |
| JSON당 Record | 3 | 3 |
| 전체 Record | 6 | 6 |
| 문자열 값 출력·저장 | 0 | 0 |

| Split | ZIP 상대경로 | JSON entry | ZIP 내 JSON 수 | 읽은 Record | 누적 비압축 read |
|---|---|---|---:|---:|---:|
| Training | `3.개방데이터/1.데이터/Training/01.원천데이터/TS_01.한국어말뭉치데이터_구어체_SL01.zip` | `SL01-00-00.json` | 16 | 3 | 131,202 bytes |
| Validation | `3.개방데이터/1.데이터/Validation/01.원천데이터/VS_01.한국어말뭉치데이터_구어체_SL01.zip` | `SL01-00-00.json` | 16 | 3 | 131,202 bytes |

- [확정] 각 JSON은 세 번째 Record callback 직후 강제 중단했다. 전체 배열을 순회하지 않았으므로 전체 Record 수와 배열 길이는 미확정이다.
- [확정] 첫 probe는 최상위 배열 가정으로 각 65,536 bytes에서 Record 0건으로 종료됐고, 후속 객체 내부 배열 검사는 각 65,666 bytes를 읽었다. 누적 read는 JSON당 131,202 bytes, 전체 262,404 bytes다.
- [확정] 두 ZIP의 검사 전후 SHA-256과 전체 inventory metadata digest가 일치했다.

## 관측 schema

두 JSON에서 동일한 최소 구조를 관측했다.

```text
JSON root: object
└─ data_info: array
   └─ record: object
```

6개 Record에서 아래 field가 모두 존재했고 `null`은 관측되지 않았다. 이는 전체 package의 schema·null 비율을 확정하지 않는다.

| Field | Type | Training 관측 | Validation 관측 | 분류 |
|---|---|---|---|---|
| `contents` | string | 길이 550–2,568 | 길이 1,134–2,267 | tokenizer text 후보, PII 검토 필수 |
| `collected_date` | string | 길이 6 | 길이 6 | metadata |
| `data_author` | array | 길이 1 | 길이 1 | metadata, PII·권리 검토 필수 |
| `data_category` | object | 존재 | 존재 | metadata |
| `data_category.main` | string | 길이 3 | 길이 3 | metadata |
| `data_category.middle` | string | 길이 2–3 | 길이 2–3 | metadata |
| `data_category.sub` | string | 길이 0 | 길이 0 | metadata |
| `data_ccl` | string | 길이 5 | 길이 5 | 권리·계보 metadata |
| `data_count` | integer | 존재 | 존재 | metadata, 전체 Record 수 근거로 사용하지 않음 |
| `data_file` | string | 길이 56 | 길이 56 | source 식별 metadata |
| `data_id` | string | 길이 36 | 길이 36 | record 식별 metadata |
| `data_institution` | string | 길이 3 | 길이 3 | 권리·출처 metadata |
| `data_source` | string | 길이 42–43 | 길이 43 | source metadata, URL·권리 위험 검토 |
| `data_title` | string | 길이 21–53 | 길이 15–63 | metadata, tokenizer 입력 제외 후보 |
| `data_type` | string | 길이 2 | 길이 2 | metadata |
| `data_year` | string | 길이 4 | 길이 4 | metadata |

## Tokenizer field 판단

- [확정] 제한 표본에서 `data_info[].contents`만 일반 말뭉치 tokenizer text 후보로 식별했다.
- [확정] `contents` 값은 출력·저장·인용하지 않았고 길이만 기록했다.
- [검증 필요] 구어체 SL01의 6개 Record만으로 다른 구어체·문어체 archive의 field 일관성을 확정하지 않는다.
- [검증 필요] `contents` 내부의 PII·저작권·평가 오염 여부가 해소되기 전 Adapter와 corpus 생성을 승인하지 않는다.

## Metadata와 제외 field

- `collected_date`, `data_author`, `data_category.*`, `data_ccl`, `data_count`, `data_file`, `data_id`, `data_institution`, `data_source`, `data_title`, `data_type`, `data_year`는 tokenizer 입력 문자열에 연결하지 않는다.
- `data_ccl`, `data_source`, `data_institution`, `data_author`, `data_id`, `data_file`은 삭제하지 않고 향후 source manifest와 권리·계보 판단에 별도 보존할 후보다.
- RLHF, 라벨링, SFT, RM, PPO, instruction·question·answer·label·role field는 이번 검토 대상이 아니며 tokenizer 입력에서 기본 제외한다.

## Validation·평가 누수 정책

- [확정] `Validation/**`은 schema 비교에만 사용했고 tokenizer development 입력에서 전부 제외한다.
- [확정] 평가용 subset, 공개 QA·instruction, benchmark와 RLHF·라벨링 경로는 tokenizer 입력에서 제외한다.
- [확정] 목적별 승인 전 corpus 생성과 fingerprint·exact/near contamination 실행을 시작하지 않는다.
- [검증 필요] Training 내부에 평가·benchmark 유래 record가 포함되는지는 별도 source metadata와 contamination 검토가 필요하다.

## PII 검토 계획

| 대상 | 위험 | 다음 검토 |
|---|---|---|
| `contents` | 자유서술 내 이름·연락처·주소·계정·고유 식별정보 가능 | 별도 승인된 최소 비공개 표본에서 자동 패턴 검사와 사람 검토, 원문 로그 금지 |
| `data_author` | 저자·작성자 식별 가능성 | 값 유형·비식별 상태·권리자 구분 확인 |
| `data_title` | 인명·사건명 또는 원문 식별 가능성 | tokenizer 입력 제외 유지, PII·저작권 metadata 검토 |
| `data_source`, `data_file`, `data_id` | URL·source·record 식별자 가능성 | 원문 비출력, hash·계보용 최소 보존 범위 결정 |
| `data_institution` | 기관 식별 및 권리 조건 | source별 권리·이용조건과 연결 |

- [확정] field 이름 신호만으로 PII 부재를 선언하지 않는다.
- [확정] PII 상태는 `not_cleared`로 유지한다. 후속 사용자 승인에 따라 tokenizer 목적은 `approved_tokenizer_development`, Adapter는 `approved_tokenizer_development_only`이며 그 밖의 사용은 차단한다.

## 원본 불변과 범위 준수

- ZIP 해제·이동·수정·삭제: 0건
- 원문·preview·corpus·파생 text 파일 생성: 0건
- 문자열 값 출력·Git 기록: 0건
- 선택 ZIP 검사 전후 SHA-256 불일치: 0건
- Inventory metadata digest 불일치: 0건
- GPU·tokenization·packing·학습: 0건

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-26 | [확정] Training·Validation 각 1 ZIP·1 JSON·3 Record의 값 비노출 schema를 확인하고 `contents` 후보, metadata 제외, Validation 제외와 PII 후속 계획을 기록함 |
