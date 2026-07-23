# DohaLM 단계별 테스트 체크리스트

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 로드맵](./development-roadmap.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](./test-strategy.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서 | 구현별 test와 Gate 결과 [검증 필요] |
| 구현 전 필수 여부 | 각 구현 전 예 |

- [확정] Phase 0의 환경·설정·경로·로깅·CLI 테스트와 Phase 1 최소 데이터 파이프라인의 synthetic fixture 테스트·CLI smoke를 구현·실행했다. Gate 2 사용자 승인은 아직 수행하지 않았다.
- [확정] 상태는 `planned`, `not_run`, `pass`, `fail`, `blocked`, `not_applicable`만 사용한다.
- [확정] 필수 항목이 `fail`, `blocked` 또는 `not_run`이면 관련 작업을 완료로 처리하지 않는다.

## 2. 체크리스트

| ID | 대상 | 점검 내용 | 테스트 수준 | 필수 여부 | 예상 결과 | 실패 시 조치 | 자동화 가능 | 현재 상태 |
|---|---|---|---|---|---|---|---|---|
| REPO-001 | 저장소 구조 | 기준 경로와 실제 경로, 불필요한 신규 디렉터리 확인 | Static validation | 예 | 승인 구조와 일치 | 구조 문서·경로 수정 | 예 | `pass` — 경로 검사 통과 |
| REPO-002 | Git 변경 | 데이터·checkpoint·비밀·범위 밖 파일 미포함 | Static validation | 예 | 금지 파일 0개 | stage/commit 금지, 원인 보고 | 예 | `pass` — 추적 산출물 위반 0건 |
| CFG-001 | 설정 | schema·필수 field·unknown key 처리 | Unit test | 예 | 유효 설정 통과, 오류 설정 명시 실패 | loader/schema 수정 | 예 | `pass` — 승인 Tiny 불변값·오류 경로 검증 |
| CFG-002 | 설정 | resolved config와 CLI override 기록 | Integration test | 예 | 실제 적용값 snapshot 일치 | 우선순위·기록 수정 | 예 | `pass` — resolve·override·미완성 상태 검증 |
| ENV-001 | 환경 진단 | OS·Python·PyTorch·CUDA build·GPU·Git 정보와 YAML/JSON 직렬화 | Unit/Integration test | 예 | primitive 계약과 두 출력의 의미 일치 | 수집·직렬화 계약 수정 | 예 | `pass` — 실제 PyTorch 포함 YAML/JSON 검증 |
| ENV-002 | CPU | 작은 CPU tensor 생성·연산·해제 | Smoke test | 예 | 합계 연산 성공, 오류 없음 | PyTorch·환경 진단 | 예 | `pass` — CPU smoke 성공 |
| ENV-003 | CUDA | 가용성·장치 수·GPU 이름·VRAM 및 tensor 생성·연산·동기화·해제 | GPU/Smoke test | 예 | RTX 3060 Ti에서 CUDA smoke 성공 | CUDA·Driver·PyTorch 조합 재검토 | 예 | `pass` — RTX 3060 Ti 8,192 MiB smoke 성공 |
| CLI-001 | CLI | 도움말, environment YAML/JSON, config validate/resolve, paths와 간결한 오류 | Integration test | 예 | 정상 종료·parse 가능·traceback 없음 | parser·출력·종료 코드 수정 | 예 | `pass` — Gate 1 명령 경로 검증 |
| PATH-001 | 경로 | 저장소 root·CWD 독립성·Windows/POSIX 상대경로·지연 생성 정책 | Unit/Integration test | 예 | 저장소 밖 차단, 읽기 진단이 디렉터리를 만들지 않음 | 경로 정책 수정 | 예 | `pass` — 경로·artifact 정책 검증 |
| LOG-001 | 로깅 | UTF-8 한글·비밀 마스킹·handler 중복 방지·지연 파일 생성 | Unit test | 예 | 한글 보존, secret 미노출, 중복 handler 없음 | formatter·handler 정책 수정 | 예 | `pass` — 로깅 회귀 테스트 통과 |
| DATA-001 | 데이터 | 원본 불변·checksum·manifest 계보 | Component test | 예 | 원본 hash 유지, 입력·출력 연결 | 처리 중단·전처리 수정 | 예 | `pass` — synthetic fixture checksum 불변과 10개 artifact·lineage 정합성 검증 |
| DATA-002 | 데이터 | deterministic split·exact 직접 누수 fixture | Component test | 예 | 같은 seed 동일 split, 교차 누수 탐지 | split 재생성·알고리즘 수정 | 예 | `pass` — group·normalized checksum·record ID·source record 누수 차단 검증; near 누수는 Phase 1 제외 |
| DATA-003 | 데이터 | 개인정보·라이선스·승인 상태 차단 | Unit/Integration test | 예 | 미승인·PII 비-clear 입력 사용 금지 | 격리·승인 재검토 | 예 | `pass` — `unknown` license, `pending` approval, `suspected` PII 전체 차단 검증 |
| TOK-001 | 토크나이저 | vocab 16,000과 special token ID 0~7 | Component test | 예 | size·문자열·ID 정확히 일치 | tokenizer 재학습·설정 수정 | 예 | `planned` |
| TOK-002 | 토크나이저 | encode/decode·role token 단일 ID·fingerprint | Regression test | 예 | 승인 fixture와 hash 일치 | normalization·artifact 검토 | 예 | `planned` |
| TOK-003 | 토크나이저 | 한국어·혼합 문자 token 품질 | Manual evaluation | 예 | 승인 상태·통계 기준 충족 | corpus·coverage·fallback 재검토 | 일부 | `planned` |
| MOD-001 | 모델 | component·통합 output shape | Unit/Integration test | 예 | 문서 shape와 일치 | 해당 layer·config 수정 | 예 | `planned` |
| MOD-002 | 모델 | parameter count·weight tying | Regression test | 예 | 16,889,856, storage alias | 구조·bias·tying 수정 | 예 | `planned` |
| MOD-003 | 모델 | causal mask 미래 정보 차단 | Unit test | 예 | 미래 token 변경이 이전 logits에 영향 없음 | mask 위치·broadcast 수정 | 예 | `planned` |
| MOD-004 | 모델 | CPU forward/backward·dtype/device·오류 | Component test | 예 | finite gradient, 명시적 오류 | 연산·validation 수정 | 예 | `planned` |
| TRN-001 | 학습 | 단일 step optimizer·scheduler update | Smoke test | 예 | 예상 parameter·step 갱신 | loop·step 순서 수정 | 예 | `planned` |
| TRN-002 | 학습 | FP16 AMP·GradScaler·NaN/Inf | GPU test | 예 | finite update와 scaler 상태 기록 | precision·연산·중단 처리 검토 | 예 | `planned` |
| TRN-003 | 학습 | gradient accumulation·clipping 순서 | Component test | 예 | update 주기·정규화·unscale 순서 일치 | trainer 수정 | 예 | `planned` |
| TRN-004 | 학습 | 단일 batch·극소량 overfit | GPU/Smoke test | 예 | 기준선 후 승인된 loss 감소 | data·loss·mask·optimizer 진단 | 예 | `planned` |
| CKPT-001 | Checkpoint | 필수 key·format·hash·atomic save | Component test | 예 | 완전한 checkpoint만 노출 | 저장 로직·schema 수정 | 예 | `planned` |
| CKPT-002 | Checkpoint | round-trip logits와 weight alias | Regression test | 예 | 허용 범위 내 동일, tying 유지 | load·migration 수정 | 예 | `planned` |
| CKPT-003 | Checkpoint | optimizer·scheduler·AMP·RNG·sampler resume | Integration test | 예 | 중단 없는 기준과 연속성 | 누락 state·step 수정 | 예 | `planned` |
| GEN-001 | 생성 | 고정 seed 최소 생성·stop token | Regression test | 예 | 재현 정책 범위 내 출력·정상 종료 | sampling·EOS·position 수정 | 예 | `planned` |
| GEN-002 | 생성 | 반복·빈 응답·특수문자·언어 붕괴 | Manual/Component test | 예 | 상태형 결과와 실패 sample 기록 | 생성 설정·모델 원인 분석 | 일부 | `planned` |
| EVAL-001 | 평가 | training/validation loss와 perplexity 집계 | Unit test | 예 | 유효 token 가중 mean과 지수 일치 | mask·집계 수정 | 예 | `planned` |
| EVAL-002 | 평가 | 동일 split/tokenizer/context 비교 계약 | Static/Integration test | 예 | 호환되지 않는 비교 차단 | evaluation metadata 수정 | 예 | `planned` |
| EVAL-003 | 평가 | throughput·latency·peak VRAM 측정 | Performance/GPU test | 예 | 조건·단위·warm-up과 값 기록 | 측정 범위·동기화 수정 | 예 | `planned` |
| SFT-001 | SFT | chat template·role·assistant loss mask 정렬 | Unit test | 예 | target 위치와 ignore_index 일치 | serializer·mask 수정 | 예 | `planned` |
| SFT-002 | SFT | SFT 전후 동일 평가·누수 검사 | Integration test | 예 | parent·prompt·split·설정 고정 | 결과 invalid·split 재검토 | 일부 | `planned` |
| API-001 | API | request/response·validation·오류 schema | Integration test | 후순위 필수 | 명세와 상태 code 일치 | API 명세·구현 수정 | 예 | `planned` |
| API-002 | API | model lifecycle·streaming 중단 | Integration/Performance test | 후순위 필수 | load 1회·정상 stream·오류 정리 | lifecycle·stream 수정 | 일부 | `planned` |
| UI-001 | Frontend | 입력·loading·응답·오류 상태 | Component test | 후순위 필수 | 명세와 화면 상태 일치 | UI state 수정 | 예 | `planned` |
| UI-002 | Frontend | API 통합·stream rendering | Integration test | 후순위 필수 | 순서·중단·오류 표시 정상 | API/UI 계약 수정 | 일부 | `planned` |
| DEP-001 | 배포 | clean 환경 설치·로컬 smoke | Smoke test | 후순위 필수 | 문서 명령으로 실행 | dependency·문서 수정 | 일부 | `pass` — Phase 0 로컬 `.venv` 검증 |
| DEP-002 | 배포 | artifact hash·모델 카드·비밀 분리 | Static/Integration test | 후순위 필수 | hash·출처·제한·secret 검사 통과 | package·card 수정 | 일부 | `planned` |
| DOC-001 | 문서 | 필수 목차·상태·인덱스·ADR 동기화 | Static validation | 예 | 누락·허위 완료 0건 | 문서 수정 | 예 | `planned` |
| DOC-002 | 문서 | 상대 링크와 예정 파일 코드 표기 | Static validation | 예 | 깨진 상대 링크 0개 | 링크·표기 수정 | 예 | `planned` |
| SEC-001 | 보안 | secret·credential·개인 절대경로 검사 | Static validation | 예 | 노출 0건 | 변경 중단·secret 폐기/회전 보고 | 일부 | `pass` — 환경 identity 제외·설정/로그 secret 마스킹 검증 |
| SEC-002 | 보안 | path traversal·비승인 파일 접근 | Unit/Integration test | 예 | 경계 밖 접근 명시 실패 | validation·권한 수정 | 예 | `pass` — 절대경로·상위 이동 차단 검증 |
| REP-001 | 재현성 | Git·config·data fingerprint 기록 | Static/Integration test | 예 | 필수 metadata 완전 | 실행 invalid·기록 수정 | 예 | `pass` — Phase 1 lineage에 Git SHA·resolved config checksum·dataset fingerprint 기록 |
| REP-002 | 재현성 | 같은 seed 재실행과 허용 차이 | Regression test | 예 | 결정론적 산출물과 fingerprint 일치 | 비결정 원인·환경 분석 | 예 | `pass` — 입력 순서 변경 시 records·split·statistics·fingerprint 일치 |

## 3. 실행 기록 원칙

- [확정] 각 결과는 test ID, code revision, config, fixture/data version, 환경, 실행 명령, 시각과 로그를 연결한다.
- [확정] `not_run`과 `blocked`를 `pass`로 집계하지 않는다.
- [확정] GPU test를 CPU 결과로 대체하지 않으며 GPU 미실행 사유를 명시한다.
- [확정] `not_applicable`에는 해당하지 않는 이유와 승인 범위를 기록한다.
- [확정] Phase 0 test 파일은 `tests/test_config.py`, `tests/test_environment.py`, `tests/test_paths.py`, `tests/test_logging.py`, `tests/test_cli.py`이며 `python -m pytest -q`로 실행한다.
- [확정] Gate 1 근거 revision `10f5f46959a018a93000987e6c20896f6c263c0a`에서 43개 테스트가 수집되어 43개 모두 통과했고 실패는 0개였다.
- [검증 필요] 후속 구현 test와 CI mapping은 해당 단계에서 정한다.

## 4. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] Gate 1 승인 근거에 따라 직접 검증한 Phase 0 항목만 `pass`로 기록하고 43개 테스트 결과를 연결함 |
| 2026-07-23 | [확정] 격리 `.venv` editable 설치·의존성 무결성·CLI·CPU/CUDA smoke 검증 반영 |
| 2026-07-23 | [확정] Phase 0 설정·환경·경로·로깅·CLI 자동 테스트와 실행 명령 반영 |
| 2026-07-23 | [확정] 저장소부터 재현성까지 16개 범주의 계획 test와 실패 조치 정의 |
