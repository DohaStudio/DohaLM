# Common DatasetVersion·DatasetManifest publication 구현 계획

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-12
- 계획 상태: `PLAN_ONLY`
- 구현 상태: `NOT_IMPLEMENTED`
- consumer 상태: `NOT_ACTIVATED`
- Training 권한: `TRAINING_NOT_AUTHORIZED`
- 기준 결정: [ADR-014](../decisions/ADR-014-dataset-product-governance-boundary.md),
  [ADR-015](../decisions/ADR-015-dataset-version-publication-contract.md)
- 권위 기준: `DohaStudio/.github@dd75fc88c16e9ae9a04acfafb72756a905f6365b`
- 권위 tree: `217ed885d2555d753c785cd00df1c836a52095c3`
- package / namespace / policy: `dohastudio-common-ai-contracts==0.1.0` /
  `dohastudio_common_ai` / `1.0.0`

## 1. 목적과 범위

[확정] 이 문서는 병합된 ADR-015의 `DatasetVersion`·`DatasetManifest` publication 계약을 현재 DohaLM 코드의
실재 symbol과 테스트 seam에 매핑하고, 구현을 독립 검증 가능한 최소 PR로 분해한다. 새 Architecture Decision이 아니며
ADR-014·015의 상태와 review date를 변경하지 않는다. ADR-015가 implementation 진입 Gate로 남긴 persistence 세부를 기존
single-unit·no-replace invariant 안에서 고정한다.

[확정] 이번 계획은 Python 구현, dependency 변경, Common 객체 발행, legacy migration, consumer 활성화와
Training/Evaluation을 수행하지 않는다. 미래 파일·module·함수·class·table 이름은 구현자가 확정한 것처럼 만들지 않는다.
신규 symbol은 아래 표에서 역할과 허용 layer만 표시하고 이름은 해당 구현 PR의 첫 검증 Gate에서 정한다.

## 2. 고정 기준과 Common 계약

| 항목 | 고정값 |
|---|---|
| DohaLM 기준 commit / tree | `7136b348133d244d794b2e498fc97294c185f649` / `aa92f698bd04a687245f47e87f83bda2ba66d5b4` |
| Authority commit / tree | `dd75fc88c16e9ae9a04acfafb72756a905f6365b` / `217ed885d2555d753c785cd00df1c836a52095c3` |
| DatasetVersion `$id` | `https://schemas.dohastudio.org/common-ai/v1/dataset-version.schema.json` |
| DatasetManifest `$id` | `https://schemas.dohastudio.org/common-ai/v1/dataset-manifest.schema.json` |
| public API | `get_schema`, `validate_contract`, `validate_scenario`, `contract_policy_version`, `build_registry` |
| lifecycle | DatasetVersion `approved` → DatasetManifest `issued` → DatasetVersion `frozen` |
| 외부 관찰 단위 | 검증된 Version/Manifest pair의 단일 no-replace publication unit |

[확정] `DatasetVersion.status`의 실제 enum은 `draft`, `reviewing`, `approved`, `frozen`, `retired`다.
“Manifest Issued”는 DatasetVersion enum이 아니라 `DatasetManifest.manifest_status == "issued"`인 논리 단계다.
`DatasetManifest.manifest_status`의 실제 enum은 `draft`, `issued`다.

[확정] 지원하지 않는 package·policy·schema version, unknown core field와 enum 확장은 fail closed한다. `$id`는
network endpoint가 아니며 Runtime network lookup은 0이어야 한다.

## 3. 현재 코드 근거와 symbol 분류

| 분류 | 파일과 qualified symbol | 현재 caller → callee | 현재 side effect·Owner | 판정과 재사용 조건 |
|---|---|---|---|---|
| `EXISTING_REUSABLE` | `src.data.artifacts._rename_directory_no_replace()` | `AtomicArtifactDirectory.publish()` → OS rename | 동일 parent의 staging directory를 기존 destination 교체 없이 rename; Data 영역 | local filesystem no-replace capability로 재사용 가능. Common identity·validation·retry 의미는 갖지 않음 |
| `EXISTING_REQUIRES_ADAPTER` | `src.data.artifacts.AtomicArtifactDirectory` | `src.data.pipeline._run()` 및 여러 legacy producer → context manager → `_rename_directory_no_replace()` | hidden staging 생성, 단일 directory publish, 예외 시 staging 삭제; Data 영역 | Publication v1 local filesystem primitive로 채택. Common layout·flush·replay·sanitized failure adapter 필요 |
| `EXISTING_REQUIRES_ADAPTER` | `src.data.pipeline.validate_pipeline()`, `build_pipeline()`, `_run()` | CLI/tests → `_run()` → discovery·read·domain validation·artifact write | legacy corpus read·정제·split·`source-manifest.json` 생성·directory publish; Data 영역 | domain validation·검증 순서 참고만 가능. Common producer 또는 Common payload source로 승격 금지 |
| `EXISTING_REUSABLE` | `src.data.checksums.checksum_value()`, `file_checksum()` | data/training code → canonical value/file checksum | deterministic checksum 계산; Data 영역 | artifact/domain fingerprint 재검증에 사용 가능. Common object identity 계산 규칙을 자동 결정하지 않음 |
| `NOT_A_COMMON_BOUNDARY` | `src.data.config.DataConfig.dataset_version` | config loader → pipeline output path/legacy manifest | legacy 문자열 identity와 path segment | Common DatasetVersion ID·payload·lifecycle이 아님 |
| `NOT_A_COMMON_BOUNDARY` | `src.data.tokenized_dataset.TokenizedJsonlDataset` | training/evaluation backend → JSONL reader | 파일 존재·record shape/token 범위를 확인하고 Dataset reader 생성 | Common validation·pair 조회·permission 판정이 없음. consumer Gate 통과 뒤에만 호출 가능 |
| `EXISTING_REQUIRES_ADAPTER` | `src.training.full_pretraining.inspect_full_pretraining_readiness()` | script/backend dry-run → config·legacy approval·lineage·storage 검사 | domain readiness를 read-only로 검사; Training 영역 | Common pair Gate 뒤의 DohaLM readiness 단계로 유지. Common 성공을 대신하지 않음 |
| `EXISTING_REQUIRES_ADAPTER` | `src.training.full_pretraining.require_full_pretraining_approval()` | `run_full_pretraining()` → execution 허용 검사 | 불허 report에 `TrainingError`; Training 영역 | 마지막 domain permission Gate의 일부로 유지. Common pair 검증만으로 통과시킬 수 없음 |
| `OUT_OF_SCOPE` | `src.training.full_pretraining_backend.run_full_pretraining()` | 실행 entry → readiness → Dataset reader·dataloader·Trainer | Dataset·Tokenizer·Model 구성과 Training 시작 | activation PR의 독립 승인 전 변경·실행 금지. 미래 consumer의 최종 caller 후보일 뿐임 |
| `NOT_A_COMMON_BOUNDARY` | `src.data.processing.output_writer.write_atomic_outputs()` | SFT processing backend → fixed `.staging` → `os.replace()` | SFT package artifact publish·failed package 보존 | replace 허용과 별도 lifecycle 때문에 Common no-replace pair transaction으로 재사용 금지 |
| `NOT_A_COMMON_BOUNDARY` | `src.data.processing.runtime_request_artifact._publish_no_replace()` | runtime request writer → single-file hard-link publish | 단일 request artifact create-if-absent | Version/Manifest pair 동시 visibility를 제공하지 않음 |
| `OUT_OF_SCOPE` | `src.training.qlora_training._rename_directory_no_replace()` | QLoRA staging/failure flow | QLoRA artifact 이동 | Training-specific duplicate primitive이며 Dataset publication에 연결하지 않음 |
| `NEW_REQUIRED` | Dataset Governance 역할, 이름 미확정 (`src/data` 허용 layer) | 승인된 외부 candidate/evidence 입력 → proposal/domain validation/approval 결과 | in-memory proposal·identity/fingerprint·approval 전이; Dataset Governance Owner | 실제 module/function 이름은 구현 PR에서 import graph와 tests를 함께 제시한 뒤 확정 |
| `NEW_REQUIRED` | Common validation adapter 역할, 이름 미확정 (`src/data` 허용 layer) | Governance/Publication/consumer → package root public API | payload mutation 없이 schema·scenario issue를 sanitized domain error로 변환 | private API·schema path 접근 금지, policy mismatch fail closed |
| `NEW_REQUIRED` | Dataset Publication 역할, 이름 미확정 (`src/data` 허용 layer) | approved Version 명시 인자 → Manifest/frozen Version staging → commit | pair staging·validation·single publication·cleanup·retry; Dataset Publication Owner | 확정된 local primitive를 adapter로 사용하고 transaction owner를 구현 evidence로 검증 |
| `NEW_REQUIRED` | training-entry pair Gate 역할, 이름 미확정 (`src/training` 허용 layer) | explicit frozen Version/issued Manifest pair → Common/domain permission result | read-only validation; Training entry Owner | reader·model 생성 전에 호출. 구현 PR과 활성화 PR 분리 |

[확정] 저장소에는 Common publication용 transaction 또는 unit-of-work abstraction이 없다. 위 `NEW_REQUIRED` 역할은
실재하지 않는 이름을 숨겨 확정하지 않으며, 기존 symbol을 Common boundary로 자동 승격하지 않는다.

## 4. Common dependency 도입 경계

1. [제안] 최초 implementation PR에서 `pyproject.toml`의 runtime dependency와 `requirements.txt`의 direct runtime
   dependency에 동일한 exact pin `dohastudio-common-ai-contracts==0.1.0`을 선언한다. 현재 lockfile은 없다.
2. [확정] 모든 production·test 호출은 `dohastudio_common_ai` namespace root의 public API만 import한다. authority schema,
   fixture, validator private symbol과 resource path를 복제하거나 직접 읽지 않는다.
3. [확정] authority source checkout의 `PYTHONPATH=src` import는 package version을 읽을 수 있지만 force-included
   `dohastudio_common_ai/resources/v1`이 없어 resource API가 실패한다. runtime과 test는 동일하게 설치된 built wheel을
   사용하고, wheel 내부 resource·offline `$ref` resolution을 검증한다.
4. [제안] adapter는 import 시점 또는 첫 validation 전에 package version `0.1.0`, policy `1.0.0`, 두 schema `$id`와
   expected kind를 확인하고 불일치 시 artifact read·staging·domain transition 이전에 fail closed한다.
5. [확정] dependency·adapter PR은 producer 또는 consumer를 활성화하지 않는다. activation은 마지막 별도 PR과 독립 승인까지
   금지한다.

## 5. 승인된 validation 순서

| 순서 | 입력 | 처리와 output | side effect / 실패 계약 | transaction owner 후보 |
|---|---|---|---|---|
| 1 | configured immutable pin | package·policy·schema identity 확인 | 불일치 시 후속 호출 0 | Common adapter 역할 |
| 2 | in-memory DatasetVersion proposal | `validate_contract(payload, "dataset_version")` | payload mutation 0, artifact 접근 0 | Dataset Governance 역할 |
| 3 | Common-valid proposal와 upstream evidence | eligibility·rights·approval·split·lineage·Tokenizer compatibility domain validation | non-pass 시 approval·staging 0 | Dataset Governance 역할 |
| 4 | domain-valid proposal | `status="approved"`, immutable identity/fingerprint와 approval evidence 결속 | 외부 publication·Training 허용 0 | Dataset Governance 역할 |
| 5 | approved Version와 검증 대상 artifact metadata | Manifest draft와 issued Manifest/frozen Version candidate를 같은 staging unit에 구성 | staging 밖 visibility 0 | Dataset Publication 역할 |
| 6 | staged pair | 각각 `validate_contract()` | 한 객체 실패 시 scenario·artifact validation·commit 0 | Dataset Publication 역할 |
| 7 | pair와 required upstream objects, `evaluated_at` | `validate_scenario()` | issue가 하나라도 있으면 domain artifact read·commit 0 | Dataset Publication 역할 |
| 8 | Common-valid staged pair | 실제 artifact bytes/checksum set/item count/split/storage collision domain validation | 실패 시 commit 0, cleanup 수행 | Dataset Publication 역할 |
| 9 | 모든 validation이 끝난 pair | single no-replace external commit | 둘 다 동시에 관찰되거나 둘 다 관찰되지 않음 | Dataset Publication 역할 |

## 6. Producer boundary

### 6.1 Dataset Governance

- input 후보: 승인된 upstream Common object의 immutable copy, 목적, Dataset composition과 split proposal,
  현재 `evaluated_at`, DohaLM domain policy.
- output 후보: Common-valid DatasetVersion proposal, domain validation report, approved DatasetVersion candidate와
  immutable identity/fingerprint.
- side effect: 최종 publication 없음. approval 기록 방식은 persistence seam과 함께 후속 PR에서 검증한다.
- failure: evidence 누락·expiry·revocation·rights non-pass·split leakage·identity 충돌 시 fail closed하고 Publication 호출 0.
- Owner: DohaLM Dataset Governance.

### 6.2 Dataset Publication

- input 후보: Governance caller가 명시 인자로 전달하는 immutable `ApprovedDatasetVersion`, immutable artifact
  metadata/checksum set, authority pin. 별도 approval persistence·lookup은 만들지 않는다.
- output 후보: externally observable frozen DatasetVersion와 issued DatasetManifest pair, 또는 sanitized 실패 결과.
- side effect: 같은 transaction unit의 staging, 최종 no-replace commit, 실패 cleanup만 허용한다.
- failure: Version/Manifest/schema/scenario/artifact/collision 실패 시 partial publication 0. cleanup 실패는 원래 실패를
  성공으로 바꾸지 않고 별도 sanitized evidence로 남긴다.
- Owner: DohaLM Dataset Publication. 이 역할이 issuance·freeze의 유일한 transaction owner다.

[확정] 두 역할은 책임상 분리되지만 Version approval output을 Publication input으로 전달하는 immutable seam이 필요하다.
하나의 함수나 module로 합칠지는 결정하지 않는다. 외부 atomicity의 owner만 Dataset Publication으로 고정한다.

## 7. Transaction seam과 atomicity 판정

| 후보 | atomic visibility | no-replace | pair 동시 관찰 | crash/cleanup | concurrency·retry | platform/backend | 판정 |
|---|---|---|---|---|---|---|---|
| `AtomicArtifactDirectory` | 동일 parent에서 directory entry 하나 | Windows `os.rename`, Linux `renameat2(RENAME_NOREPLACE)` | 고정된 Version·Manifest 두 파일을 같은 directory에 넣어 가능 | Python 예외는 `__exit__` cleanup; process crash orphan은 비가시 상태로 남음 | destination race test 존재; replay lookup은 adapter에서 신규 구현 | Windows/Linux local filesystem, 그 외 OS `ENOTSUP` | `ADOPTED_REQUIRES_ADAPTER` |
| `write_atomic_outputs()` | SFT directory 하나 | `os.replace`로 기존 대상 교체 가능 | Common pair 의미 없음 | `.failed` compensation | Common identity retry 없음 | local filesystem | `NOT_A_COMMON_BOUNDARY` |
| `_publish_no_replace()` | file 하나 | hard-link create-if-absent | pair 동시 visibility 없음 | temporary file cleanup | single-file collision만 처리 | filesystem/link 제약 | `NOT_A_COMMON_BOUNDARY` |
| DB/object store | 현재 구현 없음 | 근거 없음 | 근거 없음 | 근거 없음 | 근거 없음 | 미결정 | 발명 금지 |

[판정] Publication v1은 `AtomicArtifactDirectory`를 local filesystem persistence primitive로 채택한다. 단일 directory
visibility와 no-replace 동작으로 Version/Manifest pair를 한 commit candidate로 구성하며 DB·object store·network filesystem,
distributed lock·CAS는 범위 밖이다. 따라서 `BLOCKED_BY_PERSISTENCE_DECISION`과 `BLOCKED_BY_TRANSACTION_SEAM`은 해소됐다.

### 7.1 Publication v1 storage protocol

| 항목 | 고정 계약 |
|---|---|
| root | pinned Authority repository의 proposed Storage Layout이 제안하는 `DohaData/{domain}` 책임과 정합하게 환경별로 주입되는 local filesystem root. 절대 경로 노출·payload 저장 0 |
| logical identity | 기존 `DatasetVersionIdentity(object_id, dataset_id, dataset_version)` |
| storage key | `checksum_value({"dataset_id": dataset_id, "dataset_version": dataset_version, "object_id": object_id})`의 `sha256:` 뒤 64자리 lowercase hex |
| visibility unit | storage key 이름의 final directory 하나. raw ID path 해석 0 |
| private layout | canonical `dataset-version.json`, canonical `dataset-manifest.json` 두 파일만 허용 |
| pair fingerprint | `checksum_value({"dataset_manifest": issued_manifest_payload, "dataset_version": frozen_version_payload})` |
| staging | final과 동일 parent의 호출별 hidden sibling; staging path는 해당 호출만 소유 |
| commit | 두 파일 close·지원 file flush·검증 뒤 directory no-replace rename 한 번 |
| lookup | logical identity → storage key → 고정 두 파일 strict read; directory scan이나 staging fallback 0 |

[확정] storage key와 pair fingerprint는 기존 `canonical_json_bytes()`·`checksum_value()`의 UTF-8, key sort, compact separator,
trailing LF와 SHA-256 규칙을 재사용한다. pair fingerprint는 Authority payload field가 아니며 Version
`content_fingerprint`·Manifest `manifest_checksum`을 대체하지 않는다. storage protocol 파일명도 Common 외부 계약이 아니다.

### 7.2 Replay·conflict·crash contract

1. final이 없을 때만 새 staging을 만들고 no-replace commit을 시도한다.
2. final이 이미 있거나 concurrent commit에서 패배하면 고정된 두 파일을 읽는다. expected canonical bytes, logical identity와
   pair fingerprint가 모두 같을 때만 기존 immutable pair를 반환하는 idempotent success다.
3. 누락·추가 파일, non-canonical/unreadable bytes, identity는 같지만 Manifest ID·lineage·split·evidence·payload 또는 fingerprint가
   다르면 sanitized conflict/corruption으로 fail closed한다. overwrite·delete·fallback·repair는 하지 않는다.
4. rename 전 exception은 자신의 staging cleanup을 시도한다. cleanup 실패는 원래 실패를 성공으로 바꾸지 않는다.
5. process가 rename 전에 종료되면 final은 없고 orphan staging이 남을 수 있다. consumer와 retry는 staging을 조회·승격하지 않는다.
   rename 뒤 종료되면 complete final을 위 replay 규칙으로 재확인한다.
6. 안전한 stale lifetime 근거가 없으므로 PR 3·4는 시간 기반 자동 cleanup을 구현하지 않는다. liveness와 ownership이 별도로
   증명된 offline 운영 정리는 미래 범위다.
7. 보장 수준은 local filesystem namespace atomicity와 지원되는 file flush다. POSIX parent-directory fsync 실패는 fail closed지만
   Windows directory flush, power-loss durability, network filesystem semantics는 보장하지 않는다.

### 7.3 결정·evidence 책임표

| Decision | Status | 현재 evidence | PR 3 responsibility | PR 4 responsibility |
|---|---|---|---|---|
| persistence primitive | `DECIDED` | `AtomicArtifactDirectory`, `_rename_directory_no_replace()`와 기존 pipeline test | local adapter와 single rename transaction | production 의미 변경 없이 독립 process 검증 |
| atomic visibility unit | `DECIDED` | ADR-015 pair 동시 공개 invariant와 directory-entry seam | 고정 두 파일만 staging·검증·commit | partial final 0 adversarial 검증 |
| publication logical identity | `DECIDED` | `DatasetVersionIdentity`와 Authority Version/Manifest identity invariant | 세 field exact validation | identity collision vector 재검증 |
| final storage key | `DECIDED_PRIVATE_PROTOCOL` | 기존 `checksum_value()` canonical SHA-256와 path injection 금지 | exact digest vector·single component 보장 | unrelated identity collision·path 공격 vector |
| pair fingerprint | `DECIDED_PRIVATE_PROTOCOL` | 기존 canonical JSON helper와 ADR-015 immutable retry 계약 | named-object vector와 Authority checksum field 비변경 test | same identity/different pair conflict 재검증 |
| existing target lookup/replay | `DECIDED` | ADR-015 idempotent retry·overwrite 0 | exact target strict read와 byte-identical replay | restart·concurrent loser replay |
| conflicting retry | `DECIDED` | ADR-015 same identity/different content fail-closed | sanitized conflict, mutation·repair 0 | concurrent conflicting writer winner 보존 |
| staging location/ownership | `DECIDED` | 현재 same-parent random hidden staging과 context ownership | 호출별 sibling staging, own cleanup만 | orphan이 다른 retry/final을 방해하지 않음 증명 |
| crash boundary | `DECIDED_ATOMIC_VISIBILITY` | single directory rename과 no-replace 구현 | pre-rename failure injection, post-rename replay | rename 전/후 process termination |
| stale staging cleanup | `DEFERRED_NOT_BLOCKING` | repository·Authority에 수명 수치 근거 없음 | same-process cleanup, orphan 조회·자동 삭제 0 | orphan 비가시성·restart 검증; TTL 발명 0 |
| durability level | `DECIDED_LIMITED` | POSIX parent fsync, Windows no-op인 현재 source | file flush 실패 fail-closed, power-loss 보장 0 | OS/filesystem과 실제 flush 경로 기록 |
| Windows evidence | `PR4_REQUIRED` | `os.rename` branch와 existing race test | current-host regression만 | Windows process concurrency·termination evidence |
| Linux evidence | `PR4_REQUIRED` | `renameat2(RENAME_NOREPLACE)`·directory fsync branch | implementation을 우회하지 않는 unit seam | Linux process concurrency·termination·fsync-path evidence |
| PR 3 / PR 4 split | `DECIDED` | 기존 최소 PR 분리와 activation 금지 | production transaction·deterministic unit/integration | cross-platform adversarial evidence 전용 |
| approved result delivery | `DECIDED` | immutable in-memory `ApprovedDatasetVersion`와 Governance side-effect 0 | explicit argument, implicit lookup·DB·registry 0 | caller 재구성·restart 입력 경계 확인 |

[검증 필요] publication implementation과 evidence PR은 다음 증거를 나눠 제시한다. 충족하지 못하면 다른 기술을 임의 선택하지
않고 해당 PR을 중단한다.

- pair와 immutable publication identity가 한 visibility unit에 포함됨
- concurrent writer 둘 중 하나만 성공하고 winner bytes가 보존됨
- commit 직전 failure 뒤 partial final 0, same-process cleanup과 orphan 비가시성
- same input replay의 동일 결과와 same ID/different fingerprint 충돌
- PR 4의 Windows·Linux process/concurrency evidence와 정확한 비보장 범위
- local filesystem 이외 backend가 필요해질 경우 별도 decision Gate

## 8. State machine과 immutability

| 논리 단계 | 실제 field | 허용 조건 | 금지 결과 |
|---|---|---|---|
| Proposed | `DatasetVersion.status="draft"` 또는 `"reviewing"` | Common proposal와 domain validation 준비 | approval·Manifest·freeze·publication 0 |
| Approved | `DatasetVersion.status="approved"`, `approved=true` | 집합 eligibility·approval evidence·identity/fingerprint 완전 | issued/frozen 외부 visibility 0 |
| Manifest Issued | `DatasetManifest.manifest_status="issued"` | approved Version ID/checksum과 Manifest source identity 일치 | 아직 Version 단독 외부 노출 0 |
| Frozen | `DatasetVersion.status="frozen"`, `approved=true`, `frozen=true`, `training_allowed=true` | issued Manifest ID와 identity 결속, 모든 validation 완료 | in-place mutation 0 |

[확정] issued Manifest와 frozen Version은 terminal immutable record다. 같은 ID의 bytes, checksum, source reference,
lineage나 결속을 변경하지 않는다. replacement는 새 identity와 authority가 허용하는 `supersedes` lineage를 사용한다.

## 9. Idempotency·concurrency·failure 계약

| case | 예상 계약 | 최소 test level |
|---|---|---|
| same immutable input + same identity/fingerprint replay | 고정 두 파일의 canonical bytes를 확인해 기존 pair 반환; 새 write·overwrite 0 | integration |
| same identity + different fingerprint | sanitized conflict로 fail closed | unit + integration |
| duplicate approval | 동일 approval idempotent 또는 충돌; 새 identity 추정 0 | unit |
| duplicate issuance/freeze | terminal pair 변경 0 | unit + integration |
| concurrent publisher 2개 | 단일 winner, loser conflict, winner bytes 불변 | integration + platform |
| Version validation 실패 | domain validation·approval·staging 호출 0 | unit |
| Manifest validation 실패 | scenario·artifact validation·commit 0 | unit |
| `validate_scenario()` 실패 | artifact validation·commit 0 | unit |
| artifact/domain validation 실패 | final pair 0, staging cleanup | integration |
| staging write 중 실패 | final pair 0, staging cleanup | integration failure injection |
| commit 직전 실패 | final pair 0 | integration failure injection |
| rename 경계 process 종료 | final directory 전체 또는 부재, 파일 단위 partial 관찰 0 | platform/process failure injection |
| cleanup 실패 | publication 성공으로 보정하지 않고 sanitized cleanup failure 기록 | integration |
| crash 후 재시작 | orphan staging 조회·승격·시간 기반 자동 삭제 0; final이 있으면 strict replay, 없으면 새 staging | platform/process |

## 10. Legacy/Common 비승격

[확정] 기존 corpus, `source-manifest.json`, registry entry와 `DataConfig.dataset_version` 문자열은 Common object가 아니다.
다음 금지는 각 producer·consumer PR의 unit test와 integration test에 유지한다.

- wrapping만으로 Common payload로 취급하지 않음
- alias/default/key/type/version 변환이나 누락 evidence 추정 0
- legacy approval/readiness에서 Common approval·freeze 추정 0
- 기존 readiness 통과를 Common validation 통과로 간주하지 않음
- legacy artifact path를 Common reference로 자동 삽입하지 않음

[제외] legacy migration·ingestion·backfill은 `OUT_OF_SCOPE_FUTURE`다. 별도 authority lifecycle과 migration ADR 없이는
이 계획의 어느 PR에도 포함하지 않는다.

## 11. training-entry consumer와 activation 분리

미래 consumer의 순서는 다음과 같으며 각 앞 단계 실패 시 뒤 단계 호출은 0이다.

1. frozen DatasetVersion와 issued DatasetManifest pair를 explicit input으로 조회 또는 주입
2. 두 object의 `validate_contract()`
3. required upstream objects와 `evaluated_at`을 포함한 `validate_scenario()`
4. DohaLM domain/readiness validation
5. immutable artifact identity·checksum 확인
6. 별도 승인 evidence를 포함한 training permission 결정
7. `TokenizedJsonlDataset` 생성
8. dataloader·Model 구성과 Training/Evaluation 시작

[확정] `run_full_pretraining()`의 현재 순서는 `require_full_pretraining_approval()` 뒤에 Dataset reader를 만든다.
미래 pair Gate는 reader 생성 이전이어야 하지만 consumer implementation PR은 호출을 비활성 상태로 유지한다. 별도 activation
PR과 독립 승인 전에는 기존 execution path를 허용 방향으로 변경하지 않는다.

## 12. 최소 implementation PR 순서

### PR 1 — Common dependency와 validation adapter

- 목적: exact pin과 package root public API를 하나의 adapter 역할에 격리한다.
- 허용 layer: `pyproject.toml`, `requirements.txt`, `src/data`, 관련 `tests`; 신규 symbol 이름은 diff 전 Gate에서 확정.
- 선행 Gate: authority commit/tree/package/policy 재검증, built wheel resource layout 확인.
- 계약: payload mutation 0, offline `$ref`, exact expected kind, sanitized deterministic issue, mismatch fail closed.
- transaction owner: 없음.
- 최소 test: pin mismatch, two schema `$id`, DatasetVersion/Manifest valid·invalid, scenario pair, source checkout와 built wheel 차이.
- 회귀 test: dependency install smoke와 기존 data unit tests.
- 금지: producer·staging·artifact read·consumer 연결·Training/Evaluation.
- 완료 evidence: clean wheel install에서 public API만 사용한 test와 network lookup 0.
- 다음 Gate: adapter 독립 검증.

### PR 2 — Dataset Governance domain/state

- 목적: Version proposal, aggregate eligibility/domain validation, approval와 immutable identity/fingerprint를 구현한다.
- 허용 layer: `src/data`, 관련 `tests`; 기존 `pipeline`·`DataConfig`의 Common 승격 금지.
- 정확한 기존 seam: `checksum_value()`, domain validation 관례. 신규 producer symbol 이름은 첫 Gate에서 확정.
- 선행 Gate: PR 1 병합·동일 authority pin.
- 계약: draft/reviewing → approved만 처리하고 Manifest/freeze/publication은 하지 않음.
- transaction owner: 없음; approved candidate는 Publication에 전달할 immutable input.
- 최소 test: validation order, invalid transition, evidence expiry/revoke, split leakage, duplicate approval, fingerprint mutation.
- 회귀 test: `tests/test_data_pipeline.py`, dataset policy tests.
- 금지: staging, final artifact, reader, Model/Provider, Training/Evaluation.
- 완료 evidence: 실패 후 Publication 호출 0과 deterministic approved candidate.
- 다음 Gate: approved candidate contract 독립 검증.

### PR 3 — Dataset Publication staging과 transaction

- 목적: Manifest construction, pair validation, artifact/domain revalidation와 single no-replace commit을 구현한다.
- 허용 layer: `src/data`, 관련 `tests`; `AtomicArtifactDirectory`를 확정 protocol adapter를 통해 재사용.
- 정확한 기존 seam: `AtomicArtifactDirectory`, `_rename_directory_no_replace()`, checksum helpers.
- 선행 Gate: PR 2 병합과 같은 authority pin. 이 문서의 storage key·pair fingerprint·replay·crash 비보장 범위를 test vector로 고정.
- 계약: approved → issued → frozen 논리 순서와 pair 동시 external visibility.
- transaction owner: 새 Dataset Publication 역할 하나.
- 최소 test: individual/scenario/artifact ordering, exact two-file layout, identity/storage-key vector, collision, same-process cleanup,
  idempotent/conflicting retry, terminal immutability, orphan staging 비가시성.
- 회귀 test: atomic directory race와 legacy pipeline publication tests.
- 금지: legacy 변환, consumer 연결, Training/Evaluation.
- 완료 evidence: 지원되는 개발 host에서 no-replace, deterministic replay, injected pre-rename failure와 partial final 0. power-loss
  durability·automatic stale cleanup은 완료 조건이 아니다.
- 다음 Gate: PR 4 독립 failure/concurrency 검증.

### PR 4 — Publication failure·concurrency evidence

- 목적: PR 3의 새 기능을 활성화하지 않고 Windows·Linux adversarial process evidence로 검증한다.
- 허용 layer: tests와 synthetic fixtures, 필요한 test-only failure hook; production 의미 변경은 별도 PR로 되돌림.
- 선행 Gate: PR 3의 exact head와 transaction contract.
- 계약: test matrix의 모든 failure가 partial output·overwrite·추정 없이 fail closed.
- transaction owner: 변경 없음.
- 최소 test: concurrent processes, rename 전/후 process termination, restart replay, orphan staging 무시, cleanup failure. Windows는
  `os.rename` no-replace winner 보존, Linux는 `renameat2(RENAME_NOREPLACE)`와 parent-directory fsync 경로를 각각 실행한다.
- 회귀 test: full data test slice와 platform matrix.
- 금지: 실제 Dataset/Artifact/DB 접근, consumer activation, Training/Evaluation.
- 완료 evidence: Windows·Linux 각각 exact head·OS·filesystem·결과를 기록한 독립 report. namespace atomicity 범위를 넘는
  power-loss durability는 주장하지 않는다.
- 다음 Gate: producer 승인·병합 여부.

### PR 5 — immutable training-entry consumer 구현

- 목적: explicit frozen/issued pair를 검증하고 기존 domain readiness 앞에 read-only permission 결과를 제공한다.
- 허용 layer: `src/training`, adapter의 public surface, 관련 `tests`; 신규 consumer symbol 이름은 첫 Gate에서 확정.
- 정확한 insertion 후보: `run_full_pretraining()`의 Dataset reader 생성 이전, `inspect_full_pretraining_readiness()`와
  `require_full_pretraining_approval()`을 대체하지 않는 별도 Gate.
- 선행 Gate: Publication 구현·evidence 독립 승인.
- 계약: pair 조회/주입 → Common validation → scenario → domain readiness → artifact 확인 순서.
- transaction owner: 없음, read-only consumer.
- 최소 test: non-frozen/non-issued/mismatched pair, pin mismatch, artifact mismatch, reader/model/training 호출 0.
- 회귀 test: full-pretraining readiness/backend dry-run tests.
- 금지: 실행 path 활성화, permission default true, actual Training/Evaluation.
- 완료 evidence: consumer는 명시 주입 없이는 fail closed하고 기존 execution을 허용하지 않음.
- 다음 Gate: 독립 consumer 검증과 별도 activation 승인.

### PR 6 — consumer activation evidence와 독립 승인

- 목적: 승인된 exact consumer head만 training-entry에 연결하고 활성화 여부를 별도 결정한다.
- 허용 layer: 최소 orchestration·tests·승인 문서; activation 승인에 명시된 범위만.
- 선행 Gate: PR 5 독립 검증, immutable pair 실제 publication evidence, 별도 사용자 승인.
- 계약: 모든 Gate 뒤에만 Dataset reader를 생성하며 Common 성공만으로 Training을 허용하지 않음.
- transaction owner: 없음.
- 최소 test: end-to-end synthetic call ordering, 모든 앞 단계 failure에서 Dataset/Model/Provider/Training/Evaluation 0.
- 회귀 test: full-pretraining readiness/backend와 승인 소비 test.
- 금지: 승인 없는 Training/Evaluation, 자동 fallback, legacy ingestion.
- 완료 evidence: activation decision, exact head, synthetic evidence와 independent review.
- 다음 Gate: 별도 Training execution 승인. 이 PR 자체가 Training 권한은 아님.

## 13. Test와 failure-injection 위치

| level | 실제 관례와 후보 위치 | 계획 항목 |
|---|---|---|
| unit | `tests/`의 source module 대응 test 관례; 신규 파일명은 구현 symbol 확정 뒤 결정 | adapter, schema, lifecycle, immutability, validation order, legacy non-promotion |
| integration | `tests/test_data_pipeline.py`, `tests/test_full_pretraining_readiness.py`, `tests/test_full_pretraining_backend.py`의 tmp path·monkeypatch 관례 | staging, cleanup, pair visibility, downstream call 0, consumer ordering |
| concurrency/process | 신규 synthetic test module, 이름 미확정 | two publishers, crash/restart, commit boundary failure |
| Windows platform | PR 4의 Windows CI 또는 독립 evidence 환경 | `os.rename` no-replace race, pre/post-rename process 종료, orphan 비가시성, replay |
| Linux platform | PR 4의 Linux CI 또는 독립 evidence 환경 | `renameat2(RENAME_NOREPLACE)`, directory fsync 경로, pre/post-rename process 종료, replay |

[확정] fixture는 합성 Common object만 사용하고 실제 dataset, 사용자 evidence, 원문·path를 포함하지 않는다. Authority fixture를
private path로 import하지 않고 public API와 consumer-owned synthetic payload를 사용한다.

## 14. 보안·비노출과 side-effect Gate

- 외부 API·로그·오류에는 credential, raw path, storage root, raw exception/stack trace와 Provider response를 포함하지 않는다.
- Common issue는 code·object identity·sanitized field context만 domain error로 변환한다.
- payload와 evidence의 key/value/type/schema version을 validation 전후 변경하지 않는다.
- validation 실패 시 actual DB, Dataset, Artifact, Model, Provider 접근과 Training/Evaluation 호출은 0이다.
- fixture와 결과에는 private absolute/package path를 기록하지 않는다.

## 15. 미결정과 명시적 제외

- [검증 필요] 신규 module/function/class 이름과 import surface
- [검증 필요] Windows/Linux platform evidence를 실행할 CI 또는 독립 환경
- [검증 필요] power-loss durability 또는 network filesystem·DB·object store가 실제 요구될 경우 별도 decision
- [검증 필요] process-crash orphan을 삭제해야 하는 운영 요구와 liveness·ownership 증명 방식
- [검증 필요] revoke·supersede event의 운영 persistence와 조회 방식
- [제외] RightsEvidence·ConsentEvidence·ReviewEvidence라는 authority 비존재 resource 생성
- [제외] DohaMusic·Authority 변경과 cross-repository transport 구현
- [제외] legacy migration·ingestion·backfill
- [제외] consumer activation, Dataset/Artifact/Model/Provider 접근과 Training/Evaluation 실행

이 미결정은 PR 3의 local filesystem implementation 진입을 막지 않으며 ADR-015의 resource set이나 atomic publication
invariant를 되돌리지 않는다. 확정된 local primitive가 지원 filesystem에서 single unit을 증명하지 못하거나 외부 backend가
실제로 필요해지면 PR 3을 중단하고 추가 decision 필요성을 보고한다.

## 16. 완료 Gate

이 계획 문서의 완료는 다음만 의미한다.

- 실제 기존 symbol과 Common이 아닌 경계를 확인함
- 새 역할의 owner·input/output·failure·side-effect와 검증 순서를 분해함
- transaction seam 후보와 증거 부족을 구분함
- Publication v1 persistence·identity·replay·crash·durability 경계를 고정함
- 각 implementation PR의 선행 Gate·완료 evidence·금지 side effect를 정의함

`PLAN_ONLY`, `NOT_IMPLEMENTED`, `NOT_ACTIVATED`, `TRAINING_NOT_AUTHORIZED`는 이 계획이 병합돼도 유지된다. 첫 구현 PR은
이 문서의 독립 검증과 병합 뒤에만 시작한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-12 | [제안] local directory primitive, storage protocol, replay·crash 경계와 PR 3/4 evidence 분리 확정 |
| 2026-08-12 | [제안] ADR-015를 실제 DohaLM symbol, transaction seam, 최소 implementation PR과 evidence Gate로 분해 |
