# DohaLM 테스트 전략

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-08-30 |
| 선행 문서 | [개발 규칙](../governance/development-rules.md), [개발 로드맵](./development-roadmap.md), [Definition of Ready](../governance/definition-of-ready.md), [Definition of Done](../governance/definition-of-done.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서 | [테스트 체크리스트](./testing-checklist.md), 실제 test 구현 [검증 필요] |
| 구현 전 필수 여부 | 예 |

- [확정] 테스트 구현과 workflow는 영역별로 점진 도입하며, 이 문서는 수준·환경·데이터·실패 처리의 공통 기준이다.

## 2. 테스트 수준

| 수준 | 목적 | 예시 | 기본 실행 환경 |
|---|---|---|---|
| Static validation | 실행 전 문서·schema·경로·수치 검사 | Markdown 링크, config field, parameter 산식 | CPU |
| Unit test | 함수·layer의 단일 책임 검증 | mask, shape, loss 집계, parser | CPU 우선 |
| Component test | 연관 모듈 계약 검증 | tokenizer wrapper, block, dataset, checkpoint writer | CPU/GPU 선택 |
| Integration test | 여러 경계의 연결 검증 | data→model→trainer, save→load→resume, API→inference | CPU/GPU |
| Smoke test | 최소 비용으로 실행 가능성 확인 | 한 batch forward/backward, 짧은 generation | CPU 후 GPU |
| Regression test | 승인 기준선의 악화 탐지 | parameter count, output, ID, schema, fixed seed | CPU/GPU |
| Performance test | 시간·처리량·메모리 측정 | tokens/sec, latency, checkpoint size | 동일 환경 |
| GPU test | CUDA·FP16·VRAM 특화 검증 | AMP, checkpointing, OOM 경계 | RTX 3060 Ti 8GB |
| Manual evaluation | 자동화하기 어려운 품질·위험 검토 | 한국어 생성, 데이터 표본, 안전성 | 사람 검토 |

- [확정] 낮은 수준 test를 통과해도 통합·GPU·사람 평가가 자동으로 통과한 것으로 간주하지 않는다.

## 3. CPU와 GPU 테스트 분리

### 3.1 CPU에서 가능한 테스트

- [확정] 설정 parsing·validation·override와 resolved config
- [확정] tensor shape, causal mask와 작은 forward/backward
- [확정] tokenizer 학습의 소형 fixture 후보, encode/decode·special ID
- [확정] 데이터 parsing·정제·checksum·split·누수 fixture
- [확정] checkpoint schema·필수 key·CPU round-trip
- [확정] loss·perplexity 집계와 generation의 소형 deterministic 경로
- [확정] Markdown 링크·문서 상태·수치 정합성

### 3.2 GPU가 필요한 테스트

- [확정] CUDA FP16 autocast·GradScaler와 NaN/Inf 처리
- [확정] CUDA allocated/reserved/peak memory와 실제 OOM 경계
- [확정] block Gradient Checkpointing on/off의 loss·gradient·처리량
- [확정] 실제 token throughput·step time·생성 latency
- [확정] GPU checkpoint/resume와 RNG 차이
- [확정] 여러 step·장시간 안정성과 allocator·memory leak

- [확정] GitHub 기본 runner에서 GPU test를 실행할 수 있다고 가정하지 않는다.
- [확정] GPU test가 실행되지 않았으면 CPU test 통과와 별도로 `not_run` 또는 `blocked`로 보고한다.
- [검증 필요] 향후 GPU runner·수동 실행·결과 업로드 방식은 운영 환경 확인 후 결정한다.

## 4. 테스트 데이터

| 유형 | 용도 | 사용 원칙 |
|---|---|---|
| 가상 데이터 | 오류·schema·안전한 경계 test | 실제 데이터로 오해되지 않게 표시, 비밀·개인정보 없음 |
| 극소량 fixture | deterministic unit·integration·overfit | Git 가능 여부·라이선스·크기 검토, ID·expected 결과 고정 |
| 승인 데이터 sample | 실제 형식·token 품질·전처리 회귀 | registry 승인·접근 제한·재배포 조건 준수 |
| 실제 validation split | 모델 checkpoint 평가 | 전체 학습 test에 사용하지 않고 version·fingerprint 고정 |

- [확정] test에 실제 학습 데이터 전체를 사용하지 않는다.
- [확정] validation/test 데이터를 학습·overfit fixture로 사용하지 않는다.
- [확정] 실제 sample이 필요한 test는 라이선스·개인정보·Git 추적 가능성을 먼저 검토한다.

## 5. 회귀 테스트

| 계약 | 고정 기준 | 변경 시 처리 |
|---|---|---|
| 파라미터 수 | Tiny 16,889,856 | 구조 변경 ADR 또는 실패 |
| output shape | `[B,T,16000]` 등 설계 shape | interface 영향 검토 |
| causal mask | 미래 정보 차단 fixture | 즉시 모델 Gate 실패 |
| loss | shift·ignore_index·유효 token mean | 평가·학습 결과 무효 가능 |
| generation seed | prompt·config·seed·환경 | 비결정 한계와 승인 baseline 갱신 |
| checkpoint schema | format/version·필수 key·alias | migration 또는 명시 비호환 |
| tokenizer special ID | ID 0~7과 단일 token | checkpoint·data 비호환 검토 |
| 데이터 fingerprint | fixture·manifest hash | 전처리/split version 갱신 |
| API schema | request/response·오류·stream event | client·frontend 호환 검토 |

- [확정] 기준선 갱신은 test를 통과시키기 위한 무근거 변경이 아니라 승인된 사양·ADR·결과에 근거한다.

## 6. 실패 정책

- [확정] 필수 test 실패 상태에서 작업·Gate·version을 완료 처리하지 않는다.
- [확정] skip은 사유, 영향, 책임자와 재실행 조건을 기록하고 `pass`로 세지 않는다.
- [확정] flaky test는 반복 증거, 비결정 원인, 격리 범위와 제거 계획이 있을 때만 임시 허용 후보로 둔다.
- [확정] GPU test 미실행을 명시하고 GPU 기능·성능·메모리 완료를 주장하지 않는다.
- [확정] 예상 실패는 요구사항으로 정의된 오류 입력의 성공적 거부와 실제 test failure를 구분한다.
- [확정] 기존부터 실패한 test를 숨기거나 삭제하지 않고 baseline 상태·현재 영향과 사용자 결정을 보고한다.
- [확정] 로그·artifact 손상이나 평가 누수가 있으면 결과를 `invalid`로 처리한다.

## 7. 자동화 우선순위

1. [확정] 빠른 static·unit CPU test
2. [확정] component·integration CPU test
3. [확정] 짧은 GPU smoke·AMP·memory test
4. [확정] regression·performance·장시간 GPU test
5. [확정] 사람 생성·데이터 품질 평가

### 7.1 Dataset Governance CI

- [확정] `.github/workflows/dataset-governance.yml`의 `Dataset Governance Unit / Publication` check는 모든 pull request에서 생성한다.
- [확정] Dataset 관련 경로가 바뀌면 빠른 권한·거버넌스·Publication 회귀와 Publication 멀티프로세스 회귀를 분리된 step으로 실행하고, 무관한 변경이면 heavy step을 생략한 cheap success를 보고한다.
- [확정] cheap success 경로는 checkout, changed-path 분류, 확인 step만 실행하며 Python setup과 Dataset dependency 설치를 생략한다.
- [확정] Dataset unit discovery는 `tests/test_dataset_*.py`, `tests/test_product_dataset_*.py`, Common 계약 테스트를 자동 포함하되 Publication process는 별도 실행하고 Training/Torch 경계인 `tests/test_dataset_training_*.py`는 제외한다.
- [확정] PostgreSQL adapter·migration 통합 검증은 기존 C1/C2 workflow 책임으로 유지하며, pure Dataset 변경에 PostgreSQL service를 강제하지 않는다.
- [확정] Python 3.12 Ubuntu runner에서 Common 계약, PyYAML, pytest, Ruff만 설치하고 Training·Transformers·GPU dependency와 production secret은 사용하지 않는다.
- [확정] 정적 검사는 관련 Dataset Governance 파일의 critical Ruff 규칙, format, compile/import와 patch whitespace를 검사한다. 저장소 전체 Ruff debt는 이 workflow에서 새 blocker로 만들지 않는다.
- [확정] ADR·project 문서만 바뀐 경우 Dataset heavy regression은 실행하지 않지만 동일 check context는 cheap success로 존재하며 Markdown 문서 검증 정책을 별도로 적용한다.
- [확정] repository ruleset `Dataset Governance required check (develop)`(ID `21693103`)은 `develop`에 `Dataset Governance Unit / Publication`과 `C1 PostgreSQL Contract`를 required status check로 요구한다. 두 context는 모두 GitHub Actions App(`integration_id 15368`)에 binding되며 enforcement source는 classic branch protection이 아니라 repository ruleset이다.
- [확정] ruleset의 strict/up-to-date 정책은 `false`이며 required pull request, approving review와 approval count는 설정하지 않는다.
- [확정] C1 workflow의 `C1 PostgreSQL Contract` context는 모든 pull request와 `develop` push에서 생성하며 required status check로 적용한다. 관련 경로는 PostgreSQL heavy regression을 실행하고 무관한 경로는 dependency·Docker 없이 cheap success를 보고하므로, required 적용이 모든 pull request의 heavy 실행을 의미하지는 않는다.
- [확정] C2 workflow의 `C2 PostgreSQL Training Adapters` context는 모든 pull request와 `develop` push에서 생성하되 non-required 상태를 유지한다. pull request에서는 기존 C2/C3/Host/PostgreSQL 관련 경로를 내부 classifier로 판정해 관련 변경이면 heavy regression을 실행하고 무관한 변경이면 dependency·PostgreSQL·test 없이 cheap success를 보고한다. `develop` push에서는 변경 경로와 무관하게 항상 heavy regression을 실행한다.
- [확정] Training workflow의 `Local Training Activation Contract` context는 고유하며 path-filtered·non-required 상태와 enforcement HOLD를 유지한다.
- [확정] `RepositoryRole` admin(`actor_id 5`)만 ruleset을 `always` bypass할 수 있으며 일반 contributor bypass를 허용하지 않는다.

| 변경 경로 | Dataset Unit | Publication Process | C1 | C2 | Training |
|---|---|---|---|---|---|
| `src/data/dataset_publication.py` 등 pure Dataset Governance | 예 | 예 | 생략(check success) | 생략(check success) | 아니요 |
| `tests/test_dataset_*.py`, `tests/test_product_dataset_*.py` | 예 | 관련 process 경로이면 예 | 생략(check success) | 생략(check success) | 아니요 |
| Dataset Proposal/Review PostgreSQL adapter | 예 | 예 | 예 | 예 | 아니요 |
| `src/postgres_migrations/**`, `tests/test_postgres_c1*.py` | 아니요 | 아니요 | 예 | 예 | `tests/test_postgres_c1_integration.py`만 예 |
| `tests/test_postgres_c2*.py`, `tests/test_postgres_c3*.py` | 아니요 | 아니요 | 생략(check success) | 예 | 아니요 |
| 선택된 `src/training/**`와 Training 테스트 | 아니요 | 아니요 | 생략(check success) | 기존 C2 classifier 관련 경로이면 예, 아니면 생략(check success) | 예 |
| Dataset governance ADR·project docs only | 생략(check success) | 생략 | 생략(check success) | 생략(check success) | 아니요 |
| `.github/workflows/dataset-governance.yml` | 예 | 예 | 생략(check success) | 생략(check success) | 아니요 |

- [검증 필요] Dataset Governance 외 영역의 통합 CI matrix, coverage 임계값과 전체 합격 시간은 후속 결정한다.
- [확정] Local Training workflow는 shared PostgreSQL/C3 fixture 계약인 `tests/test_postgres_c1_integration.py`가 변경될 때도 실행한다.
- [확정] C1 heavy classifier는 normalization 전 pull request·push path filter의 workflow, dependency, C1 source·migration, Proposal/Review PostgreSQL adapter와 `tests/test_postgres_c1*.py` 범위를 그대로 보존하며 추가·수정·복사·이름 변경·삭제를 모두 감지한다.
- [확정] C2 heavy classifier는 normalization 전 pull request·push path filter의 20개 workflow, dependency, C2/C3/Host source·test, migration, Proposal/Review PostgreSQL adapter와 C1 shared fixture 범위를 그대로 보존하며 추가·수정·복사·이름 변경·삭제를 모두 감지한다.

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-30 | [확정] C2 PostgreSQL check를 always-present, pull request path-aware heavy/cheap, `develop` push always-heavy, non-required 구조로 정규화 |
| 2026-08-29 | [확정] live repository ruleset에 맞춰 Dataset과 C1을 `develop` required status check로, C2·Training을 non-required로 동기화 |
| 2026-08-29 | [확정] C1 PostgreSQL check를 always-present, path-aware heavy/cheap, non-required 구조로 정규화 |
| 2026-08-29 | [확정] shared PostgreSQL/C3 fixture 변경을 Local Training workflow의 pull request·push trigger에 포함 |
| 2026-08-28 | [확정] C1·C2·Training의 중복 `contract` context를 workflow별 고유 check 이름으로 분리하고 path-filtered·non-required 경계를 유지 |
| 2026-08-28 | [확정] `develop` 대상 Dataset Governance required status check repository ruleset과 strict·PR·review·admin bypass·C1/C2/Training 비적용 경계를 동기화 |
| 2026-08-27 | [확정] Dataset Governance always-present check, path-aware heavy regression, bounded test 자동 discovery와 cheap success 경계 추가 |
| 2026-08-26 | [확정] Dataset Governance 전용 unit·Publication process CI 범위, PostgreSQL·Training·docs-only 경계와 changed-path matrix 추가 |
| 2026-07-23 | [확정] 9개 test 수준, CPU/GPU 경계, test data, 회귀와 실패 정책 정의 |
