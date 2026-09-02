# ADR-037: Large Product Dataset Proposal Manifest-Reference Authority

- 문서 상태: `approved`
- 결정 상태: `approved`
- 결정일: 2026-09-02
- 기준 DohaLM commit: `35affee0d246282bb1ad45891f08f8380c512e9c`
- 선행 결정: [ADR-025](./ADR-025-dataset-version-proposal-authority-contract.md),
  [ADR-026](./ADR-026-dataset-review-authority-contract.md),
  [ADR-035](./ADR-035-candidate-a-product-dataset-provenance-and-producer-policy.md),
  [ADR-036](./ADR-036-existing-aihub-current-use-rights-authority.md)
- 승인 근거: 2026-09-02 사용자 `DDORINY`의 Large Product Dataset Proposal Authority Contract
  Remediation 및 production publication 재개 명시 요청

## Context

Candidate A `production-v1`의 97,747-member Common DatasetVersion draft는 canonical JSON이
252,110,202 bytes다. 기존 proposal authority의 immutable row는 2~16,777,216-byte payload만
허용하므로 proposal 생성은 DB mutation 없이 fail closed했다.

크기 구성은 extensions 197,468,250 bytes, lineage 26,684,945 bytes, split manifest
27,955,712 bytes다. 이는 단순 JSON 공백이나 PostgreSQL 한도 부족이 아니라 동일 member authority를
proposal row에 다시 inline한 구조적 중복이다. root-cause classification은
`DUPLICATED_MEMBER_PAYLOAD + INLINE_MANIFEST_DESIGN_LIMIT`, 즉 `MIXED`다.

## Decision

large Product Dataset proposal은 `MANIFEST_REFERENCE / HYBRID v2`를 사용한다. 기존 inline v1은
historical·small-Dataset compatibility를 위해 변경하지 않는다.

v2 authority row에는 `dataset_version_proposal_root / 2.0.0` canonical root만 저장한다. root는 다음을
직접 bind한다.

- proposal ID와 logical Dataset identity
- composition ID, source fingerprint, content fingerprint
- composition, member, Dataset, allocation manifest의 logical identity, SHA-256, byte size, schema version
- member 수와 train/validation/test 수
- allocation fingerprint와 production Dataset fingerprint
- current Rights record/SourceToken reference와 eligibility evidence reference
- producer와 immutable created-at

proposal fingerprint는 root canonical JSON의 SHA-256이다. member content는 composition과 member manifest
fingerprint를 통해 transitively bind한다. filesystem path, filename, mtime, directory presence는 authority
identity가 아니며 runtime locator일 뿐이다. locator가 반환한 bytes는 사용 전마다 exact size와 SHA-256,
schema, composition equality, member set, split count, allocation fingerprint, Dataset fingerprint를 다시
검증한다.

review·approval·publication read는 bounded root만 신뢰하지 않는다. manifest authority가 full Common
DatasetVersion을 재구성하고 기존 schema/domain validator를 통과한 후에만 lifecycle을 진행한다. manifest
missing, byte tamper, stale reference, member/count/split/allocation/composition/Dataset/Rights/eligibility
mismatch는 fallback 없이 fail closed한다.

## Alternatives

| option | decision | reason |
|---|---|---|
| 256/512MiB inline limit | rejected | 100k/1M scale와 storage duplication을 해결하지 못함 |
| compressed inline payload | rejected | review-time random access·tamper semantics를 압축 구현에 결합함 |
| normalized per-member table | deferred | 강한 query 기능 대신 대규모 migration·write amplification을 유발함 |
| chunk-only authority | deferred | 현재 immutable manifests가 이미 content-addressed aggregate를 제공함 |
| manifest reference + bounded summary | selected | immutable replay, reproducible review, bounded DB row, future scale를 함께 만족함 |

## Persistence and compatibility

- forward-only migration `0009_large_dataset_proposal_authority.sql`은 기존 table에 schema version 1/2를
  추가하고 v2 compare/create/read restricted functions를 추가한다.
- 기존 `0004` function과 v1 row는 rewrite하거나 삭제하지 않는다.
- 16MiB DB limit, immutable trigger, owner/runtime roles, PUBLIC denial은 유지한다.
- same identity와 same root fingerprint는 replay, 하나라도 다른 root는 overwrite 없는 conflict다.
- C1/C2/C3, Host, backend, Training intent·journal semantics는 변경하지 않는다.

## Candidate A evidence

```text
full inline payload: 252,110,202 bytes
v2 canonical root: 2,485 bytes
v2 proposal fingerprint: sha256:3748ebf011afec10468894b791e7c8bd3f2f1a7d0072e63169a16ed33983e857
member manifest: sha256:338d4ffbed20e6b50e60bbd0aa7de64e00f93fbba732caeb941800af0b734069
Dataset manifest: sha256:7f016011da2d2ce607525a3dfe6eef44709ac5c13dc60970e8ff76cf656edfb3
Dataset fingerprint: sha256:70547888a0a989767744e7b5a8c0b9ce5afe6b747b4c6f40b73515ec79977f33
```

## Consequences

- proposal DB cost is member count와 독립적인 bounded metadata가 된다.
- full review는 manifests를 다시 읽으므로 read amplification이 존재하지만, authority integrity와
  reproducibility를 우선한다.
- content-addressed artifact 보존은 proposal lifecycle의 운영 prerequisite다.
- production publication과 Training 실행은 모든 migration·review·approval·currentness Gate가 통과한
  뒤에만 허용된다.
