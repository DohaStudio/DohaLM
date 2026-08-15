# PostgreSQL 16.15 C1 risk evidence correction

- 문서 상태: `review`
- 마지막 검토일: 2026-08-15
- Decision ID: `C1-PG16-ALPINE-1615-20260815-02`
- decision: `accepted`
- accepted: `true`
- execution authorized: `true`
- approver: `DDORINY`
- approved at: `2026-08-15T13:45:06.7768148+09:00`
- expires at: `2026-09-14T13:45:06.7768148+09:00`

## 결론

[확정] exact artifact는 `postgres:16.15-alpine`의 `linux/amd64` manifest
`sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571`이다. index, config,
Alpine base와 source revision은 각각 `sha256:ab5c955e…73785`, `sha256:75f5a969…7f6b`,
`sha256:79ff19e9…d95f`, `9d15534160ade17f2b6c455a39ee967c49b1937d`다.

[확정] Docker Scout 1.24.0 fresh unsuppressed scan은 Critical 2 / High 21 / Medium 19 / Low 5 /
Unspecified 3, 총 50건이다. raw SARIF SHA-256은
`879efbff5dd39a76f98534ada53b161ee62187a45c9b223c34c6a6f148fbc40c`이며 raw finding을 삭제하거나
suppression하지 않았다. advisory DB build timestamp는 scanner가 노출하지 않아 `null`이며 PASS 근거가 아니다.

[확정] 네 신규 High와 한 Medium delta는 exact gosu 1.19 / Go 1.24.6 / CGO 0에 대해 source dependency,
complete linked-symbol inventory, binary/source govulncheck와 official entrypoint reachability를 교차 검증했다. 네 High는
`not_applicable_exact_artifact`, Medium은 같은 exact-artifact 판정이나 C/H 집합에는 포함하지 않는다. 이 판정은 다른
manifest, gosu build, entrypoint 또는 실행 경계로 확대할 수 없다.

## Risk set

- raw C/H: 23
- adjudicated: 7 — 기존 3 + 신규 High 4
- residual: 16 — Critical 1 / High 15
- `raw = residual ∪ adjudicated`: true
- overlap / missing / duplicate / unknown: 0 / 0 / 0 / 0

[확정] 세 기존 adjudication은 이전 immutable bundle을 참조하고 네 신규 High bundle은 이 directory에 둔다. Medium
`CVE-2026-56858`은 `medium-delta/`에 별도 보존한다.

## 종료와 새 record

[확정] 이전 accepted record `C1-PG16-ALPINE-1615-20260814-01`은 fresh scan의 severity/advisory drift 조건으로 종료됐다.
이전 YAML을 수정하거나 남은 만료 기간을 재사용하지 않는다. 종료 시각·identity·delta는
[termination evidence](./termination-C1-PG16-ALPINE-1615-20260814-01.yaml)에 append-only로 기록했다.

[확정] 새 [risk decision record](./risk-decision-record.yaml)는 사용자 `DDORINY`의 명시 승인으로 `accepted: true`,
`execution_authorized: true`다. 유효 기간은 `2026-08-15T13:45:06.7768148+09:00`부터 정확히 30일 뒤인
`2026-09-14T13:45:06.7768148+09:00`까지다. 권한은 exact manifest를 사용하는 local/CI isolated ephemeral C1
schema·migration·restore contract test에만 적용되며 early-termination 정책을 그대로 따른다.

## Revalidation policy

### A — 즉시 종료

artifact manifest/config/base/source drift, 새 raw C/H ID, adjudicated finding의 applicable 전환, residual affected
range/component/location 확대, official VEX 철회, vulnerable symbol/call/runtime reachability 확인, C1 isolation·credential·
network·privilege·cleanup 실패, fixed official image와 compatibility Gate 통과, 승인 만료는 authorization을 즉시 종료한다.

### B — 실행 중지 후 semantic 재검증

동일 CVE·component·range·location의 severity 변화, EPSS 변화, OSV modified 또는 비의미 metadata 변화, JSON ordering/
serialization 변화, scanner advisory DB freshness 미노출은 다음 C1 run을 중지하고 semantic delta를 재검증한다. package,
symbol과 reachability가 불변인 exact-artifact not-applicable 판정은 새 risk acceptance 없이 유지할 수 있다. 범주 판정
evidence가 부족하면 fail closed한다.

### C — 정보성

문구·URL·related reference·transport ordering 또는 artifact/affected contract와 무관한 metadata 변화는 기록하되 권한을
자동 종료하지 않는다. 이 정책은 이미 종료된 record를 되살리지 않는다.

## Evidence와 integrity

- `common/`: image, scanner, raw SARIF, SBOM, gosu build/source/symbol, govulncheck, runtime, cleanup evidence
- `adjudications/`: 신규 High 4개 child bundle
- `medium-delta/`: 신규 Medium delta child bundle
- [risk set](./risk-set-decision.json)
- [manifest scope](./manifest-scope.json)
- `SHA256SUMS`: SHA-256과 decimal byte length의 parent coverage

## C1 Gate

- `postgres_image_evidence_ready: true`
- `postgres_risk_policy_stable: true`
- `postgres_new_risk_acceptance_required: false`
- `psycopg_dependency_candidate_ready: false`
- `psycopg_dependency_approval_required: true`
- `c1_implementation_authorized: true`

Psycopg 결과와 blocker는 [dependency Decision Packet](./psycopg-dependency-decision.md)에 기록한다.
