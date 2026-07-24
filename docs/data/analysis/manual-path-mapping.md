# AI Hub ZIP 명시적 수동 경로 mapping 계약

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 선행 문서: [ZIP 안전 표본 추출 정책](./safe-sampling.md), [데이터 거버넌스 ADR](../../decisions/ADR-004-data-governance.md)
- 후속 문서: [AIHUB-71748 mapping 검토](./AIHUB-71748-path-mapping.md), 사용자 mapping 승인과 제한 dry-run

## 목적과 기본 정책의 관계

- [확정] 일반 안전 표본 모드는 `/`, drive, UNC와 traversal entry를 계속 거부한다.
- [확정] 수동 mapping은 일반 모드의 자동 정규화가 아니라, 별도 YAML에서 사용자가 승인한 절대 POSIX prefix 하나를 상대 prefix 하나로 치환하는 명시적 실행 모드다.
- [확정] `--manual-mapping`이 없으면 기존 일반 모드가 동작하며 선행 `/`를 제거하지 않는다.
- [확정] mapping 파일이 없거나 승인 상태가 아니면 수동 모드는 추출과 dry-run 산출물 생성을 시작하지 않는다.

## 승인 절차

1. [mapping 예시](../../../configs/aihub-71748-path-mapping.example.yaml)를 로컬 Git 제외 파일 `configs/aihub-71748-path-mapping.yaml`로 복사한다.
2. ZIP 중앙 디렉터리의 hash·prefix 집계와 공식 package 설명을 비교한다.
3. 허용할 source prefix, 격리 target prefix와 확장자를 최소 범위로 작성한다.
4. 검토 전에는 `approval.status: pending_user_review`, `approved_by: null`, `approved_at: null`을 유지한다.
5. 사용자가 규칙 전체를 검토한 뒤에만 상태를 `approved`로 바꾸고 승인자와 승인 시각을 기록한다.
6. 승인된 파일로 먼저 `--dry-run`을 실행하고 선택·거부·원본 불변 결과를 검토한다.
7. 별도 사용자 판단 전에는 비-dry-run 추출을 실행하지 않는다.

## Mapping schema

```yaml
schema_version: "1.0"
dataset_id: "AIHUB-71748"
approval:
  status: approved
  approved_by: "사용자 식별값"
  approved_at: "YYYY-MM-DDTHH:MM:SS+09:00"
rules:
  - source_prefix: "/승인한-prefix/"
    target_prefix: "isolated-prefix/"
    allowed_extensions:
      - .json
```

- `schema_version`: 현재 `1.0`만 지원한다.
- `dataset_id`: CLI의 Dataset ID와 정확히 같아야 한다.
- `source_prefix`: 단일 `/`로 시작하고 경계를 명확히 하도록 `/`로 끝나야 한다.
- `target_prefix`: drive·UNC·absolute·`..`가 없는 상대 POSIX 경로다.
- `allowed_extensions`: JSON, JSONL, TXT, CSV, TSV의 부분집합이다.
- Rule ID와 mapping fingerprint는 canonical JSON과 SHA-256으로 계산한다.

## 검증과 허용 범위

수동 모드는 다음을 모두 검증한다.

- 승인 상태·승인자·승인 시각과 Dataset ID
- source prefix 중복·포함 관계와 target prefix 충돌
- source prefix의 정확한 경계와 mapping 없는 entry의 전면 거부
- mapping 전후 NUL·traversal·drive·UNC·출력 root 이탈
- symlink·hardlink·device·암호화·손상·미지원 압축 방식
- 파일당·전체 byte, 허용 확장자, 임시 파일과 중복 출력

[확정] 수동 mapping은 승인 source prefix만 target prefix로 치환한다. 다른 경로 요소를 삭제하거나 수정하지 않는다.

## 결정론과 manifest

선택 rank는 고정 seed, Dataset ID, archive 상대경로, 원본 entry 이름 hash와 Rule ID를 SHA-256으로 조합한다. Python `hash()`는 사용하지 않는다.

`mapped-manifest.json`에는 다음을 기록한다.

- mapping 파일 fingerprint와 승인 metadata
- Rule ID와 sanitized source prefix
- 원본 entry 이름 SHA-256
- mapped·output 상대경로
- archive 상대경로, byte, CRC, checksum과 schema 상태
- Rule별 matched·safe·rejected·크기·확장자·경로·선택 집계
- 미매칭 확장자와 sanitized prefix group 집계

`rejected-entries.json`에는 모든 레코드에 `mapping_rule_id`, `source_prefix_hash`, `sanitized_source_prefix`, `mapping_matched`, `post_mapping_rejection`, `rejection_stage`를 기록한다. 적용되지 않는 식별자는 `null`이다.

원본 absolute entry 전체 문자열, 원문 값과 로컬 절대경로는 기록하지 않는다.

## 출력과 원본 보호

논리 출력은 `analysis/manual-samples/<Dataset ID>/<Run ID>/`다.

```text
<Run ID>/
├── mapped-manifest.json
├── mapping-validation.json
├── rejected-entries.json
├── schema-summary.json
├── run-summary.json
└── extracted/                 # 승인 후 비-dry-run에서 선택 표본이 있을 때만
```

- [확정] 원본 ZIP은 읽기 전용으로 취급하고 inventory metadata digest로 실행 전후 불변성을 확인한다.
- [확정] staging과 atomic publish를 사용하며 동일 Run ID를 덮어쓰지 않는다.
- [확정] dry-run에서는 `extracted/`를 생성하지 않는다.

## 실행 절차

승인 전에는 아래 명령을 실행하지 않는다. 승인된 로컬 mapping이 준비된 뒤 첫 실행은 반드시 dry-run이다.

```powershell
python -m scripts.datasets.sample_aihub_dataset --config configs/local-datasets.yaml --dataset AIHUB-71748 --manual-mapping configs/aihub-71748-path-mapping.yaml --sample-count 20 --dry-run
```

비-dry-run은 dry-run 결과와 mapping fingerprint가 동일하고 사용자가 제한 추출을 별도로 허용한 경우에만 검토한다.

## 실패 조건

- mapping 파일 누락·schema 오류·Dataset ID 불일치
- `approval.status != approved`, 승인자 또는 승인 시각 누락
- prefix 중복·모호성·target 충돌 또는 위험 경로
- mapping 없는 entry, prefix 경계 불일치 또는 mapping 후 안전성 실패
- 원본 metadata 변경, checksum·CRC·byte·출력 경계 검증 실패
- 기존 Run ID 또는 staging 경로 존재

실패를 우회하기 위해 선행 `/`나 `..`를 자동 제거하지 않는다.

## 데이터 승인과의 경계

- [확정] mapping 승인은 해당 prefix 치환 절차의 승인일 뿐 데이터 이용조건·PII·품질 승인이 아니다.
- [확정] 제한 표본 추출 성공도 Tokenizer·사전학습·SFT·평가 승인을 변경하지 않는다.
- [확정] Gate 3은 목적별 corpus 승인과 토크나이저 검증 전까지 `planned`다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] rejection stage·Rule ID·prefix hash와 rule별·미매칭 집계 계약을 추가하고 실제 dry-run으로 검증함 |
| 2026-07-24 | [확정] 일반 모드와 분리된 사용자 승인 prefix mapping, 격리 출력, 결정론·manifest·실패 계약을 구현 결과에 맞춰 정의함 |
