# C1 Psycopg dependency Decision Packet

- 문서 상태: `review`
- 마지막 검토일: 2026-08-15
- status: `accepted_for_c1_practical_profile`
- decision: `official_binary_3_3_4`
- dependency installation authorized: `true`
- C1 implementation authorized: `true`

## Practical Security Profile override

[확정] 사용자의 2026-08-15 후속 명시 결정은 아래 historical blocker 분석을 C1 warning으로
재분류한다. official `psycopg[binary]==3.3.4`를 exact wheel hash와 함께 local/CI isolated
ephemeral C1에서 사용할 수 있다. repository-owned runner, GHCR, SBOM, signature,
attestation 및 reproducibility는 C1 prerequisite가 아니다. 이 결정은 C2/C3, production
database, activation 또는 Training을 승인하지 않는다.

## Repository consumer contract

| 항목 | 실제 저장소 계약 |
|---|---|
| Python | `>=3.10,<3.13`; 현재 package manager는 setuptools/pip, lockfile 없음 |
| OS/CI | repository workflow 없음; Windows local과 미래 Linux CI를 모두 재현해야 함 |
| API | ADR-021 C1은 synchronous transaction, parameter binding, advisory lock, role denial, migration/restore가 필요 |
| async | C1 요구 없음 |
| pool | C1 요구 없음; production composition-owned pool은 C2 이후 |
| migration | tool 미선택; C1에서 별도 선택 필요 |
| dependency separation | 현재 core/optional requirements 파일 분리; C1 전용 group은 아직 없음 |
| TLS/FIPS | 별도 FIPS 요구 없음; bundled/system libpq·OpenSSL identity와 security 상태는 필수 |

## 후보 비교

| 후보 | 공급망·호환성 | C1 기능 | 판정 |
|---|---|---|---|
| A. `psycopg==3.3.4` pure Python + system libpq | 공식 지원, Python 3.10–3.12/Windows/Linux 가능; OS별 exact libpq 공급·hash·patch 계약 미확립 | sync transaction/binding/lock/role 충족 가능; 느리지만 C1에는 허용 가능 | **기술 우선 후보**, provenance blocker |
| B. `psycopg[c]==3.3.4` + system libpq | system libpq 외 compiler, headers, `pg_config`가 필요; Windows/Linux build 재현성 미확립 | 기능·성능 충족 | C1에 불필요한 build surface로 보류 |
| C. `psycopg[binary]==3.3.4` | wheel hash pin과 설치 재현 가능; libpq/OpenSSL을 wheel이 번들 | bounded probe 통과 | bundled libpq/OpenSSL High patch gap으로 차단 |
| D. `psql` subprocess fixture | server image에 client가 있어 image identity 단순 | Python transaction/error typing·parameter binding seam을 왜곡 | driver contract 대체로 기각 |
| E. 다른 driver | `asyncpg 0.31.0`은 async-only 방향, `pg8000 1.31.5`는 pure Python이지만 ADR-021 consumer contract와 별도 검증 필요 | 재구현 비용·migration ecosystem 차이 | Psycopg blocker 우회 근거 부족으로 보류 |

## Exact Psycopg artifacts

`psycopg` 3.3.4 universal wheel SHA-256은
`b6bbc25ccf05c8fad3b061d9db2ef0909a555171b84b07f29458a447253d679a`다. `psycopg-binary` 3.3.4의
CPython 3.10/3.11/3.12 Windows x86-64 hashes는 각각 `574ea21a…2949`, `41f2ec0f…ba8d`,
`494ca549…7be4`; manylinux x86-64 hashes는 `fa1cbc10…9765`, `ab8cca8e…49e4`, `e7510c37…c85d`다.
PyPI는 release artifact signature·attestation 또는 upstream SBOM을 이 Gate의 검증 가능한 필수 증거로 제공하지 않았다.

## Probe와 blocker

[확정] Windows CPython 3.12 import probe는 `psycopg 3.3.4`, implementation `binary`, bundled libpq runtime/build
`18.3`을 확인했다. exact Windows wheel은 OpenSSL `3.6.2`도 번들한다.

[확정] private Docker network, public port 0, synthetic credential/data로 수행한 Linux probe는 UTF-8/UTC metadata,
commit/rollback, parameter binding, composite FK/CHECK, advisory transaction lock, privilege denial와 connection cleanup을
통과했다. Linux manylinux wheel runtime libpq는 `18.0`이었다. task container/network/volume 잔존은 0이다.

[차단] PostgreSQL 공식 security authority에서 client High `CVE-2026-6477`, `CVE-2026-6475`는 18.4에서 수정됐다.
따라서 bundled libpq 18.0/18.3은 patched artifact가 아니다. OpenSSL 3.6.2도 3.6.3에서 수정된 High를 포함한다.
wheel filesystem Scout는 shared library package를 식별하지 못해 `indexed packages: 0`이었으므로 0 C/H 근거로 사용할 수 없다.

[차단] pure/C 후보는 이 bundled risk를 피하지만 Windows와 Linux의 exact patched system libpq 공급 주체, artifact hash,
설치 절차와 update owner가 아직 없다. 그러므로 현재 어떤 후보도 provenance/security Gate를 완전히 통과하지 못했다.

## 다음 evidence

1. Python 3.10–3.12 Windows/Linux용 patched libpq의 exact supplier, version, artifact hash와 설치 contract를 승인하거나,
2. libpq 18.4+와 OpenSSL 3.6.3+를 번들한 새 official Psycopg binary release를 기다리고 fresh scan·probe하거나,
3. exact binary wheel의 client/TLS High를 별도 symbol/runtime adjudication하되 사용자 승인 전 accepted로 만들지 않는다.

아래 historical 결론은 Practical Security Profile amendment로 대체되었다:
`psycopg_dependency_candidate_ready: true`, `psycopg_dependency_approval_required: false`. dependency/lockfile, migration,
SQL, schema와 production activation 변경은 0이다.
