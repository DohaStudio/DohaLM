# ADR-036: Existing AIHUB material의 current-use Rights authority

- 문서 상태: `approved`
- 마지막 검토일: 2026-09-01
- 결정 상태: `approved`
- 실행 영향: DohaRights current-use record와 DohaLM Common RightsMetadata projection, Candidate A production artifact
  rebuild를 승인한다. Dataset publication과 Training은 승인하지 않는다.
- 기준 DohaLM commit: `aa96b8a000a6d6170f6b24c51feb8b9d02fe7650`
- 기준 DohaLM tree: `8056d40439da59710bdc663e20c0ec95042332f7`
- 기준 DohaRights commit: `b697eda5ee8deee2dcc9c3be4b4afc730b72232d`
- 선행 결정: [ADR-034](./ADR-034-cross-repository-rights-authority-and-current-evidence-snapshot.md),
  [ADR-035](./ADR-035-candidate-a-product-dataset-provenance-and-producer-policy.md)
- 승인 근거: 2026-09-01 사용자 `DDORINY`의 Existing AIHUB Dataset Current-Use Rights Authority
  Remediation 명시 요청

## Context

[현재] AIHUB-71748의 55개 ZIP, 17,256,335,769 bytes와 107,226개 canonical Training record는 local Dataset
repository에서 checksum·lineage가 검증되어 있다. 과거 다운로드 신청 ID·승인 receipt·당시 terms snapshot은 복구되지 않았다.
이 역사 사실을 합성하거나 현재 authority로 가장하지 않는다.

[현재] 2026-09-01에 다시 읽은 AI 허브 공식 [데이터 이용정책](https://aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105)은
AI데이터를 AI 학습모델 학습용으로 이용할 수 있다고 설명하고, 제3자 제공·국외 반출·Dataset 상업적 이용을 제한한다. 별도
본인 확인·목적 제출 절차는 AI 허브를 통한 다운로드 방법으로 설명한다. 공식
[FAQ](https://www.aihub.or.kr/aihubnews/faq/list.do)는 승인 이력이 사라진 이용자가 다시 다운로드하려는 경우 인증 후 신청하도록
안내한다. 두 문서와 Dataset [71748 현재 페이지](https://www.aihub.or.kr/aihubdata/data/view.do?currMenu=115&dataSetSn=71748&topMenu=100)에는
이미 합법적으로 보유하고 byte integrity가 검증된 material을 internal local 학습에 계속 이용하기 위해 반드시 재다운로드해야 한다는
명시 조건이 확인되지 않았다.

이 판단은 코드가 표현하는 현재 운영 범위의 evidence review이며 법률 자문이 아니다. provider가 이용 중지·환수·폐기를 요구하거나
정책이 바뀌면 current record를 supersede 또는 revoke하고 rebuild·publication·Training을 중단한다.

## Decision

```text
CURRENT_USE_AUTHORIZATION = PASS
FRESH_DOWNLOAD_REQUIRED = NO
EXISTING_BYTES_REUSED = YES
HISTORICAL_ACQUISITION_RECEIPT = NOT_RECOVERED
HISTORICAL_ACQUISITION_RECEIPT_USED_AS_CURRENT_AUTHORITY = NO
HISTORICAL_PACKAGE_CLASSIFICATION = EXISTING_VERIFIED_PACKAGE_CURRENT_USE_AUTHORIZED
```

이 결정은 AIHUB-71748 exact source identity와 `internal_noncommercial_model_training_and_evaluation`에만 실제 활성화한다.
DohaRights contract는 다른 verified external Dataset도 동일한 fact model로 표현할 수 있지만 다른 local Dataset의 record는 이
작업에서 발행하지 않는다.

## Canonical Rights facts

canonical owner는 DohaRights다. immutable current-use record와 SourceToken fingerprint는 다음 사실을 모두 포함한다.

- stable source-authority UUID, source Dataset subject UUID, `dataset_source_identity=AIHUB-71748`
- `subject_kind=source_dataset`, `bound_identity=AIHUB-71748`
- source classification `external`, status `approved_limited`
- analysis·internal Training·derivative generation `true`
- commercial use·redistribution·external model publication `false`
- retention `indefinite_while_current / training`; 임의 2099 expiry 금지
- consent evidence `[]`; provider policy·Dataset metadata·source integrity·lineage는 typed evidence로 분리
- jurisdiction `KR`
- current review timestamp와 서로 다른 producer/reviewer authority UUID
- historical receipt `not_recovered`, fresh acquisition required `false`, existing material reuse `true`

`indefinite_while_current`는 영구적·취소 불가능한 권리를 뜻하지 않는다. Common v1에는 `retention_allowed=true`로 투영하며,
owner record의 supersede/revoke 또는 token currentness 실패가 즉시 우선한다. consent가 legal basis가 아닌 external provider Dataset은
`consent_evidence_refs=[]`와 typed policy evidence를 함께 사용한다. license evidence를 consent로 가장하지 않는다.

## DohaLM projection과 consumer contract

DohaLM은 authenticated DohaRights read function의 payload만 `RightsReadModel`로 읽고 Common RightsMetadata를 deterministic하게
materialize한다. eligibility manifest, filesystem, historical artifact 또는 caller override는 Rights fallback이 아니다. source UUID,
subject·binding, current token, required fact 또는 typed evidence가 없거나 producer/reviewer UUID가 충돌하면 fail closed한다.

LearningCandidate review·DatasetInclusionHandoff consumer는 Common schema가 허용하는 indefinite boolean retention과 empty consent
references를 받아들인다. empty consent는 external/reference source, `consent_basis=not_applicable`, current-use authorization과 non-empty
typed evidence가 모두 검증될 때만 허용한다.

candidate-specific TrainingEligibility는 current Rights·source membership 검토 시점부터 24시간 유효한
`candidate-a-current-review-24h-v1` operational window를 사용한다. 이는 legal Rights expiry가 아니며 만료 후 재검토·재발행해야 한다.

## Rebuild boundary

ADR-035의 member·group·split 결정을 변경하지 않는다. production rebuild는 실제 record-level LearningCandidate, ACCEPTED review,
DatasetInclusionHandoff와 ProductDatasetComposition을 만들고 `production-v1` train/validation/test artifact와 manifests를 원자적으로
완성한다. synthetic provenance는 0이어야 한다.

이 ADR이 승인하지 않는 mutation은 다음과 같다.

- actual Dataset publication
- Training intent·journal·Host·backend·Training workload
- C1·C2·C3 또는 ruleset 변경
- commercial use, Dataset redistribution, external model publication

## Revalidation triggers

- AI 허브 이용정책·Dataset 71748 metadata 또는 provider 요구 변경
- 이용 중지·환수·폐기 요청
- source bytes·checksum·lineage 변경
- DohaRights source authority·subject·record/token currentness 변경
- commercial·redistribution·external publication scope 요청
- retention 또는 consent 의미 변경

