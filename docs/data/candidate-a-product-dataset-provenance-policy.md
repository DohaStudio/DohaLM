# Candidate A Product Dataset 계보 정책

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `approved` |
| 마지막 검토일 | 2026-09-02 |
| 적용 대상 | `AIHUB-71748 / Candidate A / production_internal` Product Dataset rebuild |
| 결정 문서 | [ADR-035](../decisions/ADR-035-candidate-a-product-dataset-provenance-and-producer-policy.md), [ADR-036](../decisions/ADR-036-existing-aihub-current-use-rights-authority.md) |
| 선행 정책 | [Phase 1 데이터 계약](./phase1-data-contract.md), [분할 및 누수 방지](./data-split-and-leakage-policy.md), [ADR-034](../decisions/ADR-034-cross-repository-rights-authority-and-current-evidence-snapshot.md) |
| 구현 상태 | rebuild implementation complete; production artifact execution is an operational Gate |

## 적용 계약

| 항목 | 승인 값 |
|---|---|
| member | existing canonical `source_id` |
| logical group | `NFC(data_file)` |
| persisted group key | `group:sha256:<SHA-256(logical group UTF-8)>` |
| split policy/version | group-preserving SHA-256 bucket / `aihub-71748-production-split-v1` |
| seed | `17` |
| ratios | train `0.90`, validation `0.05`, test `0.05` |
| candidate granularity | selected canonical source record 1건 |
| candidate ID | `candidate:aihub-71748-production-v1:<source_id lowerhex>` |
| Common candidate fields | `human_authored / base_pretraining / approved` |
| producer | `dohalm-dataset-ingestion / 1.0.0` |
| Rights | shared current AIHUB-71748 source Rights Subject record/token |
| eligibility | candidate-specific deterministic projection |
| review | validation-backed immutable review; all required checks pass only |
| current-use review validity | `candidate-a-current-review-24h-v1`; legal Rights expiry가 아닌 operational recheck window |

같은 source, selector, group policy, split version과 seed는 exact same allocation을 만들어야 한다. member·group 중복,
missing metadata, cross-split group, non-current authority와 fingerprint mismatch는 rebuild를 중단한다.

## Source evidence

| evidence | result |
|---|---:|
| canonical source records | 107,226 |
| stable `source_id` missing / duplicate | 0 / 0 |
| raw `data_id` unique / conflicting duplicate occurrences | 107,224 / 2 |
| `data_file` missing / unique / max group | 0 / 93,999 / 7 |
| `data_source` unique / max group | 85,352 / 8,192 |
| `data_title` unique / max group | 87,285 / 8,193 |
| one `data_file` mapped to multiple `data_source` | 0 |
| selected records after historical selector and approved PII exclusion | 97,747 |
| selected `data_file` groups | 85,992 |

raw `data_id`, `data_source`와 `data_title`은 canonical member/group identity로 사용하지 않는다. `data_file`을
source-document boundary로 채택하지만 raw text는 authority ID로 노출하지 않는다.

## Split evidence and invariants

| split | records | groups | observed record ratio |
|---|---:|---:|---:|
| train | 88,071 | 77,524 | 90.10% |
| validation | 4,770 | 4,193 | 4.88% |
| test | 4,906 | 4,275 | 5.02% |

- cross-split group overlap: `0`
- reversed-order deterministic replay: `PASS`
- allocation fingerprint contract: `aihub-71748-production-allocation-fingerprint-v1`
- allocation fingerprint: `sha256:055e82a5103043b769a9d2ea56b9efc4243c50e4c38261d87177b8fb63d66f3c`
- canonical bytes: `19,177,444`
- train, validation, test non-empty: `PASS`

ratio는 record 수를 강제로 맞추는 quota가 아니라 group hash bucket threshold다. 따라서 실제 record 비율은 정확히
90/5/5가 아닐 수 있다. group을 쪼개 ratio를 맞추는 것은 금지한다.

### Allocation fingerprint serialization

authoritative machine contract는
[`aihub-71748-production-allocation-fingerprint.contract.json`](./aihub-71748-production-allocation-fingerprint.contract.json)이다.
logical row는 canonical ASCII `source_id`, `group_key`, `split`만 포함하고 `source_id` UTF-8 bytes 오름차순으로 정렬한다.
payload는 `contract_version`과 `allocations`를 가진 JSON object이며 기존 `canonical_json_bytes` 계약인 sorted keys,
compact separators, `ensure_ascii=false`, UTF-8, trailing LF 1개를 사용한다. SHA-256은 이 complete bytes에 적용한다.

최초 승인 값 `sha256:0eee73ff...c8308c`는 recipe와 input bytes가 보존되지 않아
`LEGACY_APPROVED_FINGERPRINT_UNREPRODUCIBLE`로 남긴다. allocation content는 변경하지 않았으며 unversioned implementation
projection `sha256:805f65e2...a99f83`도 새 authority로 사용하지 않는다.

## Producer and review acceptance

producer input은 canonical typed source record, source identity·lineage, selector ID, split policy identity와 frozen authority
references다. output은 immutable Common LearningCandidate이며 review, Rights decision과 arbitrary eligibility state를 포함하지
않는다. candidate의 Common `approved` 상태와 non-empty review evidence는 ADR-035의 deterministic upstream policy evidence를
뜻하며 local Dataset inclusion review나 publication 결과를 뜻하지 않는다.

candidate review ACCEPTED 조건은 모두 필수다.

1. Common schema validation 성공
2. canonical `source_id`와 source location 재계산 일치
3. normalized content fingerprint 일치
4. historical selector membership과 approved PII exclusion 통과
5. canonical group과 split allocation 재계산 일치
6. ADR-034 source Rights current record/token과 Dataset source binding 일치
7. candidate-specific eligibility projection current 및 approved internal Training scope
8. duplicate candidate ID, conflicting content와 authority ambiguity 없음

review aggregate authority는 accepted review의 canonical sorted identities와 fingerprints를 결속한다. 개별 실패를 aggregate
성공으로 숨기거나 부분 성공을 Dataset approval evidence로 사용할 수 없다.

## Rights, eligibility and authority boundary

- Rights owner는 DohaRights다. DohaLM candidate producer는 Rights record를 발행·변경하지 않는다.
- Candidate A source-wide current permission을 candidate가 exact lineage로 참조한다. candidate별 Rights 복제는 0이다.
- eligibility는 candidate ID를 가진 immutable projection이며 approved Dataset-level evidence와 member validation에서만 파생한다.
- schema, manifest, eligibility, approval aggregate와 composition producer owner는 ADR-035 표를 따른다.
- missing, expired, revoked, multiple-current 또는 source mismatch는 fail closed한다.

## Deferred work and non-authority

semantic near-duplicate clustering과 threshold는 production v1에 포함하지 않는다. 후속 quality analysis는 새 policy version과
split regeneration decision 없이 현재 allocation을 변경할 수 없다.

이 문서와 simulation은 Dataset artifact, publication, Training approval 또는 commercial/publication 권한이 아니다. 실제 rebuild는
별도 implementation Gate에서 exact producer port, authority material과 manifests를 만들고 검증해야 한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-09-02 | versioned allocation fingerprint contract와 machine-readable authority manifest 반영 |
| 2026-09-01 | Candidate A production provenance policy 최초 승인 |
