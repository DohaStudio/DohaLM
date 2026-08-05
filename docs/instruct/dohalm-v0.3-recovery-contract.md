# DohaLM General Instruct v0.3 V03-1·V03-2 Recovery Contract

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 브랜치·커밋: `develop` · `a42f02f3fef8257e1350a3c3ee5ff7fb37d6ac43`
- 계약 설계 상태: `design_completed`
- V03-1 evidence 상태: `pending`
- V03-2 fresh tokenization 상태: `not_approved`
- V03-R1 schema·writer·finalizer 상태: `implemented_synthetic_validated`
- 실제 V03 evidence bundle 상태: `not_created`
- 실행 권한: `false`
- 선행 문서: [v0.3 학습 재개 Readiness](./dohalm-v0.3-training-readiness.md), [v0.3 Tokenization Readiness](./dohalm-v0.3-tokenization-readiness.md), [publish 실패 보존 계약](./dohalm-v0.3-tokenization-publish-failure.md)
- 관련 결정: [ADR-004](../decisions/ADR-004-data-governance.md), [ADR-010](../decisions/ADR-010-dohalm-instruct-strategy.md)

## 1. 목적과 비목표

[확정] 이 문서는 V03-1 데이터 evidence와 V03-2 fresh tokenization의 실행 전 계약을 정의한다. 기존
`DOHALM-V0.3-TOKENIZATION-20260802-0001`을 재개·retry·replay하거나 그 identity surface를 복원하는 계약이 아니다.
새 실행은 새 Run ID·새 단일 사용 Approval·새 RuntimeExecutionRequest를 사용하는 별도 canonical execution이다.

[제외] 이번 단계에서는 Dataset·scan·exclusion manifest·Approval·Runtime request·Tokenization artifact를 생성하지
않는다. payload read, Tokenization, publish, GPU, QLoRA, Adapter manifest, Provider·FastAPI·Frontend 변경, 네트워크,
commit과 push를 수행하지 않는다.

```yaml
v0.3_recovery_contract: design_completed
v0.3_data_evidence: pending
v0.3_fresh_tokenization: not_approved
v0.3_training: not_started
execution_allowed: false
```

## 2. 확인한 기존 근거와 재사용 경계

| 근거 | 확인 상태 | V03에서의 사용 |
|---|---|---|
| v0.3 Short Answer package | Dataset ID, 17,639/1,287행, package·manifest fingerprint와 8-file checksum inventory 존재 | V03-1의 immutable 입력 후보. 새 evidence가 통과하기 전 학습 입력 승인 아님 |
| Run 0010~0014 Processing 이력 | 현재 상태 문서는 preflight·retirement 감사 이력으로 요약하지만 현재 checkout과 탐색 가능한 외부 root에서 개별 evidence artifact를 찾지 못함 | 성공·승인 근거로 사용하지 않음. V03-1 lineage bundle에서 위치·checksum을 확인하거나 `not_available`로 명시 |
| Run 0015 Processing 계보 | v0.3·v0.2·v0.1 downstream manifest가 `AIHUB-71748-SFT-PROCESSING-20260730-0015`와 source checksum을 기록; 개별 Processing root는 현재 환경에서 직접 resolve하지 못함 | transitive provenance만 조건부 계승. 독립 evidence 위치·checksum 확인 전 포괄 승인이나 재처리 근거로 사용 금지 |
| 기존 PII scan | 원천 SFT component에 대한 aggregate 후보 4,390건, critical 0 | v0.3 accepted package의 독립 PII clear가 아님 |
| 기존 leakage scan | Train/Validation 후보 1,741 pair, 외부 benchmark source 없음 | source 위험 설명용. v0.3와 고정 평가 집합의 독립 검사 필요 |
| 기존 Safety 문서 | threat model 설계 완료, 실제 safety dataset·평가 미승인 | category·review 설계 입력. 통과 evidence 아님 |
| Processing Approval v2 | single-use, lifecycle lock, checksum, atomic no-replace와 retirement 구현 | primitive와 실패 원칙만 재사용 후보 |
| RuntimeExecutionRequest v1 | nonce·TTL·fingerprint·no-replace 구현 | issuance 원칙만 재사용 후보 |
| v0.3 hardened publisher | stage heartbeat, failure artifact, 단계별 no-replace synthetic 검증 | V03-R7·R8 기반. 기존 실패 root cause 해결 증명은 아님 |

[확정] 현재 `ApprovalRecord v2`와 `RuntimeExecutionRequest v1`은 Processing 전용이다. Dataset/component·예산이
고정되고 `tokenization_allowed=true`를 거부하므로 v0.3 Tokenization에 그대로 사용하면 안 된다. 기존 schema를
소급 변경하지 않고 별도 action-scoped schema를 만든다. 공통 atomic writer·lifecycle lock을 추출해 재사용하는 것은
후속 구현 검토 대상이다.

[검증 필요] Run 0010~0015의 비공개 evidence root가 별도로 보존돼 있다면 V03-R1에서 read-only inventory와 checksum을
연결해야 한다. 찾을 수 없다는 사실을 성공 evidence 부재나 Run 미실행으로 단정하지 않으며, downstream manifest에
기록된 Run 0015 계보도 독립 Approval·request·processing-result artifact를 대신하지 않는다.

## 3. V03-1 라이선스 계약

### 3.1 실제 근거 판정

| 항목 | 현재 근거 | 판정 |
|---|---|---|
| AIHUB-71748 사용 범위 | 사용자 결정으로 학생·비상업 연구·개인 학습 범위 기록 | `conditionally_supported` |
| 취득 승인·당시 조건 | 신청 ID, 승인 일시·목적, 당시 약관 snapshot을 로컬에서 찾지 못함 | `evidence_missing` |
| SFTdata/SFTlabel 사용 | Terms Review와 Approval Log 모두 SFT `not_approved` | `not_approved` |
| 파생 데이터 생성 | 일반 정책만으로 SFT 정제·short variant 생성 권리를 확정하지 못함 | `verification_required` |
| 파생 Adapter 생성 | SFT 목적 및 파생 weight 조건이 미확정 | `not_approved` |
| 로컬 개인 사용 | 일반 범위는 조건부 지원되나 SFT 목적을 자동 포함하지 않음 | `purpose_approval_required` |
| 원본·파생 데이터 공개 | 모두 `not_approved` | `prohibited_by_project_policy` |
| checkpoint·Adapter 공개 | 공식 조건 미확정, 프로젝트 승인 없음 | `not_approved` |
| 외부 서비스·해외 cloud | 제3자 제공·국외 반출 조건 미확정 | `not_approved` |
| DohaMusic 등 다른 프로젝트 | 현재 목적·접근자·보관 범위와 다름 | `new_purpose_approval_required` |
| 상업 목적 전환 | 현재 비상업 범위 밖 | `new_provider_or_legal_approval_required` |

**라이선스 판정: `evidence_insufficient`**

[확정] 이는 이용조건이 SFT를 명시적으로 금지한다고 단정하는 `license_blocking` 판정이 아니다. SFT와 파생
Adapter를 허용한다고 입증할 증거가 부족하므로 실행은 동일하게 Fail Closed한다.

### 3.2 V03-1에 필요한 라이선스 evidence

`license-evidence.json`은 다음을 식별해야 한다.

- 제공자와 Dataset 71748 version, 로컬 ZIP inventory와의 대응 관계
- 비공개 다운로드 신청·승인 artifact의 경로 대신 artifact ID·SHA-256·보관 책임자
- 취득 당시 이용조건 snapshot의 ID·SHA-256·적용일
- 허용 목적: 학생·비상업 로컬 SFT와 파생 Adapter 생성 여부
- 금지 목적: 공개·재배포·외부 서비스·국외 처리·상업 사용
- 원본·정제본·tokenized data·checkpoint·Adapter별 공개 가능성
- attribution 문구와 적용 위치
- 보관 위치·접근자·폐기 및 개인정보 사고 대응
- DohaMusic 등 목적 변경 시 재승인 필요 여부
- 공식 회신 또는 사용자·법률 검토자의 결정 ID, 결정일과 만료·재검토 조건

[확정] 개인정보나 승인 화면 원문을 Git artifact에 넣지 않는다. 비공개 원본은 제한 저장소에 두고 evidence에는
ID·checksum·결정 요약만 기록한다.

## 4. 독립 PII 검증 계약

### 4.1 검사 범위

- 주민등록·외국인등록번호와 유사 번호
- 전화번호, 이메일, 상세 주소
- 계좌·카드·여권·면허 번호
- 실명과 학교·회사·병원·부서·직책 조합
- 사용자·환자·학생·직원 ID와 social handle
- URL query/path 안의 개인 식별자
- 자유서술형 의료·정신건강·법률·금융·종교·정치 등 민감정보의 개인 귀속
- 질문·답변 조합이나 short variant로 원문 개인 문맥을 복원할 가능성

### 4.2 Artifact schema

`pii-scan-summary.json`은 검사기 version, policy version, split·variant별 scan 수, category·severity별 집계,
automatic/manual 수, unresolved 수와 input/output fingerprint만 포함한다. 원문·부분 문자열·token 배열·직접 식별값을
포함하지 않는다.

`pii-findings.jsonl`의 각 행은 다음 최소 필드를 가진다.

```json
{"schema_version":1,"finding_id":"opaque-id","record_ref":"sha256:<record-ref>","split":"train","variant":"short","detector":"email","detection_mode":"automatic","severity":"high","disposition":"review_required","evidence_hash":"sha256:<hash>","review_required":true}
```

`record_ref`는 Dataset 내부 안정 ID를 HMAC 또는 별도 salt가 있는 one-way reference로 변환한 값이다. raw record hash가
사전 공격으로 원문을 드러낼 가능성이 있으면 사용하지 않는다. salt·key는 artifact에 저장하지 않는다.

`pii-exclusion-manifest.json`은 제외된 `record_ref`, reason code, finding ID, source/variant 관계만 보존한다.
`pii-review-evidence.json`은 reviewer role, review protocol, reviewed count, disposition 집계, unresolved count,
완료 시각과 evidence fingerprint를 기록하고 원문을 복제하지 않는다.

### 4.3 Severity·disposition과 Gate

| Severity | 허용 disposition | V03-1 조건 |
|---|---|---|
| `critical` | `exclude`, `provider_incident`, `false_positive_confirmed` | unresolved 0, retain 금지 |
| `high` | `exclude`, `false_positive_confirmed` | unresolved 0, retain은 별도 정책 승인 없이는 금지 |
| `medium` | `exclude`, `retain_with_review`, `false_positive_confirmed` | 수동 검토자·reason code·evidence 필수 |
| `low` | `retain`, `exclude`, `false_positive_confirmed` | 자동 결과와 정책 version 기록 |

[확정] V03-1 통과에는 모든 finding의 disposition이 필요하다. `unresolved_total=0`, unresolved critical/high=0,
unknown detector=0, scan·review artifact checksum 일치가 필수다. 단순히 critical 0건인 기존 source scan으로 통과하지 않는다.

## 5. 독립 Safety 검증 계약

### 5.1 필수 category

- 자해·자살
- 폭력·무기
- 성적 콘텐츠
- 혐오·괴롭힘
- 불법 행위
- 개인정보·재식별
- 의료·법률·금융 고위험 조언
- 아동 관련 민감·성적·착취 콘텐츠
- prompt injection, role spoofing과 system-like content
- evaluation prompt·benchmark contamination

`safety-scan-summary.json`, `safety-findings.jsonl`, `safety-exclusion-manifest.json`,
`safety-review-evidence.json`은 PII artifact와 동일한 비노출·fingerprint·automatic/manual review 원칙을 따른다.
finding에는 `category`, `severity`, `policy_label`, `disposition`, `reviewer_required`를 추가한다.

### 5.2 Gate

- unresolved `critical`·`high`: 0건
- `critical`: 학습 유지 금지, 제외 또는 Dataset 전체 차단
- `high`: 수동 검토와 명시적 `exclude` 또는 승인된 안전 학습 목적이 없으면 제외
- `medium`: category별 허용 정책·review evidence·reason code가 있을 때만 유지
- prompt injection·system-like content: 기본 제외, 별도 adversarial-training 목적 승인 없이는 유지 금지
- evaluation contamination: 학습 제외 또는 평가 집합 교체가 확정되기 전 차단
- unknown category·severity·disposition: Fail Closed

[확정] canonical Dataset 파일은 수정하지 않는다. PII·Safety 제외를 합친 결정론적 selection view를 만든다.

```text
effective_dataset_fingerprint = SHA256(
  canonical_dataset_package_fingerprint
  + evaluation_exclusion_manifest_fingerprint
)
```

Tokenization은 canonical package fingerprint와 effective fingerprint를 모두 기록한다. exclusion manifest가 바뀌면
새 evidence bundle·새 effective fingerprint·새 Tokenization Run이 필요하다.

[확정] V03-R1 core bundle에는 PII·Safety 개별 exclusion manifest가 아직 없으므로 PII 또는 Safety
`excluded_count > 0`인 evidence를 `ready`나 `ready_with_conditions`로 finalization하지 않는다. R1에서 effective
fingerprint는 canonical package와 evaluation exclusion manifest만으로 계산한다. 실제 PII·Safety exclusion이 필요한
경우 V03-R2에서 opaque reference 기반 manifest를 추가하고 schema version과 계산식을 함께 올린 뒤에만 실행한다.

## 6. 평가 누수 검증 계약

### 6.1 입력과 검사

- v0.3 Train과 Validation의 exact·Unicode/whitespace normalized duplicate
- 승인된 알고리즘·threshold의 near duplicate
- 질문끼리의 prompt overlap과 답변끼리의 answer overlap
- QA pair와 의미상 동일 문제 후보
- benchmark template·지시문·보기 구조 contamination
- v0.1/v0.2 고정 evaluation·decoding prompt와의 exact·normalized·near overlap
- 새 v0.3 평가 prompt와 외부 benchmark의 고정 version·license·fingerprint

`leakage-scan-summary.json`, `leakage-findings.jsonl`, `evaluation-exclusion-manifest.json`을 생성한다. 외부 benchmark
원문은 bundle에 포함하지 않고 source ID, version, license, checksum과 제한 보관 위치의 logical ID만 기록한다.

### 6.2 Gate

- Train/Validation exact·normalized QA overlap: 미해결 0
- 고정 evaluation prompt/answer exact·normalized overlap: 미해결 0
- near·template candidate: 모두 review disposition 필요
- 학습 유지로 판정한 near candidate: reviewer, threshold version, reason code 필요
- benchmark source/version 또는 fingerprint 부재: `BENCHMARK_SOURCE_NOT_FIXED`
- v0.1/v0.2 prompt inventory 누락: `HISTORICAL_EVALUATION_INVENTORY_MISSING`
- exclusion 적용 후 Train·Validation 최소 크기와 category 분포 guardrail 재검증
- scan input fingerprint와 effective dataset 계산 입력이 다르면 Fail Closed

## 7. V03-1 Evidence Bundle

Canonical 논리 구조는 다음과 같다. 실제 root와 identity는 실행 승인 때 정한다.

```text
v03-data-readiness-bundle/
├── license-evidence.json
├── dataset-lineage.json
├── checksum-inventory.json
├── pii-scan-summary.json
├── pii-review-evidence.json
├── safety-scan-summary.json
├── safety-review-evidence.json
├── leakage-scan-summary.json
├── evaluation-exclusion-manifest.json
└── readiness-decision.json
```

[확정] 위 10개 파일은 V03-R1 core bundle의 정확한 파일 집합이다. `pii-findings.jsonl`,
`pii-exclusion-manifest.json`, `safety-findings.jsonl`, `safety-exclusion-manifest.json`,
`leakage-findings.jsonl`과 별도 `bundle-manifest.json`은 V03-R2 이후 후보이며 현재 finalizer 입력이 아니다.
R1 artifact에는 원문·부분 문자열·실제 record ID·절대 로컬 경로를 저장하지 않는다.

### 7.1 공통 envelope

모든 JSON/JSONL artifact는 파일 자체 checksum과 별도로 다음 의미 필드를 갖는다.

| 필드 | 계약 |
|---|---|
| `schema_version` | artifact 종류별 정수 version; unknown major 차단 |
| `artifact_type` | 고정 allowlist 값 |
| `artifact_id`, `run_id`, `dataset_id` | 비어 있지 않은 고정 identity |
| `writer_name`, `writer_version` | module ID와 writer version |
| `input_fingerprint` | 현재 artifact 입력의 `sha256:<64 lowercase hex>` |
| `output_fingerprint` | checksum 필드를 제외한 canonical payload SHA-256 |
| `created_at` | UTC timezone-aware 시각 |
| `source_commit` | clean `origin/develop` reachable 40-char commit |
| `payload` | artifact 종류별 exact object; unknown field 차단 |
| `approval_status`, `reviewer`, `decision` | 승인과 판정을 분리하며 review artifact는 reviewer 필수 |
| `predecessor_artifact_id` | 선행 artifact가 없으면 `null`, 있으면 고정 identity |
| `artifact_checksum` | 이 필드 자체를 빈 문자열로 두고 계산한 canonical artifact SHA-256 |

[확정] canonical JSON은 UTF-8, key 정렬, `(',', ':')` separator, `ensure_ascii=false`,
`allow_nan=false`, 후행 newline 없음이다. strict loader는 duplicate key, NaN·Infinity, unknown field,
bool-as-int, 비표준 timestamp·Git SHA·fingerprint, 비정규 직렬화를 모두 차단한다.

### 7.2 Writer와 재실행 정책

| Artifact 그룹 | Writer 후보 | 승인 주체 | 재실행 정책 |
|---|---|---|---|
| License·lineage·checksum | V03-R1 evidence writer | 사용자 또는 지정 data owner | 입력·조건 변경 시 새 evidence Run; 기존 덮어쓰기 금지 |
| PII | V03-R2 PII scanner/review writer | 사용자 + privacy reviewer | 같은 Run 재실행 금지; 실패·정책 변경 시 새 Run |
| Safety | V03-R2 Safety scanner/review writer | 사용자 + safety owner | 같은 Run 재실행 금지; 실패·정책 변경 시 새 Run |
| Leakage | V03-R2 Leakage scanner/review writer | 사용자 + evaluation owner | benchmark/prompt 변경 시 새 Run |
| Readiness decision | V03-R1 bundle finalizer | 사용자 | 모든 입력 immutable·통과일 때 1회 publish |

모든 writer는 same-directory exclusive temp, complete write, flush, file fsync, atomic no-replace publish, 지원되는
플랫폼의 parent directory fsync, reload와 checksum 검증을 적용한다. overwrite·silent fallback·부분 성공은 금지한다.
V03-R1 writer는 이미 존재하는 명시적 bundle root의 직접 자식만 쓰며 destination·root symlink를 거부한다.
finalizer는 자동 탐색이나 bundle 쓰기를 하지 않고 정확한 10-file set을 strict load한다. readiness 이전 9개
artifact checksum의 정렬된 map을 bundle fingerprint로 계산하고 `readiness-decision.json`이 이를 참조한다.
순환 fingerprint를 피하기 위해 readiness 자체는 bundle fingerprint 입력에서 제외하며, 별도 completion marker는
만들지 않고 readiness artifact checksum을 완료 증거로 사용한다.

### 7.3 V03-1 최종 결정

`readiness-decision.json`의 `overall_decision`은 `ready`, `ready_with_conditions`, `blocked`,
`evidence_insufficient` 중 하나다. `ready`와 `ready_with_conditions`는 다음을 모두 요구한다.

1. License가 최소 `license_ready_with_conditions`이며 조건이 local/noncommercial Tokenization·SFT를 명시적으로 허용
2. Dataset lineage·기존 checksum과 package fingerprint 일치
3. PII·Safety unresolved 0, critical/high Gate 충족
4. Leakage disposition 완료와 benchmark source 고정
5. exclusion 적용 후 effective Dataset fingerprint 확정
6. 모든 artifact의 schema·source commit·writer·checksum·fingerprint와 승인 주체 일치

`ready_with_conditions`는 blocking reason 없이 하나 이상의 conditional reason이 있고, license가 최소
`ready_with_conditions`, 나머지 component가 모두 `passed`일 때만 허용한다. `blocked`와
`evidence_insufficient`는 blocking reason이 필수이며 approved next action을 가질 수 없다. 승인·금지 action의
충돌과 실제 evidence보다 강한 readiness 판정은 `V03_EVIDENCE_READINESS_CONTRADICTION`으로 차단한다.

### 7.4 V03-R1 오류 계약

외부로 전달할 수 있는 오류 문자열은 payload나 경로가 아닌 고정 code뿐이다. core loader·finalizer code는
`V03_EVIDENCE_NOT_FOUND`, `V03_EVIDENCE_INVALID`, `V03_EVIDENCE_UNSUPPORTED_VERSION`,
`V03_EVIDENCE_PATH_INVALID`, `V03_EVIDENCE_CHECKSUM_MISMATCH`, `V03_EVIDENCE_BUNDLE_INCOMPLETE`,
`V03_EVIDENCE_BUNDLE_INCONSISTENT`, `V03_EVIDENCE_READINESS_CONTRADICTION`이다. writer는 여기에
`V03_EVIDENCE_ALREADY_EXISTS`, `V03_EVIDENCE_TEMPORARY_COLLISION`,
`V03_EVIDENCE_NO_REPLACE_UNSUPPORTED`, `V03_EVIDENCE_ATOMIC_WRITE_FAILED`,
`V03_EVIDENCE_WRITE_INCOMPLETE`를 사용한다. 오류 message에는 전체 경로·원문·artifact payload를 넣지 않는다.

## 8. 새 Tokenization Run Identity

형식은 `DOHALM-V0.3-TOKENIZATION-YYYYMMDD-NNNN`이다.

- 날짜는 예약 순간의 `Asia/Seoul` 달력 날짜다. `created_at`은 별도로 UTC를 기록한다.
- sequence는 canonical identity ledger와 reservation에서 같은 날짜의 모든
  `reserved/committed/completed/failed/abandoned/retired` canonical execution 중 최대값+1이다. 날짜가 바뀌면
  `0001`부터 시작하지만 전체 문자열 중복은 계속 검사한다. `predecessor_failure_reference`는 sequence 계산에서 제외한다.
- directory listing만으로 sequence를 결정하지 않는다. final·staging·failed·emergency·reservation·Approval·request·
  registry와 역사 ledger를 모두 검사한다.
- 구현은 호출자가 지정한 절대 ledger root만 사용하고 discovery와 symlink를 거부한다. 논리 구조는
  `ledger.jsonl`, `reservations/<reservation-id>.json`, `committed/<run-id>.json`, `retired/<run-id>.json`이다.
- reservation writer는 ledger lifecycle lock 아래 ledger·reservation을 다시 읽고 inventory fingerprint freshness와
  전체 surface 충돌을 확인한다. reservation은 atomic no-replace로 게시하며 ledger는 기존 byte prefix를 보존한 전체
  generation을 임시 파일에 fsync한 뒤 atomic replace하고 strict reload한다. append 실패 시 이번 호출이 만든 reservation만
  정리하며, lock 경쟁에서는 한 호출만 성공한다.
- lock 충돌·stale lock은 자동 삭제하지 않는다. 수동 조사와 새 시도만 허용한다.
- 기존 `DOHALM-V0.3-TOKENIZATION-20260802-0001`은 영구 `retired_unresolved_publish`다.
- retry·resume·replay는 언제나 새 identity를 요구한다. 새 Run은 `attempt`가 아니라 `canonical_execution`이며
  `predecessor_run_id`, `predecessor_status`, `predecessor_failure_code`로 과거 실패를 연결한다.
- `abandoned`는 Approval 발급 전 예약 폐기, `retired`는 evidence 또는 Approval이 생긴 뒤 폐기를 뜻한다.
  어느 상태도 ID를 다시 사용 가능하게 만들지 않는다.

`V03Reservation` strict schema는 다음과 같다. 실제 파일은 canonical JSON으로 직렬화하며 unknown/missing field를 거부한다.

```yaml
schema_version: 1
reservation_id: null
run_id: null
ledger_root_id: null
source_commit: null
dataset_id: null
dataset_fingerprint: null
predecessor_run_id: DOHALM-V0.3-TOKENIZATION-20260802-0001
reserved_at: null
expires_at: null
owner_token_hash: null
reservation_nonce: null
reservation_fingerprint: null
reservation_checksum: null
status: active
```

ledger entry는 `reserved`, `committed`, `abandoned`, `retired`, `completed`, `failed` transition을 checksum이 있는
canonical JSONL row로 추가한다. `abandoned`와 `retired` sequence는 영구 소비된다. exact committed artifact 재호출만
idempotent하며 다른 payload는 거부한다. 완료 run retirement는 금지한다. predecessor는 자기 자신이 아니며 ledger의
`failed`/`retired` run 또는 명시적 historical failure reference여야 하고 lineage cycle을 허용하지 않는다. 신규 run의
kind와 purpose는 각각 `canonical_execution`, `canonical_recovery_execution`으로 고정하며 retry·resume·replay 의미를
부여하지 않는다.

외부 오류는 `V03_RUN_ID_INVALID`, `V03_RUN_ID_SEQUENCE_EXHAUSTED`, `V03_RUN_ID_CONFLICT`,
`V03_LEDGER_NOT_FOUND`, `V03_LEDGER_INVALID`, `V03_LEDGER_INCONSISTENT`, `V03_RESERVATION_INVALID`,
`V03_RESERVATION_ALREADY_EXISTS`, `V03_RESERVATION_EXPIRED`, `V03_RESERVATION_STATE_INVALID`,
`V03_RESERVATION_CHECKSUM_MISMATCH`, `V03_PREDECESSOR_INVALID`, `V03_IDENTITY_INVENTORY_STALE`,
`V03_IDENTITY_LOCK_FAILED` code만 노출한다.

## 9. Tokenization Approval 계약

### 9.1 기존 계약과의 관계

[확정] 신규 `TokenizationApproval v1`은 Processing `ApprovalRecord v2`를 재직렬화하거나 확장하지 않는다. 별도 schema와
경로를 사용하되 다음 구현 원칙을 재사용한다.

- stable identity fingerprint와 lifecycle-dependent checksum 분리
- approval별 lifecycle lock
- atomic no-replace issue
- request 발급·consume·retirement 상호 배제
- legacy/unknown schema 실행 차단
- publish 이후 불완전 상태의 자동 retry 금지

### 9.2 필수 필드

```yaml
schema_version: 1
approval_id: null
run_id: null
dataset_id: DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001
dataset_package_fingerprint: null
effective_dataset_fingerprint: null
tokenizer:
  model_id: Qwen/Qwen2.5-1.5B-Instruct
  revision: 989aa7980e4cf806f80c7fef2b1adb7bc71aa306
  inventory_fingerprint: null
  chat_template_fingerprint: null
base_revision: 989aa7980e4cf806f80c7fef2b1adb7bc71aa306
tokenization_config_fingerprint: null
backend_fingerprint: null
dependency_snapshot_fingerprint: null
source_commit: null
allowed_action: fresh_tokenization_publish
allowed_input_roots: []
allowed_output_roots: []
issued_at: null
expires_at: null
consumed_at: null
status: draft
approver: null
predecessor_failure_reference: DOHALM-V0.3-TOKENIZATION-20260802-0001
retry_allowed: false
resume_allowed: false
overwrite_allowed: false
maximum_consumptions: 1
stable_fingerprint: null
checksum: null
```

### 9.3 상태와 전이

```text
draft -> issued -> consumed
draft -> retired
issued -> retired
issued -> expired
```

- `draft`: 실행 권한 없음. 파일 존재만으로 발급을 의미하지 않는다.
- `issued`: 사용자 승인, identity·fingerprint·root·TTL 고정, 아직 미소비.
- `consumed`: request와 preflight를 lock 안에서 재검증한 뒤 payload 접근 직전에 단 한 번 전이.
- `retired`: identity drift, 코드·dependency 변경, 실행 실패 또는 사용자 폐기로 영구 종료.
- `expired`: 미소비 상태에서 TTL 경과. 재발급·소비 금지.

Approval 발급 자체는 Tokenization을 실행하지 않는다. issued 뒤 source commit, backend, dependency, Dataset,
Tokenizer, config, output root가 바뀌면 기존 Approval을 `retired` 처리하고 새 Run ID부터 시작한다. 실행 실패 뒤
Approval은 재사용하지 않는다.

## 10. TokenizationExecutionRequest 계약

신규 action-scoped request의 필수 schema는 다음과 같다.

```yaml
schema_version: 1
request_id: null
run_id: null
approval_id: null
approval_fingerprint: null
dataset_id: null
dataset_package_fingerprint: null
effective_dataset_fingerprint: null
tokenization_config_fingerprint: null
tokenizer_inventory_fingerprint: null
chat_template_fingerprint: null
backend_fingerprint: null
dependency_snapshot_fingerprint: null
source_commit: null
requested_output_root: null
expected_artifact_set: []
environment_requirements_fingerprint: null
created_at: null
expires_at: null
requested_by: null
nonce: null
request_checksum: null
```

검증 규칙은 다음과 같다.

- Approval의 모든 identity·fingerprint·allowed root·action과 exact match
- request ID·nonce·checksum·approval fingerprint의 과거 사용 이력 0
- request root는 예약된 Run의 canonical final root와 정확히 일치
- final·staging·failed·emergency·worker root와 conflicting reservation 부재
- current clean HEAD와 `source_commit` 일치, commit은 `origin/develop`에서 reachable
- backend execution surface와 dependency snapshot fingerprint 일치
- expected artifact set exact match, unknown file 금지
- timezone-aware 발급·만료와 최대 1시간 TTL
- canonical UTF-8, exact field set, atomic no-replace publish

Request 생성은 Approval을 소비하지 않는다. request 발급과 Approval retirement는 같은 lifecycle lock을 사용한다.

`expected_artifact_set`은 현재 writer 기준의 logical top-level entry를 다음처럼 정확히 고정한다. 하위 Hugging Face
Dataset 파일 inventory는 실행 시 dependency snapshot과 함께 확정하며 unknown top-level entry는 허용하지 않는다.

```yaml
expected_artifact_set:
  - train/
  - validation/
  - row-alignment.json
  - lineage-alignment.json
  - tokenization-manifest.yaml
  - tokenization-statistics.json
  - sampler-readiness.yaml
  - checksums.sha256
```

## 11. Metadata-only Preflight

### 11.1 허용 경계

[확정] metadata-only preflight는 JSONL/Arrow payload를 parse하거나 tokenization하지 않는다. 기존 checksum inventory,
manifest, 파일 존재·크기·filesystem metadata와 소형 evidence만 읽는다. payload byte를 다시 SHA-256하는 행위도 full
payload read이므로 이 단계에는 포함하지 않는다.

[확정] 따라서 preflight의 “checksum 검증”은 V03-1에서 이미 생성된 checksum evidence의 서명·fingerprint와 현재
파일 inventory metadata의 일치를 뜻한다. 실제 payload byte checksum 재계산은 Approval 소비 뒤, record parse와
tokenizer load 전에 수행하는 `input_integrity_validation` 상태의 첫 실행 단계다. 이 경계를 숨기지 않는다.

### 11.2 검사 항목

- V03-1 bundle `passed`, checksum·effective Dataset fingerprint·승인 조건 일치
- Approval `issued`, unconsumed, unexpired와 stable fingerprint 일치
- Runtime request exact match와 nonce 미사용
- Dataset·Tokenizer inventory·config·backend·dependency artifact 존재와 evidence checksum 일치
- config 필수 field와 unknown field 0
- final·staging·failed·emergency·worker·log 경로 신규
- output/staging이 same-volume이고 atomic no-replace 지원
- 예상 staging+final+failure+log 용량과 safety margin을 반영한 disk 여유
- Windows 절대경로·최대 예상 descendant 경로 길이 정책 통과
- Python·torch·transformers·datasets·tokenizers 등 dependency availability와 snapshot 일치
- clean worktree, HEAD/source commit 일치, 실행 surface fingerprint 일치
- 동일 Run·output root·Dataset identity를 소유한 process·reservation·lock 부재
- heartbeat, stage, stdout/stderr와 terminal failure writer의 synthetic self-check evidence
- supervisor의 liveness·graceful/force stop·orphan policy 고정

### 11.3 결과 artifact

`tokenization-preflight-evidence.json`은 `preflight_passed`, `preflight_failed`,
`approval_retirement_required` 중 하나를 기록한다. 필수 필드는 다음과 같다.

- 모든 Approval/request/V03-1/config/backend/dependency fingerprint
- identity surface·filesystem·disk·path·process·writer 검사 결과
- payload_reads=0, tokenizer_loads=0, tokenization_calls=0, output_writes=0
- failure codes, created/expires timestamp, source commit, evidence fingerprint와 checksum

주요 failure code:

- `V03_DATA_READINESS_NOT_PASSED`
- `TOKENIZATION_APPROVAL_NOT_ISSUED`, `TOKENIZATION_APPROVAL_EXPIRED`, `TOKENIZATION_APPROVAL_DRIFT`
- `TOKENIZATION_REQUEST_MISMATCH`, `TOKENIZATION_REQUEST_REUSED`
- `DATASET_EVIDENCE_MISMATCH`, `TOKENIZER_INVENTORY_MISMATCH`, `CONFIG_INCOMPLETE`
- `RUN_ID_ALREADY_USED`, `OUTPUT_IDENTITY_COLLISION`, `ATOMIC_NO_REPLACE_UNSUPPORTED`
- `SOURCE_COMMIT_MISMATCH`, `WORKTREE_DIRTY`, `BACKEND_FINGERPRINT_MISMATCH`
- `DEPENDENCY_SNAPSHOT_MISMATCH`, `DISK_SPACE_INSUFFICIENT`, `WINDOWS_PATH_LENGTH_UNSAFE`
- `CONFLICTING_PROCESS_OR_LOCK`, `OBSERVABILITY_WRITER_NOT_READY`
- `APPROVAL_RETIREMENT_REQUIRED`

## 12. Wrapper timeout·worker lifecycle 재설계

- supervisor는 worker PID, process creation time, command fingerprint와 process group/job identity를 시작 evidence에 기록한다.
- worker는 진행 중 stage와 monotonic sequence, 처리 count, heartbeat timestamp를 atomic `stage-state.json`에 기록한다.
- stdout/stderr는 worker 전용 bounded/rotated 파일에 직접 연결하고 parent pipe close와 분리한다.
- 전체 실행에 단일 600초 timeout을 두지 않는다. stage별 최대 무진행 시간과 publish stage timeout을 분리한다.
- timeout은 즉시 성공·실패를 확정하지 않고 `stop_requested` 전이를 쓴 뒤 cooperative cancellation을 요청한다.
- grace period 후 POSIX는 terminate→kill, Windows는 CTRL_BREAK/terminate→`process.kill()` 또는 Job Object 종료처럼
  지원 API를 사용한다. Windows에 `signal.SIGKILL`이 있다고 가정하지 않는다.
- 각 종료 시도, 반환·예외, 최종 PID 생존 여부와 worker exit code를 기록한다.
- worker와 알려진 child process가 모두 종료됐는지 확인하고 orphan이면 `ORPHAN_PROCESS_DETECTED`로 차단한다.
- terminal failure artifact, cleanup evidence, stdout/stderr checksum과 마지막 valid stage를 보존한다.
- worker는 실행 결과를 제안하고 supervisor만 exit code·terminal evidence·artifact reload를 종합해 최종 상태를 결정한다.
- terminal evidence를 쓰지 못했거나 worker 생존 여부가 불명확하면 성공 금지, Approval·Run retirement 필요 상태다.

## 13. Hardened publish preflight와 atomicity

### 13.1 `publish_ready` 조건

- staging의 expected artifact set이 exact match하고 unknown·missing file 0
- 각 파일 close·flush·fsync 완료
- checksum inventory가 모든 publish 대상 파일을 정확히 한 번 포함
- semantic manifest fingerprint와 package fingerprint 계산 완료
- Train·Validation row/token/mask/EOS/truncation 통계가 config guardrail 통과
- staging reload와 schema·checksum 재검증 통과
- staging/final parent가 same-volume이며 directory atomic rename·no-replace probe 통과
- final destination 미존재
- `.failed`·emergency·terminal artifact 경로는 사전 정책에 따라 모두 미존재
- open handle 검사는 best-effort 진단으로 수행하되, 실제 rename failure를 무시하는 근거로 쓰지 않음
- source Dataset·Tokenizer·config·Approval/request fingerprint를 publish 직전 재검증

### 13.2 성공·실패 원자성

1. final로 atomic no-replace rename하기 전에는 consumer가 staging을 볼 수 없다.
2. rename 뒤 parent directory sync, final reload와 checksum 검증 전 상태는 `published_pending_validation`이다.
3. consumer는 final directory 존재만 보지 않고 같은 Run의 `completion-evidence.json`과 checksum을 함께 요구한다.
4. final reload까지 통과한 뒤 completion evidence를 atomic no-replace로 게시해야 `completed`다.
5. rename 전 실패는 final을 만들지 않고 `.failed` artifact를 게시한다.
6. rename 뒤 검증 실패는 final을 삭제·덮어쓰기·성공 처리하지 않는다. sibling terminal failure evidence로
   `publish_failed_after_visibility`를 기록하고 해당 final을 비적격·Run retired로 처리한다.
7. failure artifact publish 실패는 emergency record를 남기며 자동 retry하지 않는다.

[확정] directory rename의 원자성과 전체 transaction의 원자성은 다르다. completion evidence를 eligibility commit
marker로 사용해 partial visibility를 성공으로 오인하지 않는다.

## 14. Fresh tokenization 상태 머신

| 상태 | 허용 전이 | Writer | 필수 evidence |
|---|---|---|---|
| `planned` | `data_ready`, `retired` | recovery planner | 계약 version·predecessor |
| `data_ready` | `approval_issued`, `retired` | V03-1 finalizer | passed readiness bundle |
| `approval_issued` | `request_created`, `retired`, `expired` | Approval issuer | issued Approval |
| `request_created` | `preflight_passed`, `preflight_failed`, `retired` | Request issuer·preflight writer | immutable request·preflight |
| `preflight_passed` | `running`, `retired` | execution gate | fresh preflight·atomic Approval consume |
| `running` | `tokenized`, `runtime_failed` | worker·stage tracker | input checksum, heartbeat, logs |
| `tokenized` | `validating`, `validation_failed` | worker | in-memory/output inventory |
| `validating` | `publish_ready`, `validation_failed` | validator | schema·mask·EOS·statistics |
| `publish_ready` | `published`, `publish_failed` | publisher | publish preflight evidence |
| `published` | `completed`, `publish_failed` | publisher·supervisor | final reload·checksum |
| `completed` | terminal | supervisor | completion evidence |

실패 상태는 `preflight_failed`, `runtime_failed`, `validation_failed`, `publish_failed`, `retired`다. 모든 실패는
terminal 또는 retirement evidence를 요구하며 같은 Run/Approval의 재실행을 허용하지 않는다. `preflight_failed`가
identity와 Approval을 소비하지 않았더라도 원인이 source/backend drift이면 `retired`로 전환한다. 단순 비파괴 환경
검사 실패의 재검토 정책도 같은 evidence artifact 안에 명시하며 자동 실행은 금지한다.

## 15. 현재 Blocker와 승인 시점

| ID | Severity | 현재 상태 | 해결 artifact | 코드 변경 | 실제 실행 | 사용자 승인 시점 | 차단 Gate |
|---|---|---|---|---|---|---|---|
| `V03-BLOCK-001` | critical | SFT·파생 Adapter 목적 증거 부족 | `license-evidence.json` | 아니요 | 공식 증거 확보 필요 | 라이선스 판정 확정 | V03-1·2 |
| `V03-BLOCK-007` | blocking | v0.3 독립 PII evidence 없음 | PII 4-artifact set | 예 | scan·review 필요 | scan 범위와 수동 검토 전 | V03-1 |
| `V03-BLOCK-009` | blocking | 독립 Safety evidence 없음 | Safety 4-artifact set | 예 | scan·review 필요 | scan 범위와 disposition 전 | V03-1 |
| `V03-BLOCK-008` | blocking | 외부 benchmark·v0.3 leakage clear 없음 | Leakage 3-artifact set | 예 | scan·review 필요 | benchmark source·threshold 전 | V03-1·평가 |
| `V03-BLOCK-010` | blocking | 새 Run identity ledger/reservation 미구현 | reservation·registry evidence | 예 | 예약 필요 | 실제 identity 예약 전 | V03-2 |
| `V03-BLOCK-004` | critical | Tokenization Approval 계약 미구현 | TokenizationApproval v1 | 예 | issue 필요 | issue 직전 | V03-2 |
| `V03-BLOCK-011` | critical | Tokenization request writer 미구현 | TokenizationExecutionRequest v1 | 예 | request 생성 필요 | request 발급 전 | V03-2 |
| `V03-BLOCK-003` | blocking | 내부 publish 원인 unresolved | 새 Run stage·terminal evidence | 예 | fresh 실행에서만 확인 | 실행 직전 | V03-2 |
| `V03-BLOCK-012` | blocking | metadata preflight·input integrity 분리 미구현 | preflight evidence·unit test | 예 | metadata preflight 필요 | preflight 전 | V03-2 |
| `V03-BLOCK-013` | blocking | Windows termination·orphan 계약 미검증 | supervisor synthetic evidence | 예 | synthetic만 먼저 | 실제 실행 전 | V03-2 |
| `V03-BLOCK-014` | blocking | publish eligibility marker·after-visibility 실패 계약 미구현 | publish preflight·failure tests | 예 | synthetic만 먼저 | 실제 실행 전 | V03-2 |
| `V03-BLOCK-006` | blocking | v0.3 evaluation Gate 제안 미승인 | evaluation contract | 문서·코드 후속 | 평가 필요 | QLoRA 전·후 별도 | V03-8~10 |

## 16. 구현 Task

| Task | 내용·예상 변경 파일 | 필수 테스트 | 실행 권한 | 현재 상태 | 후속 |
|---|---|---|---|---|---|
| `V03-R1` | Evidence envelope·strict loader·bundle schema·atomic writer·finalizer. `src/data/v03_evidence.py`, `src/data/v03_evidence_writer.py` | exact schema, canonical fingerprint, no-replace, strict reload, Gate contradiction, zero payload call | 실제 evidence 생성 전 승인 필요 | `implemented_synthetic_validated` | R2 |
| `V03-R2` | PII·Safety·Leakage backend와 review/exclusion writer. 기존 inspector·duplicate 로직 최소 재사용 | synthetic detector/category, raw leak 0, deterministic rerun, unknown fail closed | 실제 v0.3 scan·review 전 승인 필요 | `implemented_synthetic_validated` | V03-1 decision |
| `V03-R3` | Run identity ledger·reservation·commit·abandon·retirement. `src/training/v03_run_identity.py`, `tests/test_v03_run_identity.py` | concurrency single winner, all-surface collision, date/sequence, write failure cleanup, corruption, symlink, abandoned/retired, predecessor | 실제 ID 예약 전 승인 필요 | `implemented_synthetic_validated` | R4 |
| `V03-R4` | `TokenizationApproval v1`, issue/consume/expire/retire와 lifecycle lock | state matrix, drift retirement, one-shot, concurrent request/retire/consume, legacy reject | 실제 issue·consume 전 승인 필요 | `designed_not_started` | R5 |
| `V03-R5` | `TokenizationExecutionRequest v1` writer·validator | exact match, nonce/TTL/replay, path/root, atomic no-replace, lifecycle race | 실제 request 생성 전 승인 필요 | `designed_not_started` | R6 |
| `V03-R6` | metadata-only preflight와 별도 input-integrity Gate | payload/tokenizer call 0, checksum evidence, disk/path/dependency/process failure matrix | metadata preflight 실행 전 승인 필요 | `designed_not_started` | R7·R8 |
| `V03-R7` | 기존 `src/training/v03_tokenization_runtime.py`의 platform stop·orphan·terminal authority 보완 | POSIX/Windows synthetic, missing SIGKILL, heartbeat stall, child orphan, exit preservation | synthetic 불필요; 실제 worker 실행 승인 필요 | `designed_not_started` | R9 |
| `V03-R8` | 기존 publisher에 publish-preflight·completion marker·after-visibility failure 추가 | 단계별 fault injection, exact set, same-volume, collision, final reload, consumer eligibility | synthetic 불필요; 실제 publish 승인 필요 | `designed_not_started` | R9 |
| `V03-R9` | PII 없는 synthetic E2E recovery rehearsal | reservation→issue→request→preflight→consume→worker→publish→complete와 모든 terminal failure | 실제 Dataset/GPU 권한 불필요 | `blocked_by_R1_to_R8` | fresh execution review |

[확정] 표의 경로는 예상 후보다. 후속 코드 작업에서 저장소 구조·하위 AGENTS·ADR를 다시 확인하고 중복 모듈을
피한다. 이번 작업에서는 생성하지 않았다.

## 17. 구현과 실행 순서

`V03-R1`과 `V03-R3`의 schema·순수 validator는 synthetic-only 구현·검증을 완료했다. 다음 코드 범위는
`V03-R4`, `V03-R5`이며 실제 payload를 읽지 않고 사용자 실행 승인을 소비하지 않는다. 이후 `R6 → R7 → R8 → R9`
순서로 검증한다.

아직 실행하면 안 되는 작업:

- v0.3 PII·Safety·Leakage 실제 scan과 수동 review
- 새 Run ID 실제 예약
- Approval issue·consume, Runtime request 생성과 preflight artifact 게시
- Dataset payload checksum 재계산·read, Tokenizer load, Tokenization과 publish
- sampler simulation, QLoRA, 평가, Adapter manifest와 Runtime 연결

사용자 승인은 최소 다음 시점에 별도로 필요하다.

1. 비공개 license evidence 판정과 실제 PII·Safety·Leakage scan/review 범위
2. V03-1 bundle `passed` 판정
3. 새 Run ID 예약
4. Approval issue
5. Runtime request와 metadata-only preflight
6. Approval consume 및 fresh Tokenization 실행

fresh tokenization까지의 최소 경로는 다음과 같다.

```text
R1 schema/writer
→ R2 synthetic + 승인된 실제 scans/reviews
→ V03-1 readiness decision
→ R3 identity reservation
→ R4 Approval issue
→ R5 request issue
→ R6 metadata-only preflight
→ R7/R8/R9 synthetic recovery rehearsal
→ 별도 실행 승인
→ atomic Approval consume
→ input checksum verification
→ fresh tokenization·validation·publish
```

## 18. 최종 판단

```yaml
final_decision: recovery_contract_design_complete
license_decision: evidence_insufficient
v03_r1_evidence_schema: implemented_synthetic_validated
v03_r1_atomic_writer: implemented_synthetic_validated
v03_r1_bundle_finalizer: implemented_synthetic_validated
v03_r2_scanner_contract: implemented_synthetic_validated
v03_r2_review_contract: implemented_synthetic_validated
v03_r2_exclusion_builder: implemented_synthetic_validated
v03_r3_identity_schema: implemented_synthetic_validated
v03_r3_ledger_validator: implemented_synthetic_validated
v03_r3_reservation_writer: implemented_synthetic_validated
actual_v03_run_reserved: false
actual_v03_evidence_bundle: not_created
actual_pii_scan: not_started
actual_safety_scan: not_started
actual_leakage_scan: not_started
actual_review_evidence: not_created
v03_data_evidence: pending
v03_fresh_tokenization: not_approved
v03_training: not_started
existing_tokenization_run_reusable: false
execution_allowed: false
```

[확정] 계약 설계는 완료됐지만 V03-1·V03-2 Gate가 통과된 것은 아니다. 특히 라이선스 evidence 부족을 문서 설계
완료 상태로 덮지 않는다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | V03-R3 strict Run Identity schema·ledger validator·atomic reservation/commit/abandon/retire를 synthetic-only로 구현·검증; 실제 ledger migration과 Run 예약은 수행하지 않고 execution 금지를 유지 |
| 2026-08-05 | V03-R2 synthetic-only PII·Safety·Leakage scanner, opaque HMAC reference, review policy, exclusion builder, R1 payload 변환을 구현·검증; 실제 Dataset scan·review·evidence 생성은 수행하지 않음 |
| 2026-08-05 | V03-R1 strict evidence schema·loader, atomic no-replace writer, 10-file bundle finalizer와 readiness Gate를 synthetic-only 검증으로 구현; 실제 evidence·승인·실행은 생성하지 않음 |
| 2026-08-05 | V03-1 license·PII·Safety·Leakage evidence와 V03-2 새 identity·Approval·request·preflight·worker·publish 계약 설계 |
