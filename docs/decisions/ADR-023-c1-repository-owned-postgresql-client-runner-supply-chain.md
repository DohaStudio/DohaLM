# ADR-023: C1 Repository-Owned PostgreSQL Client Runner Supply Chain

- 문서 상태: `approved`
- 마지막 검토일: 2026-08-15
- 결정 상태: `accepted`
- 실행 영향: C1 runner 구현·검증·GHCR 게시, exact dependency 설치와 C1-A/B/C 구현 승인; production activation 미승인
- decision: `accepted`
- runner_implementation_authorized: `true`
- registry_publish_authorized: `true`
- dependency_installation_authorized: `true`
- c1_implementation_authorized: `true`
- production_activation_authorized: `false`
- approver: `DDORINY`
- approved_at: `2026-08-15T13:45:06.7768148+09:00`
- 관련 문서: [ADR-021](./ADR-021-production-training-adapters-and-durable-journal.md),
  [ADR-022](./ADR-022-c1-ephemeral-postgresql-test-image-security-policy.md),
  [Definition of Ready](../governance/definition-of-ready.md),
  [Definition of Done](../governance/definition-of-done.md),
  [테스트 전략](../quality/test-strategy.md),
  [테스트 체크리스트](../quality/testing-checklist.md)

## Context

[확정] ADR-021은 C1 schema/dependency → C2 adapter → C3 composition → 별도 Production Activation 순서를 승인했다.
ADR-022의 현재 PostgreSQL 16.15 Option B risk record는 사용자 `DDORINY`의 명시 승인으로 `accepted`이며,
`execution_authorized: true`다. 이 권한은 exact manifest의 local/CI isolated ephemeral C1 test와 별도 Draft 구현에만
적용되며 C2/C3, Production Activation 또는 실제 Training을 승인하지 않는다.

[확정] `psycopg[binary] 3.3.4`의 official Windows wheel은 libpq 18.3·OpenSSL 3.6.2, Linux wheel은 libpq
18.0을 bundle해 security-fixed libpq 18.4 baseline에 미달했다. pure-Python `psycopg 3.3.4`와 Alpine libpq
18.4-r0 prototype은 기능 식별에 성공했지만 final runtime의 `binutils 2.45.1-r1`에서 unsuppressed High 3건이
남았다. Debian slim 대안도 Critical 2·High 2로 탈락했다. 두 clean Alpine prototype build의 OCI digest도 일치하지
않았다. 이 결과를 PASS 또는 승인된 dependency로 재해석하지 않는다.

[확정] Windows native와 Linux native가 서로 다른 system libpq를 소비하는 방식은 supplier·artifact parity가 없다.
`psql` subprocess는 Python DB error와 transaction mapping 계약에 부적합하다. 따라서 C1 local/CI contract test에는
repository가 recipe와 publication lifecycle을 소유하고 두 환경이 같은 published `linux/amd64` manifest digest를 실행하는
별도 client runner 설계가 필요하다.

[확정] 현재 repository에는 runner Dockerfile, publish workflow, GHCR package, driver dependency와 lockfile pin이 없다.
branch protection과 ruleset도 없고 repository Actions 정책은 모든 Action을 허용하며 full commit SHA pin을 강제하지 않는다.
따라서 workflow 자체가 trusted-event, 최소 권한과 immutable Action pin을 fail-closed로 강제해야 한다.

## 검토한 선택지

| 선택지 | 장점 | 문제 | 판정 |
|---|---|---|---|
| patched official `psycopg[binary]` 대기 | upstream이 wheel과 bundled library를 소유 | 현재 3.3.4 artifact가 baseline 미달이고 release 시점 미정 | 대기 대안 |
| Windows/Linux native system libpq | container build 불필요 | supplier·library·crypto artifact parity 없음 | 기각 |
| pure-Python Alpine runner | source compile 불필요 | libpq discovery용 binutils가 final runtime High 3건 유발 | 기각 |
| Debian slim pure-Python runner | glibc loader가 system libpq 발견 | base runtime Critical 2·High 2 | 기각 |
| repository-owned compiled Psycopg C runner | final runtime에서 compiler/header/binutils 제거 가능, same-digest 소비 가능 | build·registry·provenance·patch 운영 책임 필요 | 채택 제안 |

## Proposed Decision

### 1. 목적과 artifact topology

[제안] C1 local/CI PostgreSQL schema·migration·restore contract test의 Python client는 repository-owned minimal
client runner만 사용한다. runner는 test-only artifact이며 production runtime dependency, production database client 또는
Training execution artifact가 아니다.

[제안] trusted GitHub Actions workflow가 하나의 `linux/amd64` image를 한 번 build·검증·publish하고, Windows Docker
Desktop과 Linux CI는 source rebuild 없이 동일한 platform manifest digest를 소비한다. tag, index digest 또는 equal-version
native installation은 parity authority가 아니다.

[제안] proposed canonical registry path는 다음과 같다.

```text
ghcr.io/dohastudio/dohalm-c1-postgres-client
```

lowercase organization namespace와 package name을 사용한다. package는 아직 존재하지 않으며 이 ADR은 생성·visibility·publish를
승인하지 않는다. 구현 PR은 최초 publish 전에 package-to-repository linkage, inheritance/granular access, pull visibility와
retention 설정을 독립 검증해야 한다.

### 2. Multi-stage build 계약

#### Build stage

[제안] 구현 recipe는 다음 direct input을 version뿐 아니라 exact digest/hash로 고정한다.

- exact `linux/amd64` builder base index·manifest·config digest와 source revision
- exact Python patch version
- `psycopg==3.3.4` official universal wheel와 SHA-256
  `b6bbc25ccf05c8fad3b061d9db2ef0909a555171b84b07f29458a447253d679a`
- `psycopg-c==3.3.4` official sdist
- sdist SHA-256 `ed8106128b2d04359c185fc9641b4409abfce4d0b6fb1d1ff6800646e27f1a22`
- resolver가 요구하는 `typing_extensions==4.16.0` official wheel와 SHA-256
  `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8`
- compiler, linker, Python headers, PostgreSQL/libpq headers와 build frontend의 exact artifact/version/hash
- package index snapshot 또는 모든 fetched artifact의 exact URL, decimal size, SHA-256와 signature verification
- normalized Dockerfile, build arguments, environment, locale, timezone와 build command

[제안] network fetch와 compilation은 분리한다. fetch 단계가 모든 direct/transitive artifact를 검증해 immutable build-input
manifest를 만든 뒤 compile 단계는 network 없이 그 manifest의 artifact만 사용한다. 생성 wheel의 filename, platform tag,
decimal size와 SHA-256를 기록한다. floating package index, unpinned install, mutable URL과 build-time `latest`는 금지한다.

#### Runtime stage

[제안] final runtime에는 exact allowlist만 존재할 수 있다.

- exact minimal runtime base index·`linux/amd64` manifest·config digest와 exact Python patch
- exact `psycopg==3.3.4` core wheel, build stage가 생성하고 hash를 기록한 matching `psycopg-c==3.3.4` wheel과
  exact runtime dependency closure; implementation identity `c`
- upstream security-fixed libpq 18.4 계열의 exact provider/version/artifact/hash
- libpq에 실제 link된 OpenSSL/TLS library의 exact provider/version/artifact/hash
- 필요한 libc, CA bundle과 runtime shared library closure
- 고정 non-root UID/GID와 최소 entrypoint

[제안] compiler, linker/binutils, headers, source/sdist, package-manager cache/index, build frontend, shell helper와 사용하지 않는
package는 final runtime에 0개여야 한다. implementation PR은 SBOM과 filesystem inventory를 동일 allowlist로 비교하고 unknown,
missing 또는 extra component를 fail closed한다.

[제안] final runner는 read-only root filesystem, writable tmpfs 한정, `no-new-privileges`, capabilities drop all, public port 0과
task-owned private network에서 실행 가능해야 한다. image에는 credential, DSN, Dataset content 또는 test result를 넣지 않는다.

### 3. Registry와 immutable identity

[제안] consumer reference는 반드시 다음 형태다.

```text
ghcr.io/dohastudio/dohalm-c1-postgres-client@sha256:<linux-amd64-manifest-digest>
```

- tag-only pull, floating `latest`, branch tag와 multi-arch index-only pin은 금지한다.
- evidence에는 index, platform manifest, config, source commit과 normalized recipe hash를 모두 기록한다.
- source와 evidence에 기록하는 실행 authority는 실제 `linux/amd64` manifest digest다.
- digest 변경은 별도 review 가능한 repository commit과 fresh evidence Gate를 요구한다.
- superseded digest를 같은 tag의 이동만으로 승인하거나 rollback authority로 복구하지 않는다.
- release reference overwrite와 untrusted branch/fork의 package write를 금지한다.

GHCR가 tag immutability를 강제한다고 가정하지 않는다. content-addressed digest와 attestation verification이 authority다.

### 4. Build·publish trust boundary

[제안] build/publish workflow는 protected trusted branch의 reviewed commit 또는 명시적 `workflow_dispatch` approval로만 시작한다.
현재 branch protection/ruleset 부재는 WARNING이며, 구현 전에 trusted-event 조건과 environment approval 또는 동등한 repository
governance control을 증명해야 한다. `pull_request_target`, fork PR과 untrusted PR code에는 package write·OIDC·attestation
권한을 주지 않는다.

[제안] workflow permission은 job별 최소 권한이다.

- default와 validation jobs: `contents: read`
- publish job만: `contents: read`, `packages: write`
- GitHub OIDC/artifact attestation을 선택한 attestation job만: `id-token: write`, `attestations: write`
- 그 밖의 write permission은 명시적으로 `none`

[제안] third-party Actions와 reusable workflow는 reviewed repository의 full commit SHA로 pin한다. tag/branch reference는 금지한다.
untrusted PR title, branch, label, body, filename 또는 input을 shell/script에 직접 보간하지 않는다. build secret은 layer,
provenance parameter, SBOM, log와 artifact에 포함하지 않는다. credential persistence를 최소화하고 publish 동시성 group으로
같은 source/version의 race를 단일 winner로 제한한다.

[제안] build, final runtime allowlist, SBOM, full scan, attestation과 signature 검증이 모두 끝나기 전 artifact를 approved로
승격하지 않는다. partial push 또는 attestation 실패 digest는 consumer record에 기록하지 않고 별도 failed evidence로 남긴다.

### 5. SBOM·provenance·signature 계약

[제안] 다음 evidence를 동일 platform manifest digest에 결속한다.

- SPDX 또는 CycloneDX SBOM과 SHA-256
- OCI build provenance/attestation과 source commit
- normalized Dockerfile와 build-input manifest SHA-256
- builder base/toolchain/workflow run identity
- index/manifest/config digest
- wheel/libpq/crypto/runtime-library identity
- scanner executable/version/hash, advisory source, scan timestamp와 report SHA-256
- signature 또는 keyless signing identity와 verification result

[제안] GitHub OIDC 기반 keyless signing 또는 GitHub artifact attestation을 우선 후보로 검증한다. 정확한 tool과 Action SHA는
implementation PR에서 repository의 current official support, permissions와 verification path를 확인해 선택한다. 이 ADR은
특정 도구 이름이나 mutable Action tag를 accepted authority로 고정하지 않는다.

[제안] consumer는 pull 전후 manifest digest와 provenance/SBOM attestation의 subject digest를 검증한다. attestation이 다른
index·manifest·repository·source commit을 가리키거나 verification이 unavailable이면 fail closed한다.

### 6. Reproducibility 정의

#### Consumer parity — 필수

- Windows Docker Desktop과 Linux CI가 같은 published `linux/amd64` manifest digest를 실행한다.
- 양쪽에서 manifest/config/SBOM/signature·attestation subject를 검증한다.
- 어느 환경도 wheel, image 또는 libpq를 재빌드하거나 native dependency로 대체하지 않는다.

#### Independent rebuild identity — 목표와 진단

- 고정 input으로 clean build를 최소 두 번 수행해 wheel, layer, config와 manifest delta를 기록한다.
- timestamp, compiler output, archive ordering, metadata와 layer serialization 차이를 설명한다.
- bit-for-bit equality가 성립하면 evidence로 기록하되 초기 C1 절대 승인 조건으로 사용하지 않는다.
- equality가 성립하지 않아도 input pin, trusted single publication, immutable digest consumption과 provenance Gate를 완화하지
  않는다. 설명되지 않은 dependency 또는 payload delta는 publish blocker다.

### 7. Security Gate

[제안] implementation/publish PR은 final runtime 전체를 suppression, ignore와 VEX filtering 0으로 scan한다.

- Critical 0
- High 0
- SBOM inventory와 scanner component/version/location 일치
- scanner/advisory DB build timestamp가 없으면 `unavailable`로 명시
- build-stage finding과 final runtime finding을 분리하되 build-stage risk를 삭제하지 않음
- final runtime compiler/header/binutils/package-manager cache 0

Critical 또는 High가 하나라도 남으면 자동 승인하지 않는다. exact-artifact not-affected/N/A 판정은 raw finding을 보존한 별도
evidence와 사용자 명시 승인이 있어야 하며 이 ADR이 선승인하지 않는다.

### 8. Functional·isolation Gate

[제안] implementation PR은 동일 runner manifest digest와 exact PostgreSQL server artifact
`postgres:16.15-alpine@sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571`를
사용해 다음을 검증한다. PostgreSQL image 실행은 ADR-022 current risk record의 별도 명시 승인 뒤에만 가능하다.

- Psycopg implementation `c`, Psycopg 3.3.4, exact libpq 18.4 계열과 linked crypto/runtime inventory
- UTF-8·UTC, parameter binding, commit/rollback과 timeout/cancellation
- composite FK/CHECK violation mapping
- advisory lock과 transaction-scoped advisory lock
- NOLOGIN owner/group, LOGIN runtime role와 privilege denial
- schema/migration transaction, restore와 restart persistence
- connection close와 deterministic teardown
- Windows Docker Desktop와 Linux CI의 same-digest execution
- non-root, read-only filesystem, public port 0, private task network와 synthetic credential/data
- task-owned container/network/volume와 credential fixture cleanup residue 0

### 9. Scope와 권한

[제안] 허용 후보 범위는 C1 local/CI isolated ephemeral schema·migration·restore contract test뿐이다. production, staging,
shared/live database, production credential/data, production runtime dependency, public port, C2/C3, Production Activation,
Dataset/Model/GPU/Training/Evaluation은 금지한다.

[제안] 이 ADR의 승인·병합만으로 runner build/publish, dependency installation, PostgreSQL risk acceptance, C1 implementation 또는
execution authority가 생기지 않는다. 각 권한은 implementation evidence와 아래 Phase Gate를 거친 별도 사용자 승인이다.

### 10. Ownership과 lifecycle

[제안] 다음 accountable role을 repository contract로 둔다. 실제 GitHub team/actor assignment는 모두 `null`이며 사용자 승인과
implementation PR의 CODEOWNERS/repository evidence 전에는 임의 확정하지 않는다.

| Role | 책임 | 현재 assignment |
|---|---|---|
| C1 Runner Supply Chain Owner | recipe, input pin, lifecycle과 termination | `null` |
| C1 Runner Build Workflow Owner | trusted event, permissions, Action pin과 failed publication | `null` |
| DohaStudio GHCR Package Owner | package linkage, visibility, access, retention과 revocation | `null` |
| C1 Runner Vulnerability Triage Owner | fresh advisory, C/H Gate, emergency rebuild | `null` |
| C1 Runner Cleanup Owner | ephemeral resource teardown와 residue evidence | `null` |

[제안] 정기 currentness 검토는 최소 주 1회와 PR Ready·publish·C1 run 직전에 수행한다. Python, Psycopg, libpq,
OpenSSL/TLS, libc, CA bundle, base, compiler/toolchain, scanner/advisory, Action SHA 또는 GitHub attestation support 변화는 fresh
review trigger다. 새 Critical/High, digest/provenance drift, signature failure, credential/registry compromise와 upstream security
release는 즉시 실행 종료·emergency rebuild trigger다.

[제안] current digest, 명시적 rollback digest와 그 evidence를 보존한다. superseded digest는 새 run에서 금지하되 historical
evidence를 덮어쓰거나 삭제하지 않는다. rollback은 기존 digest가 fresh Security/Functional Gate와 current source policy를 다시
통과한 경우에만 별도 review commit으로 허용한다. package deletion, attestation deletion과 retention 축소는 별도 승인 대상이다.

### 11. 구현 Phase Gate

이 ADR이 독립 검증·명시 승인·병합된 뒤에도 구현은 별도 Draft PR이다.

1. **C1-R1**: runner Dockerfile, exact build-input manifest와 offline multi-stage build
2. **C1-R2**: trusted workflow, GHCR package linkage와 single publication
3. **C1-R3**: SBOM, provenance, signature/attestation와 unsuppressed full scan
4. **C1-R4**: Windows/Linux same-digest functional·isolation probe와 cleanup evidence
5. **C1-R5**: published digest와 evidence의 independent read-only revalidation
6. PostgreSQL Option B risk + runner dependency + C1 implementation 통합 사용자 승인
7. 별도 C1-A/B/C implementation Draft PR

단계를 한 PR에 포함할 수 있지만 각 evidence Gate는 별도 review 가능한 commit과 fail-closed output을 가져야 한다. R1~R5 완료는
6·7단계 승인이 아니다.

## Failure와 termination contract

- input hash, manifest/config, SBOM, provenance 또는 signature mismatch: publish/consume 0
- final runtime Critical/High 또는 allowlist extra component: approval 0
- partial publication, tag race 또는 attestation binding 실패: failed digest 승격 0
- Windows/Linux manifest mismatch: parity 실패
- functional/isolation/cleanup failure: C1 실행 승인 0
- credential, raw DSN, secret, private path 또는 test data 노출: 즉시 중단·artifact revoke 검토
- process restart: 이전 local container/capability authority 복원 0

오류와 evidence에는 raw credential, DSN, secret, private path와 stack trace를 포함하지 않는다. cleanup은 task-owned resource만
대상으로 하며 기존 사용자 image/container/network/volume을 변경하지 않는다.

## Implementation acceptance criteria

1. exact build/runtime base, Python, toolchain, sdist, wheel, libpq, crypto와 runtime closure가 hash-pin됨
2. network fetch/compile 분리와 deterministic dependency resolution 증명
3. final runtime allowlist, SBOM과 full unsuppressed scan 일치; Critical/High 0
4. trusted branch/event, 최소 permission, full-SHA Action pin과 publish race 차단
5. GHCR package linkage·visibility·owner와 immutable platform manifest digest 확인
6. SBOM/provenance/signature subject가 동일 manifest digest와 source commit에 결속
7. Windows Docker Desktop와 Linux CI same-digest verification 및 전체 Functional Gate 통과
8. public port 0, synthetic-only, non-root/read-only와 cleanup residue 0
9. source checkout와 built artifact evidence의 private path·secret·binary repository ingress 0
10. independent read-only revalidation과 별도 사용자 통합 승인

## 명시적 미결정과 제외

- [검증 필요] exact builder/runtime base digest, compiler/header artifact와 linked crypto closure
- [검증 필요] exact workflow file, Action commit SHA, signing/attestation tool과 GHCR package settings
- [검증 필요] actual role/team assignment, CODEOWNERS와 emergency response SLA
- [제외] Dockerfile, workflow, dependency, lockfile, image, SBOM, migration, SQL, schema와 Python 구현
- [제외] image build/push/pull, package creation, credential 생성과 PostgreSQL/C1 실행
- [제외] 기존 immutable security evidence와 risk record 변경

## Consequences

- 장점: Windows와 Linux의 native libpq 차이를 제거하고 동일 published artifact를 parity authority로 사용한다.
- 장점: compiler/header/binutils를 final runtime에서 제거하면서 source·toolchain provenance를 review할 수 있다.
- 장점: bit-for-bit rebuild와 consumer parity를 분리해 unexplained drift는 차단하되 trusted publication을 명확히 소유한다.
- 비용: repository가 build workflow, GHCR, attestation, vulnerability triage와 patch lifecycle을 운영해야 한다.
- 한계: 이 ADR만으로 안전한 runner artifact가 존재하지 않으며 현재 C1 blocker는 유지된다.

## Revisit conditions

- security-fixed official Psycopg binary wheel이 배포된다.
- libpq/OpenSSL/Python/base/toolchain security baseline 또는 support status가 변경된다.
- GHCR, GitHub Actions, OIDC/signing·attestation trust model이나 repository policy가 변경된다.
- Windows/Linux가 동일 `linux/amd64` artifact를 실행할 수 없게 된다.
- runner가 production, shared DB, multi-arch 또는 cross-repository consumer로 확대된다.

## 승인 Gate

이 ADR은 사용자 `DDORINY`가 `2026-08-15T13:45:06.7768148+09:00`에 명시 승인해 `approved`·`accepted`다.
runner 구현·게시, exact dependency 설치와 C1-A/B/C 구현은 별도 implementation Draft PR에서 허용한다. R1~R5 evidence Gate는
완화되지 않으며 실패 시 fail closed한다. 이 승인은 C2/C3, Production Activation, 실제 Training 또는 production/staging/shared
database 접근 권한을 부여하지 않는다.

## 사용자 Decision Packet

1. repository-owned minimal C1 client-runner ADR 승인 및 별도 implementation Draft PR 착수 승인
2. ADR 수정 후 재검증
3. patched official Psycopg binary release 대기
4. Draft 유지 및 작업 중단

선택지 1은 multi-stage compiled Psycopg C 3.3.4, patched libpq 18.4 계열, final compiler/header/binutils 0, trusted
GitHub Actions single publication, GHCR immutable `linux/amd64` manifest, Windows/Linux same-digest consumption,
SBOM/provenance/signature, final runtime Critical/High 0과 isolated ephemeral-only 범위를 승인 대상으로 삼는다는 뜻이다.
그러나 이 선택도 PostgreSQL Option B risk acceptance나 C1 실행을 자동 승인하지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-15 | [확정] DDORINY 명시 승인으로 runner 구현·GHCR 게시·exact dependency 설치·C1-A/B/C를 승인하고 Production Activation은 차단 유지 |
| 2026-08-15 | [제안] repository-owned compiled Psycopg C client runner, GHCR same-digest parity와 공급망 Gate 초안 등록 |
