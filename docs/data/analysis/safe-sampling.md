# AI Hub ZIP 안전 표본 추출 정책

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-23
- 선행 문서: [구조 분석 안내](./README.md), [데이터 거버넌스 ADR](../../decisions/ADR-004-data-governance.md)
- 후속 문서: [AIHUB-71748 표본 결과](./AIHUB-71748-sampling.md), 목적별 수동 승인

## 안전 표본 추출 목적

- [확정] ZIP 원본을 변경하지 않고 schema 검토에 필요한 소수 text 형식만 외부 격리 경로에 추출한다.
- [확정] 표본 추출 성공은 라이선스·PII·Tokenizer·학습 승인이 아니다.
- [확정] 전체 archive 압축 해제, 위험 경로 자동 교정과 저장소 내부 원문 복사는 범위에서 제외한다.

## 전체 압축 해제와 차이

| 구분 | 안전 표본 추출 | 전체 압축 해제 |
|---|---|---|
| 대상 | 결정론적으로 선택한 소수 entry | 전체 entry |
| 형식 | JSON·JSONL·TXT·CSV·TSV | 제한 없음 |
| 크기 | 파일·전체 byte 상한 | 대용량 가능 |
| 위험 entry | 즉시 거부 | 도구 동작에 의존할 위험 |
| 출력 | 외부 `analysis/samples`의 격리 run | [제외] |

## ZIP Slip 방지

- [확정] `/`, `\`, drive, UNC, `..`, NUL, 빈 이름, 출력 root 이탈과 비정상 장경로를 거부한다.
- [확정] 위험한 선행 구분자나 `..`를 제거해 entry를 살리지 않는다.
- [확정] symlink, hardlink 후보, device·특수 파일과 암호화 entry를 추출하지 않는다.
- [확정] 안전 상대경로라도 archive별 namespace를 추가해 같은 이름의 덮어쓰기를 차단한다.

## 허용·거부 entry

| 허용 조건 | 거부 조건 예시 |
|---|---|
| 일반 파일·안전 상대경로 | 절대·UNC·drive·traversal |
| 허용 확장자 | 오디오·이미지·PDF·XLSX·실행 파일 |
| 0 byte 초과·파일 상한 이하 | 빈 파일·대용량·임시 파일 |
| 비암호화 | 암호화·symlink·device·손상 ZIP |

Archive 상태는 `safe_for_sampling`, `partially_safe`, `unsafe`, `corrupted`, `encrypted`, `unsupported`를 사용한다. `partially_safe`에서는 안전 entry만 후보가 될 수 있다.

## 표본 제한과 선택

- 기본 표본 수 20개, 파일당 5 MiB, 전체 50 MiB다.
- [확정] 선택 rank는 고정 seed, Dataset ID, archive 상대경로와 entry 상대경로의 SHA-256으로 계산한다.
- [확정] archive별 첫 후보를 우선한 뒤 SHA-256 rank 순으로 채운다. Python `hash()`는 사용하지 않는다.
- [검증 필요] Training·Validation, 원천·라벨·확장자별 추가 균형은 실제 안전 후보가 확인된 후 검토한다.

## 출력 경로와 게시

논리 출력은 `analysis/samples/<Dataset ID>/<Run ID>/`이며 실제 절대 root는 Git 제외 로컬 설정에만 둔다.

```text
<Run ID>/
├── extracted/                 # 실제 실행에서 안전 표본이 있을 때만
├── sample-manifest.json
├── rejected-entries.json
├── schema-summary.json
├── run-summary.json
└── manual-review-required.json  # 안전 후보가 없을 때
```

- [확정] staging에서 파일 크기·CRC·SHA-256·일반 파일·출력 경계를 검증한 뒤 디렉터리를 게시한다.
- [확정] 같은 Run ID를 덮어쓰지 않으며 실패 시 미완성 staging을 제거한다.

## 원문 비공개 원칙

- 원문 cell·문장·JSON line과 위험 entry 전체 경로를 manifest·로그·Markdown에 기록하지 않는다.
- 안전 entry는 외부 manifest에 상대경로만 기록한다.
- 위험 entry는 이름 SHA-256, 확장자, 크기, reason code와 제한된 prefix 범주만 기록한다.
- Git 추적 문서에는 실제 로컬 절대경로와 추출 원문을 포함하지 않는다.

## 실행 명령

```powershell
python -m scripts.datasets.sample_aihub_dataset --config configs/local-datasets.yaml --dataset AIHUB-71748 --dry-run --sample-count 20
python -m scripts.datasets.sample_aihub_dataset --config configs/local-datasets.yaml --dataset AIHUB-71748 --sample-count 20
```

- [확정] 두 번째 명령은 dry-run에서 안전 후보가 확인되고 별도 실행 판단이 가능할 때만 사용한다.
- 특정 ZIP은 `--archive`에 dataset root 기준 상대경로를 전달한다.

## Schema 검토

- JSON·JSONL·TXT는 기존 제한 profiler를 재사용한다.
- CSV·TSV는 제한 byte·행·열·field 길이 안에서 header·type 후보만 기록한다.
- text, label·metadata와 PII field 이름은 후보 경고이며 원문 값은 저장하지 않는다.

## 승인 절차

1. dry-run으로 archive·entry 안전 상태를 확인한다.
2. 안전 후보와 거부 사유를 수동 검토한다.
3. 안전 후보가 있을 때만 제한 추출 실행 여부를 결정한다.
4. schema·PII·권리·평가 누수를 별도로 검토한다.
5. [승인 로그](../dataset-approval-log.md)에서 목적별 상태를 사용자가 결정한다.

## 실패 처리

- 손상·암호화·경로 위험은 숨기지 않고 reason code로 기록한다.
- CRC·checksum·크기·출력 경계 검증 실패 시 게시하지 않는다.
- 안전 후보 0개는 구현 실패가 아니라 `manual_review_required` 결과다.
- [후순위] 선행 slash를 허용하는 수동 mapping mode는 별도 설계·승인 전 구현하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] ZIP Slip 차단, 제한 선택·추출·검증·atomic publish와 비공개 보고 계약을 구현 결과에 맞춰 작성함 |

