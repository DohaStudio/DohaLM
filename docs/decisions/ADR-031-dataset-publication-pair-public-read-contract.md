# ADR-031: Dataset Publication Pair public read 계약

- 문서 상태: `draft`
- 마지막 검토일: 2026-08-26
- 결정 상태: `proposed`
- 실행 영향: 없음; public Python/library read port 설계만 제안
- 기준 DohaLM commit: `733f93fca5176aaad343b1018b053076446495ff`
- 기준 DohaLM tree: `51ba5899901ab73e7a4dd2266de35caa2c8b4352`
- 선행 ADR: [ADR-015](./ADR-015-dataset-version-publication-contract.md),
  [ADR-026](./ADR-026-dataset-review-authority-contract.md),
  [ADR-027](./ADR-027-dataset-governance-production-prerequisites.md)
- 관련 문서: [Dataset publication 구현 계획](../data/dataset-publication-implementation-plan.md),
  [제품 지속 학습 경계](../project/ai-music-director-continuous-learning.md)

## Context와 사용자 가치

[현재] Publication v1의 durable authority는 final directory에 함께 commit된 frozen `DatasetVersion`과 issued
`DatasetManifest` pair다. `ApprovedDatasetVersion`, process-local approval result, replay cache, index DB, latest pointer와
mutable projection은 authority가 아니다.

[현재] `publish_dataset_version()`은 새 pair를 commit하거나 같은 command 입력의 replay를 검증할 수 있지만, exact identity만
받아 이미 commit된 pair를 읽는 public query는 없다. process restart 후 확인, operator/library inspection, downstream read,
future runtime read-before-write와 republish 없는 replay/debug에는 command와 분리된 standalone read가 필요하다.

[제안] 최종 Architecture Gate 판정은 `C. NEW PUBLIC READ PORT REQUIRED`이며 implementation readiness는
`READY FOR IMPLEMENTATION`이다. 이 판정은 Python/library 계약만 승인 후보로 만들며 runtime, CLI, API, worker, IAM,
CurrentEvidence 또는 Training activation을 승인하지 않는다.

## Existing publication inventory

| 영역 | 실제 symbol·구조 | 판정 |
|---|---|---|
| command | `src.data.dataset_publication.publish_dataset_version()` | approved candidate에서 pair를 구성·검증·commit/replay |
| command result | `DatasetPublicationResult` | immutable snapshot이지만 `published`가 command outcome 의미 |
| construction | `_validate_pair()`, `_build_manifest()`, `_require_domain_identity()` | Common schema·scenario와 pair binding 검증 |
| fingerprint | `_pair_fingerprint()` | canonical pair projection의 `checksum_value()` |
| storage key | identity 세 field의 `checksum_value()`에서 `sha256:`을 제거한 64자리 lowercase hex | deterministic exact lookup 가능 |
| layout | `<publication_root>/<storage_key>/dataset-version.json`, `dataset-manifest.json` | final directory와 exact 두 파일이 visibility unit |
| serialization | `canonical_json_bytes()`와 exclusive binary write | canonical UTF-8 JSON bytes |
| atomicity | `AtomicArtifactDirectory`, same-parent staging, no-replace directory rename | commit 전 final 부재, commit 후 complete final |
| replay | `_replay()` → `_verify_directory()` | caller가 다시 계산한 expected pair와 persisted pair 비교 |
| process evidence | `tests/test_dataset_publication_process.py` | two-process race, termination boundary, restart corruption 거부 |
| public standalone read | 없음 | 새 query port 필요 |

### Private verifier assumptions

[현재] `_verify_directory(path, expected, version, manifest, scenario)`는 exact file set과 regular file, strict JSON, canonical bytes,
expected bytes equality, pair domain identity, expected pair fingerprint와 persisted scenario를 검증한다. 누락·추가·malformed·
noncanonical file은 corruption이고 같은 identity의 다른 expected bytes는 conflict다.

[현재] 이 verifier는 side-effect를 직접 수행하지 않지만 replay 전용 expected bytes, command가 구성한 Version·Manifest와 upstream
objects를 포함한 scenario를 요구한다. internal path를 받고 mutable mapping을 다루며 filesystem·parse failure를 대부분 하나의
internal corruption code로 접는다. 따라서 rename/export만으로 stable public read가 될 수 없다.

[제안] 후속 구현은 strict JSON, canonical-byte, pair-local validation 같은 side-effect-free primitive를 내부에서 분리해 재사용할
수 있다. public port가 private command verifier의 signature, filename, path 또는 replay-specific argument를 노출해서는 안 된다.

## Exact identity와 deterministic lookup

[제안] lookup identity는 기존 `DatasetVersionIdentity(object_id, dataset_id, dataset_version)` 하나다. Manifest identity,
publication ID와 pair fingerprint는 별도 lookup key가 아니다. final storage key는 ADR-015와 현행 구현의 다음 projection으로만
계산한다.

```text
checksum_value({
  "dataset_id": identity.dataset_id,
  "dataset_version": identity.dataset_version,
  "object_id": identity.object_id,
}).removeprefix("sha256:")
```

[제안] raw filesystem path, directory name, raw ID, Manifest ID, timestamp, list order, mtime와 caller-provided storage key를
authoritative identity로 받지 않는다. exact identity는 root 바로 아래 하나의 deterministic final component를 결정하므로 DB,
index, directory scan 또는 latest pointer가 필요 없다.

[제안] caller는 optional expected pair fingerprint를 integrity assertion으로 전달할 수 있다. 이는 lookup identity나 authority가
아니며, 없더라도 exact identity read는 가능하다. 값이 있으면 recomputed canonical pair fingerprint와 constant semantic equality를
요구하고 mismatch를 별도 typed failure로 반환한다.

## Storage owner와 root boundary

[제안] Dataset Publication module이 pair storage protocol과 read semantics를 소유한다. Product Publication orchestration은
storage verifier나 path layout을 소유하지 않는다. 새 aggregate state store 또는 generic artifact store로 authority를 옮기지 않는다.

[제안] read model은 `DatasetPublicationAuthority` Protocol과 owner-local filesystem adapter다. Protocol의 query는 exact identity와
optional expected fingerprint만 받는다. adapter construction이 explicit `publication_root` capability를 주입받고 private layout을
캡슐화한다. 구체 symbol 이름은 후속 구현에서 repository naming과 충돌 여부를 확인해 고정하되 다음 의미를 유지한다.

```text
DatasetPublicationAuthority.read(identity, *, expected_pair_fingerprint=None)
    -> DatasetPublicationRecord
```

[제안] root는 cwd, repository root, user home, implicit temp, hidden global 또는 environment auto-discovery로 결정하지 않는다.
library adapter에는 explicit dependency로 주입하고, future production composition에서는 ADR-027의 governance runtime config가
소유한다. public request/result/error에는 root나 absolute path를 넣지 않는다.

[제안] library port는 IAM을 발명하지 않는다. adapter를 보유한 filesystem read capability와 business authorization은 분리한다.
future runtime이 어떤 principal에게 이 capability를 제공할지는 별도 activation/IAM 결정이다.

## Read result

[제안] read는 새 immutable `DatasetPublicationRecord` 의미의 DTO를 반환한다. 기존 `DatasetPublicationResult`는
`published: bool`이 new commit 대 replay라는 command outcome을 나타내므로 query 결과로 재사용하지 않는다.

최소 result는 다음만 포함한다.

- exact `DatasetVersionIdentity`
- frozen `DatasetVersion` immutable canonical snapshot
- issued `DatasetManifest` immutable canonical snapshot
- recomputed canonical pair fingerprint

[제안] mapping property가 필요하면 매 접근마다 canonical snapshot을 decode해 caller mutation이 내부 state를 바꾸지 않게 한다.
publication root, storage key, absolute path, private filename, staging path, filesystem handle과 raw credential은 반환하지 않는다.

## Full committed-authority verification

[제안] validation depth는 `FULL DURABLE AUTHORITY VERIFICATION`이다. 여기서 full은 committed pair가 스스로 제공하는 모든
pair-local authority invariant를 뜻한다. historical/current upstream objects를 다시 조회하거나 `validate_scenario()`를 새
`evaluated_at`으로 실행한다는 뜻이 아니다.

read는 다음 순서를 fail closed로 수행한다.

1. exact identity와 optional expected fingerprint 형식을 검증하고 Common runtime compatibility를 확인한다.
2. injected root와 identity projection으로 final path 하나만 결정한다. staging, sibling 또는 directory listing으로 publication을
   찾지 않는다.
3. final directory의 존재와 exact 두 entry가 regular file인지 검증한다. extra file은 v1 corruption이다.
4. 두 파일을 strict JSON으로 decode해 duplicate key, NaN/Infinity, non-object와 malformed bytes를 거부한다.
5. decoded payload를 `canonical_json_bytes()`로 다시 직렬화해 persisted bytes와 exact equality를 검증한다.
6. Common public validator로 `DatasetVersion`과 `DatasetManifest` schema를 각각 검증한다.
7. Version이 `status="frozen"`, `approved=true`, `frozen=true`, `training_allowed=true`이고 Manifest가
   `manifest_status="issued"`, `training_allowed=true`인지 검증한다.
8. requested identity가 Version의 `object_id`, `dataset_id`, `dataset_version`과 일치하고 Manifest의 source/version identity까지
   동일 pair에 결속되는지 검증한다.
9. Manifest self-checksum, Version/Manifest ID·content checksum·dataset·item-count binding을 `_require_domain_identity()`와
   동등한 pair-local rule로 검증한다.
10. canonical pair fingerprint를 재계산해 result에 넣고 optional expected fingerprint가 있으면 exact match를 검증한다.

[제안] pair fingerprint는 별도 파일이나 payload field로 persisted되지 않는다. 따라서 “missing fingerprint file”은 v1 case가
아니다. reader는 ADR-015 projection에서 항상 재계산하며 optional trusted expected value가 있을 때 mismatch를 독립 검출한다.
fingerprint를 새 파일로 쓰거나 Manifest field에 삽입하지 않는다.

[제안] read 성공은 historical committed publication fact의 검증이다. Proposal/Review Authority, approval, current RightsMetadata,
current TrainingEligibility와 CurrentEvidence snapshot을 조회하지 않는다. full publication scenario는 upstream objects와 original
`evaluated_at`이 pair에 전부 저장되지 않아 standalone read가 재구성해서는 안 된다.

### Validation depth matrix

| 항목 | Existence | Schema/Identity | Full Authority Verification |
|---|---:|---:|---:|
| corruption detection | 낮음 | 중간 | **높음** |
| canonical bytes | 아니요 | 선택적 | **예** |
| pair fingerprint | 아니요 | 아니요 | **재계산; expected가 있으면 대조** |
| restart safety | 낮음 | 중간 | **높음** |
| replay consistency | 없음 | 부분 | **pair-local invariant 일치** |
| 구현 비용 | 낮음 | 중간 | 높지만 기존 primitive 분리 가능 |

Existence-only는 malformed authority를 정상으로 반환해 기각한다. Schema/identity-only는 semantically equal한 noncanonical bytes,
extra file과 lifecycle corruption을 놓쳐 기각한다.

## Read-only, concurrency와 process contract

[제안] read는 verification only다. `mkdir`, write, rename, cleanup, quarantine, staging creation, canonical rewrite, fingerprint rewrite,
permission mutation, repair와 fallback은 모두 0이다. noncanonical JSON을 canonicalize-and-save하거나 missing/corrupt 값을
재계산해 저장하지 않는다.

[제안] exact final path만 읽으므로 process-crash orphan staging과 concurrent publisher staging은 보이지 않는다. no-replace final
directory rename 전에는 `PUBLICATION_NOT_FOUND`, commit 뒤에는 complete pair만 반환한다. 같은 root와 exact identity를 가진 새
process와 여러 process는 동일 canonical record/fingerprint를 얻는다. process-local cache를 authority로 사용하지 않는다.

[제안] reader와 publisher가 동시에 실행될 때 final 부재 관찰은 정상 `NOT_FOUND`다. final이 나타난 뒤 file-set 또는 read I/O가
실패하면 partial success나 retry guess 없이 해당 typed failure로 종료한다. Network filesystem과 power-loss durability는 ADR-015
범위처럼 보장하지 않는다.

## Failure taxonomy와 sanitization

후속 public contract는 기존 `DatasetPublicationError`의 sanitized `code`/`stage` 형태를 재사용하되 query 의미를 다음처럼
고정한다. 같은 의미의 중복 exception hierarchy를 만들지 않는다.

| public code | 조건 | 구분 |
|---|---|---|
| `PUBLICATION_READ_REQUEST_INVALID` | identity 또는 optional expected fingerprint 형식 오류 | caller input |
| `PUBLICATION_NOT_FOUND` | usable root 아래 deterministic final directory 부재 | 정상 exact miss |
| `PUBLICATION_CORRUPT` | final은 있으나 required file 누락, extra/non-file entry, malformed/noncanonical bytes, lifecycle·pair binding·checksum 위반 | persisted authority invalid |
| `PUBLICATION_SCHEMA_INVALID` | Common resource/schema/version validation 실패 | contract compatibility failure |
| `PUBLICATION_IDENTITY_MISMATCH` | decoded pair identity가 requested identity와 불일치 | wrong authority at deterministic location |
| `PUBLICATION_FINGERPRINT_MISMATCH` | optional expected fingerprint와 recomputed pair fingerprint 불일치 | external integrity assertion failure |
| `PUBLICATION_STORAGE_UNAVAILABLE` | root 부재·invalid capability, permission denied, unreadable mount 또는 I/O failure | not-found와 다른 storage failure |

[제안] root가 usable하고 final만 없을 때만 `NOT_FOUND`다. final이 있는데 한 파일이 없으면 `CORRUPT`다. wrong identity는
`IDENTITY_MISMATCH`, expected fingerprint mismatch는 `FINGERPRINT_MISMATCH`, permission/I/O는 `STORAGE_UNAVAILABLE`다.

[제안] error string/result에는 stable code, query stage와 requested resource identity/reference만 허용한다. absolute root/path,
username, mount detail, filename, raw malformed body, credential, raw OS exception와 stack trace는 노출하지 않는다. 원인은 exception
chaining으로 내부에 보존할 수 있지만 public serialization에는 포함하지 않는다.

## Read model decision matrix

| 항목 | Public function | Authority Protocol | Storage abstraction | BLOCKED |
|---|---|---|---|---|
| exact lookup | 가능 | **가능** | 가능 | 불필요 |
| future runtime composition | root가 call마다 노출됨 | **capability 주입·fake 교체 용이** | 범위가 과도함 | 진전 없음 |
| testability | filesystem fixture 필요 | **fake port와 filesystem adapter 분리** | 높음 | 없음 |
| storage encapsulation | signature에 root가 드러남 | **private adapter에 layout 보존** | layout 외 책임까지 일반화 | 없음 |
| API stability | function/path 결합 위험 | **semantic request/result 안정화** | premature multi-backend API | 없음 |
| 구현 비용 | 낮음 | **중간** | 높음 | 0이지만 사용자 가치 없음 |

[제안] `Authority Protocol`을 선택한다. fixed local filesystem adapter는 port의 첫 implementation이고 generic DB/object-store API를
설계하지 않는다. exact identity-to-path mapping과 pair-local validation이 모두 결정돼 `D. BLOCKED` 조건은 성립하지 않는다.

## Future implementation scope와 tests

[제안] 후속 별도 PR의 production 범위는 Dataset Publication module의 public port/result/error와 filesystem adapter, package export,
직접 unit/process tests 및 문서 동기화다. migration, DB/index, runtime config, CLI/API/worker와 Training 연결은 0이다.

최소 acceptance tests는 다음과 같다.

1. exact identity successful read
2. 새 process에서 same root+identity read
3. usable root의 missing publication은 `NOT_FOUND`
4. required file missing은 `CORRUPT`
5. malformed/duplicate-key JSON 거부
6. semantically valid noncanonical JSON 거부
7. wrong DatasetVersion identity는 `IDENTITY_MISMATCH`
8. wrong Manifest source/binding 거부
9. non-frozen Version lifecycle 거부
10. non-issued Manifest lifecycle 거부
11. optional expected pair fingerprint mismatch 거부
12. extra file/non-file entry 거부
13. permission/I/O와 root unavailable을 `NOT_FOUND`와 구분
14. returned DTO와 nested snapshots 불변
15. 성공·실패 read 모두 write/rename/mkdir 0
16. corrupt/noncanonical pair no-repair
17. orphan/concurrent staging 무시
18. committed command result와 standalone record의 pair/fingerprint equivalence
19. error에 path/body/credential/stack trace 없음
20. multiple processes에서 동일 canonical result
21. commit 전 read는 `NOT_FOUND`, commit 후 complete pair만 관찰
22. unsupported Common schema/package/policy version fail closed

[경고] 현행 Windows pytest/temp ACL 문제는 architecture contract와 분리한다. 후속 구현 test가 막히면 별도 infrastructure 문제로
기록하며 이 docs-only Gate에서 temp ACL, workflow path filter 또는 repository-wide Ruff debt를 수정하지 않는다.

## Final decisions

| 결정 항목 | 판정 |
|---|---|
| Public Read Contract | `C. NEW PUBLIC READ PORT REQUIRED` |
| Exact identity input | `DatasetVersionIdentity`; optional expected pair fingerprint는 verification data |
| Deterministic location | `YES`; identity checksum의 root 직하 final directory |
| Storage owner | Dataset Publication module |
| Publication root boundary | filesystem adapter construction에 explicit dependency injection; future config owner는 ADR-027 |
| Read result type | 새 immutable `DatasetPublicationRecord` 의미 DTO |
| Validation depth | `FULL DURABLE AUTHORITY VERIFICATION`의 pair-local 범위 |
| Canonical bytes verification | `YES` |
| Exact file-set verification | `YES`; v1은 두 regular file만 허용 |
| Pair fingerprint verification | `YES`; 항상 재계산, optional expected value가 있으면 대조 |
| Schema validation | `YES`; Common public validators |
| Lifecycle validation | `YES`; frozen/issued exact state |
| Read-only/no-repair | `YES` |
| Process restart | `SUPPORTED` |
| Multi-process | `SUPPORTED` |
| Listing/latest/search | `NOT SUPPORTED` |
| Runtime/API/CLI | `NOT ACTIVATED` |
| DB/migration/index | `0` |
| Implementation readiness | `READY FOR IMPLEMENTATION` |

## Boundaries, consequences와 remaining blockers

- [제안] query와 publish/replay command가 분리되고 private filenames/path가 public API에서 숨겨진다.
- [제안] committed pair를 current Training permission으로 해석하지 않는다. historical `training_allowed` field는 current
  authorization이 아니다.
- [제안] future format의 extra file, unknown schema/version 또는 lifecycle은 자동 downgrade·guess 없이 fail closed한다. v2 format은
  별도 ADR과 adapter/version dispatch가 필요하다.
- [제안] filesystem capability는 storage access일 뿐 business IAM이 아니다.
- [검증 필요] 후속 구현에서 final public symbol 이름과 package export 위치를 확정한다.
- [검증 필요] filesystem adapter root capability validation의 정확한 platform rule과 error-stage mapping을 테스트로 고정한다.
- [제외] CurrentEvidence, Proposal/Review/Approval 재검증과 publication scenario 재구성
- [제외] Rights owner, reviewer authority, governance runtime config/secret와 production composition 구현
- [제외] listing/latest/search, repair, migration, DB/index/object store와 network filesystem 지원
- [제외] CLI, API, worker, runtime activation, Dataset artifact open, Training/Evaluation/promotion

[현재] Rights owner, CurrentEvidence projection/snapshot, reviewer trust와 runtime config/composition은 계속 별도 blocker다. 이
read contract가 `READY FOR IMPLEMENTATION`이어도 ADR-027 overall prerequisite와 Dataset Governance Runtime Activation은
`STILL BLOCKED`다.

## Acceptance와 approval Gate

- [제안] exact identity와 deterministic location을 actual code와 ADR-015에서 확인했다.
- [제안] private replay verifier assumption과 public query validation을 분리했다.
- [제안] full pair-local verification, immutable result, read-only/no-repair와 sanitized failure taxonomy를 결정했다.
- [제안] restart, multi-process와 concurrent publish/read visibility를 기존 atomic final-directory contract에 결속했다.
- [제안] production source·test·migration·runtime·CLI/API/worker 변경은 0이어야 한다.

이 ADR은 `draft`·`proposed`다. 독립 검토, 사용자 명시 승인과 merge 전 authoritative implementation requirement가 아니다.
merge되더라도 Runtime/API/CLI, CurrentEvidence, Training 또는 publication write를 활성화하지 않는다. 승인·병합 뒤 별도 PR에서
`Dataset Publication Pair Public Read` 구현을 진행한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-26 | [제안] exact-identity Authority Protocol, pair-local full verification, immutable query result와 read-only failure 계약 결정 |
