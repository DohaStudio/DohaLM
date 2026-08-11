# Common Dataset Contract adapter

- 문서 상태: `implemented`
- 마지막 검토일: 2026-08-12

## 경계

[확정] `src.data.common_dataset_contracts`는 Common AI Contract의 `DatasetVersion`,
`DatasetManifest`, 두 객체의 publication scenario를 검증하는 최소 소비자 경계다.
Dataset 생성, governance 판정, 저장, publication transaction, training activation은 이
adapter의 책임이 아니다.

## 불변 dependency와 API

[확정] 배포 dependency는 `dohastudio-common-ai-contracts==0.1.0`, 실행 policy는
`1.0.0`, Dataset schema ID는 Common Contract v1의 canonical ID로 고정한다. Adapter는
설치된 package namespace root의 `get_schema`, `validate_contract`, `validate_scenario`,
`contract_policy_version`, `build_registry`만 사용한다. schema 파일을 복제하거나 package
내부 경로를 탐색하지 않는다.

## Fail-closed 동작

[확정] package·policy·schema ID·offline registry가 기대값과 다르면
`CommonContractRuntimeError`를 발생시킨다. 객체 또는 scenario가 유효하지 않으면
`CommonDatasetValidationError`를 발생시킨다. 성공 시 입력 객체를 변형하지 않고 그대로
반환한다. 오류에는 고정 error code와 정제된 JSON path만 포함하며 raw payload, 내부
filesystem path, secret, authority 내부 예외 메시지는 노출하지 않는다.

[확정] frozen `DatasetVersion`과 issued `DatasetManifest`의 상호 identity는 두 객체를 한
scenario에 넣어 `validate_dataset_publication_scenario`로 검사해야 한다. 개별 schema 검증은
상호 identity 검증을 대신하지 않는다.
