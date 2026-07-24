# AI Hub 데이터셋 구조 분석 안내

## 문서 정보

- 문서 상태: `review`
- 마지막 검토일: 2026-07-24
- 적용 범위: 로컬에 제한 보관한 AI Hub 후보 5종의 읽기 전용 구조 분석

## 분석 목적

- [확정] 토크나이저·사전학습·SFT·평가 목적별 승인에 앞서 파일, 압축 패키지, 형식과 분할 구조를 파악한다.
- [확정] 자동 분석은 후보 적합성 판단을 돕지만 데이터 사용 승인이나 라이선스 승인을 대신하지 않는다.
- [확정] 저장소에는 집계 결과만 기록하며 원본 데이터와 원문 예시는 포함하지 않는다.

## 외부 경로 구성

실제 절대 경로는 Git에서 제외한 `configs/local-datasets.yaml`에만 둔다. 저장소에는 [설정 예시](../../../configs/local-datasets.example.yaml)만 추적한다. 보고서에는 `external_root: configured_locally`와 데이터셋 상대 경로만 기록한다.

분석 산출물은 기본적으로 외부의 `analysis/<Dataset ID>/`에 기록한다. 원본 디렉터리와 저장소 내부는 출력 위치로 허용하지 않는다.

## 실행 방법

```powershell
python -m scripts.datasets.analyze_aihub_dataset --config configs/local-datasets.yaml --dataset AIHUB-71748 --inventory-only
python -m scripts.datasets.analyze_aihub_dataset --config configs/local-datasets.yaml --all --json
```

- `--inventory-only`: 파일 메타데이터와 ZIP 중앙 디렉터리만 조사한다.
- 기본 quick profile: 직접 접근 가능한 JSON·JSONL·TXT만 제한적으로 조사한다. ZIP entry 내용은 읽지 않는다.
- `--sample-files`, `--max-json-bytes`: 결정론적 표본 수와 JSON 크기 상한을 조정한다.
- `--output-dir`: 외부 분석 디렉터리만 지정할 수 있다.

## 결과 갱신 절차

1. 로컬 설정과 대상 root를 확인한다.
2. 합성 테스트를 통과시킨다.
3. inventory-only를 먼저 실행한다.
4. 원본 metadata digest와 무변경 결과를 확인한다.
5. quick profile을 실행하고 외부 JSON을 검토한다.
6. 이 디렉터리의 집계 문서를 수동 갱신하고 링크·원문·절대 경로 노출을 검사한다.

## 자동 판정과 수동 승인

| 구분 | 의미 |
|---|---|
| 자동 탐지 | 경로명·확장자·schema 통계를 이용한 후보 표시 |
| `manual_review_required` | 원문을 기록하지 않는 별도 승인 검토 필요 |
| 목적별 승인 | [승인 로그](../dataset-approval-log.md)에 기록되는 사용자 결정 |

- [확정] 5종 모두 `candidate_status: registered`, 목적별 승인은 `pending`으로 유지한다.
- [검증 필요] 로컬 package 존재는 공식 다운로드 계보와 이용조건 검토가 끝났음을 의미하지 않는다.

## 문서 상태 체계

문서 자체에는 `planned`, `draft`, `review`, `approved`, `implemented`, `deprecated`를 사용하고 본문 판단에는 `[확정]`, `[가정]`, `[검증 필요]`, `[후순위]`, `[제외]`를 사용한다.

## 민감정보 기록 금지

- [확정] 원문 문자열, JSON line, 개인정보 추정 값, 로컬 절대 경로를 로그·Markdown·분석 JSON에 기록하지 않는다.
- [확정] PII field 이름 탐지는 위험 신호일 뿐 개인정보 존재 여부의 확정 판정이 아니다.
- [확정] ZIP은 자동 압축 해제하지 않는다. 기본 구조 분석은 entry를 읽지 않으며, 별도 승인된 bounded inspector만 명시된 byte 상한에서 값을 저장하지 않고 stream으로 읽는다.

## 관련 문서

- [데이터셋 비교 요약](./dataset-analysis-summary.md)
- [ZIP 안전 표본 추출 정책](./safe-sampling.md)
- [AIHUB-71748 안전 표본 결과](./AIHUB-71748-sampling.md)
- [명시적 수동 경로 mapping 계약](./manual-path-mapping.md)
- [AIHUB-71748 mapping 후보 검토](./AIHUB-71748-path-mapping.md)
- [대용량 JSON 제한 streaming 검사](./large-json-inspection.md)
- [ZIP JSON record 제한 분석 계약](./zip-json-record-sampling.md)
- [AIHUB-71748 record 분석 결과](./AIHUB-71748-record-sampling.md)
- [층화 record schema·PII review 계약](./stratified-record-review.md)
- [AIHUB-71748 schema·PII review 결과](./AIHUB-71748-schema-review.md)
- [후보 등록부](../dataset-candidate-registry.md)
- [라이선스 검토](../dataset-license-review.md)
- [Phase 2 토크나이저 계약](../../training/phase2-tokenizer-contract.md)

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] Archive·entry·bounded record 구간 층화와 AIHUB-71748 schema·PII review 결과를 연결함 |
| 2026-07-24 | [확정] ZIP JSON array record 경계 분석 계약과 AIHUB-71748 bounded inspection 결과를 연결함 |
| 2026-07-24 | [확정] 대용량 JSON bounded streaming과 원문 비노출 prefix review 결과 문서를 연결함 |
| 2026-07-24 | [확정] 일반 안전 sampler와 분리된 수동 mapping 계약 및 AIHUB-71748 pending 후보 문서를 연결함 |
