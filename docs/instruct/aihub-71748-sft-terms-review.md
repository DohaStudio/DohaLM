# AIHUB-71748 SFT 이용조건 검토

- 문서 상태: `review`
- 최종 검토일: 2026-07-28
- Dataset ID: `AIHUB-71748`
- 검토 목적: Instruct SFT 사용 가능성의 법적·거버넌스 사전 검토
- SFT 승인 상태: `not_approved`
- 관련 문서: [AI Hub 후보 검토](./aihub-dataset-candidate-review.md), [Dataset 라이선스 검토](../data/dataset-license-review.md), [ADR-004](../decisions/ADR-004-data-governance.md)

## 1. 범위와 판정 원칙

이 문서는 AIHUB-71748의 공식 페이지와 공통 이용정책, 기존 로컬 package 계보를 비교한다. 이번 작업은
약관 문서화만 수행하며 dataset 선택, ZIP/record read, 검증 scan, 변환과 SFT를 승인하지 않는다.

- 공식 문구로 직접 확인되지 않은 권리는 `verification_required`로 둔다.
- 로컬 package 존재를 다운로드 승인 증빙으로 간주하지 않는다.
- 기존 사용자 결정 `approved_student_noncommercial`을 유지하되 목적을 SFT로 자동 확대하지 않는다.
- 취득 당시 조건 snapshot과 현재 웹 정책이 같다고 가정하지 않는다.
- 공통 정책과 dataset/source별 별도 조건이 충돌하면 더 제한적인 조건으로 Fail Closed한다.

## 2. 공식 근거

| 근거 | URL | 확인 범위 | 한계 |
|---|---|---|---|
| AI Hub 공통 이용정책 | [공식 페이지](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105) | 연구·개발 활용, 권리 주체, 신청·제3자 제공·개인정보 원칙 | dataset별·취득 당시 조건을 대체하지 않음 |
| Dataset 71748 상세 페이지 | [공식 페이지](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71748) | Dataset ID와 공개 endpoint | 현재 자동 조회에서 상세 title·version·갱신일 전체를 독립 재확인하지 못함 |
| 로컬 package manifest | [manifest](../data/aihub-71748-local-package.manifest.yaml) | 로컬 명칭, 구성, checksum, 승인 snapshot | 제공자 발급 약관·다운로드 승인 증빙이 아님 |

## 3. 공통 AI Hub 이용정책 검토

| 항목 | 확인 결과 | 현재 프로젝트 판정 |
|---|---|---|
| 교육 목적 | 교육만을 별도 허용하는 명시적 dataset 조건은 이번 조회에서 미확인 | `verification_required` |
| 학생 프로젝트 | 신청자 신분과 프로젝트 목적에 적용되는 개별 조건 미확인 | 기존 사용자 결정 범위에서 `conditionally_supported` |
| 연구·개발 목적 | AI 기술·제품·서비스의 영리·비영리 연구·개발 활용 문구 확인 | 공통 정책 확인, dataset별 조건 우선 |
| 비상업적 이용 | 기존 승인 범위는 학생·비상업 연구·개인 학습 | `approved_student_noncommercial` 유지 |
| 원본 재배포 | 승인 없는 제3자 제공·양도·대여·판매 제한 | `not_approved` |
| 가공 데이터 재배포 | SFT 변환물에 대한 명시적 허용 미확인 | `not_approved`, `verification_required` |
| 모델 가중치 공개 | 데이터가 반영된 weight 공개 조건 미확인 | `not_approved`, `verification_required` |
| 파생 결과물 공개 | 논문·보고와 데이터/weight 공개를 동일하게 볼 수 없음 | 범주별 `verification_required` |
| 상업 전환 | 현재 프로젝트 범위가 아니며 dataset별·source별 조건 확인 필요 | `not_planned` |
| 출처 표시 | 기존 공식 정책 검토에서 활용 사실 표시 의무를 기록함 | `required`; 정확한 표기문구는 `verification_required` |
| 신청자 계정 조건 | 본인 확인·정보 제공·사용 목적 제출 및 심사 절차가 있음 | 로컬 취득 증빙 없이는 승인 추정 금지 |
| 데이터셋별 별도 제한 | NIA 비권리 자료와 source별 조건은 해당 기관 정책이 우선할 수 있음 | source·CCL별 확인 필요 |

현재 공통 페이지의 영리·비영리 연구·개발 활용 문구는 AIHUB-71748의 SFT, 재배포, weight 공개를 개별적으로
승인하는 문구가 아니다. 프로젝트의 더 제한적인 학생·비상업 결정과 공개 금지를 유지한다.

## 4. Dataset 상세 identity

| 항목 | 확인 값 | 상태 |
|---|---|---|
| Dataset ID | `71748` | confirmed |
| 공식 endpoint | `dataSetSn=71748` | confirmed |
| 로컬 manifest 명칭 | 한국어 성능이 개선된 초거대AI 언어모델 개발 및 데이터 | repository-recorded |
| 일반 말뭉치 component | 대규모 구매도서 기반 한국어 말뭉치 데이터 | repository-recorded |
| 제공 목적 | 한국어 초거대 AI 언어모델 개발·성능 개선용 데이터 제공 | repository-recorded; 공식 상세 재확인 필요 |
| 구성 | 일반 말뭉치와 RLHF 계열 SFT·RM·PPO | local inventory confirmed |
| 공개 version | null | `verification_required` |
| 갱신일 | null | `verification_required` |
| 데이터 이용 신청 | 취득 당시 신청·승인 증빙 미발견 | `evidence_not_found_locally` |
| 로컬 package | ZIP 55개, checksum inventory 보유 | confirmed, `downloaded_restricted` |

상세 페이지 title과 로컬 manifest 명칭의 정확한 일치, 공개 version과 갱신일은 공식 page snapshot 또는 제공자
증빙을 확보하기 전 확정하지 않는다.

## 5. Component별 SFT 관련성

| Component | 구조적 역할 | 이번 범위 | 승인 상태 |
|---|---|---|---|
| 일반 말뭉치 | Base/CPT용 원문 corpus | excluded | SFT `not_approved` |
| `SFTdata` | instruction/question source 후보 | terms·validation candidate | `not_approved` |
| `SFTlabel` | answer target 후보 | terms·validation candidate | `not_approved` |
| `RMdata`/`RMlabel` | reward/preference 후보 | excluded | `not_approved` |
| `PPOdata` | alignment/PPO 후보 | excluded | `not_approved` |

Tokenizer Development에서 승인된 일반 Training `contents` 사용은 SFT component 사용 승인으로 전이되지 않는다.

## 6. 승인 상태

```yaml
AIHUB_71748:
  download_authorization: evidence_not_found_locally
  local_possession: confirmed
  general_package_status: approved_student_noncommercial
  student_noncommercial_use: conditionally_supported
  sft_component_status: not_approved
  sft_training_use: not_approved
  raw_redistribution: not_approved
  processed_redistribution: not_approved
  checkpoint_publication: not_approved
  model_weight_publication: not_approved
  commercial_use: not_planned
```

`conditionally_supported`는 사용자 결정에 따른 프로젝트 내부 제한 상태다. 제공자의 SFT 목적 승인, 다운로드
승인 증빙 또는 법률 자문을 의미하지 않는다.

## 7. Verification required

다음은 공식 증빙 또는 책임자 확인 전 확정하지 않는다.

1. 취득 당시 계정, 신청 ID, 승인 일시, 제출 목적과 적용 약관 snapshot.
2. Dataset 71748의 제공자 version, 갱신일과 현재 로컬 ZIP 55개의 대응 관계.
3. `SFTdata`/`SFTlabel`을 학생·비상업 SFT에 사용할 수 있는지 여부.
4. 구매도서와 복수 source·CCL별 학습·파생물·암기 재현 제한.
5. 정제·필터·SFT 직렬화 데이터의 로컬 저장과 재배포 조건.
6. checkpoint, model weight, tokenizer, metrics와 sample 공개 조건.
7. 논문·프로젝트 보고서의 정확한 출처 표시 문구.
8. 국외 cloud, 외부 SaaS, 외국 사용자 접근과 반출 조건.

## 8. 승인 요청에 필요한 증거

- 다운로드 승인 화면 또는 제공자 발급 기록의 비공개 보관 위치와 checksum.
- 취득 당시 이용조건 snapshot 또는 AI Hub/NIA의 서면 답변.
- source/CCL별 component inventory와 권리 매핑.
- 학생·비상업 SFT 목적, 보관 위치, 접근자, 폐기·사고 대응 계획.
- 공개하지 않을 artifact 범위와 생성 결과 원문 재현 대응 정책.
- [SFT 검증 계획](./aihub-71748-sft-validation-plan.md)의 모든 scan에 대한 별도 사용자 승인.

## 9. 최종 판정

```yaml
terms_review: verification_required
dataset_selection: not_selected
dataset_processing: not_approved
sft_training: not_approved
publication: not_approved
execution_allowed: false
```

공식 공통 정책은 연구·개발 활용 가능성을 뒷받침하지만, SFT component와 파생 artifact의 목적별 조건 및 취득
증빙이 부족하다. 따라서 AIHUB-71748 SFT 사용을 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | AIHUB-71748 공통 정책·상세 identity·취득 증빙·SFT 및 공개 조건을 분리하고 미확정 항목을 Fail Closed로 기록 |
