# DohaLM 개발 로드맵과 단계별 Gate

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-27 |
| 선행 문서 | [범위와 목표](../project/scope-and-goals.md), [개발 규칙](../governance/development-rules.md), [시스템 아키텍처](../architecture/system-architecture.md), [핵심 개발 기능명세서](../architecture/core-development-feature-specification.md), [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서 | [테스트 체크리스트](./testing-checklist.md), [Definition of Ready](../governance/definition-of-ready.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](./test-strategy.md), [위험 등록부](../governance/risk-register.md), [버전 계획](../project/version-plan.md), [Codex 작업 절차](../governance/codex-workflow.md) |
| 구현 전 필수 여부 | 예 |

- [확정] Phase 0 저장소·환경 기반은 구현·검증을 완료했으며 모델·학습·평가·서비스 구현은 완료되지 않았다.
- [확정] Phase 번호는 선행 관계를 나타내며 일정·기간을 뜻하지 않는다.
- [확정] Gate를 통과하지 못하면 후속 Phase를 완료 상태로 처리하지 않는다.

## 2. 개발 Phase

| Phase | 목적 | 선행 조건 | 작업 항목 | 결과물 | 필수 테스트 | 진입 조건 | 통과 조건 | 실패 시 복귀 | 현재 상태 |
|---|---|---|---|---|---|---|---|---|---|
| 0. 저장소와 환경 기반 | 재현 가능한 구현 기반 마련 | 기준 문서·ADR 확인 | 구조 확정, Python 기준, CUDA·PyTorch 호환 검토, 의존성·설정 구조, 기본 테스트 환경, 로그·산출물 경로 | 환경 기준, 설정 계약, 테스트 진입점 | 설정 parse, CPU smoke, CUDA 가용성 후보, 경로·Git 제외 검사 | Gate 0 통과 | Gate 1 통과와 환경 snapshot 가능 | Gate 0 문서 보완 | [확정] 구현·검증 완료 |
| 1. 데이터 최소 파이프라인 | 안전한 최소 입출력·계보 검증 | Phase 0, 데이터 정책, [Phase 1 데이터 계약](../data/phase1-data-contract.md) | 가상/극소량 로컬 sample, 형식 검증, 정제 흐름, manifest, checksum, split 검증 | 소형 fixture 처리 결과·manifest | 원본 불변, checksum, deterministic split, 누수 fixture | Gate 1 통과·허용 fixture 준비·Phase 1 계약 검토 | Gate 2 통과 | Phase 0 설정·경로 | [확정] 구현·검증 완료, DATA-001~016 `verified` |
| 2. 토크나이저 | 한국어 token 계약 확정 | Phase 1, [후보 등록부](../data/dataset-candidate-registry.md), [구조 분석 요약](../data/analysis/dataset-analysis-summary.md), [안전 표본 정책](../data/analysis/safe-sampling.md), [라이선스 검토](../data/dataset-license-review.md), [승인 로그](../data/dataset-approval-log.md), [Phase 2 토크나이저 상세 계약](../training/phase2-tokenizer-contract.md) | TOK-001~012: corpus 승인, SentencePiece Unigram, special token, encode/decode, fingerprint, artifact·호환성과 한국어 품질 | versioned tokenizer bundle·manifest·평가·호환성 보고 | vocab 16,000, ADR-003 ID 0~7, round-trip, fingerprint, atomic publish, 후보 비교 | Gate 2 `passed`, 최소 1개 `approved_tokenizer_development`, 공식 조건 검토, fingerprint 가능, validation/test 분리 | Gate 3 통과 | Phase 1 데이터·승인 정책 | [확정] `operating-16k-v2/unigram-16k` 구현·검증·사용자 승인 완료, Gate 3 `passed` |
| 3. 모델 구성요소 | 핵심 layer를 독립 검증 | Phase 0, ADR-002 | Config, token/position embedding, causal self-attention, MHA, FFN, Pre-LN, block, LM Head, weight tying | 직접 구현 모듈·단위 테스트 | shape, causal mask, backward, dtype/device, error, tying alias | Gate 1·모델 문서 승인 | Gate 4 통과 | 해당 구성요소·Config | [확정] 구성요소와 단위 테스트 및 통합 evidence를 검증하고 사용자 승인으로 Gate 4 `passed` |
| 4. 모델 통합 | DohaLM-Tiny forward·생성 연결 | Phase 2·3 | 전체 forward, loss, parameter count, dtype/device, causal mask, 최소 generation | 통합 model·loss·generation | count 16,889,856, logits shape, shift, mask, forward/backward, deterministic generation | Gate 3·4 통과 | Gate 5 통과 | Phase 2 또는 3 | [확정] 합성 token 기반 구현·CPU/CUDA 검증과 사용자 승인 완료, Gate 5 `passed`; 제한 Gate 7 실험에서 운영 tokenizer 연결 검증 |
| 5. 학습 기반 | 재개 가능한 학습 loop 구축 | Phase 1·4 | Dataset/DataLoader, AdamW, scheduler, FP16 AMP, accumulation, clipping, checkpoint, resume, log | trainer·checkpoint·log 계약 | smoke update, AMP, accumulation equivalence 후보, round-trip, resume, NaN/Inf | Gate 5 통과 | Gate 6 통과 | Phase 1 데이터 또는 4 모델 | [확정] 합성 Foundation과 실제 Tiny 규모 sampler·cosine 후보·CUDA FP16·checkpoint/resume·VRAM evidence를 사용자 승인해 Gate 6 `passed`; 실제 사전학습 미실행 |
| 6. 초소형 검증 | 장시간 학습 전 end-to-end 검증 | Phase 5 | 단일 batch·극소량 overfit, loss 감소, round-trip, resume, sample, CUDA peak VRAM | overfit 실험 기록·checkpoint·sample | overfit, resume 연속성, 생성, peak allocated/reserved | Gate 6 통과·experiment ready | Gate 7 통과 | Phase 4·5 | [확정] 실제 Training 64문서·운영 tokenizer의 1,000-step packed overfit, exact continuation, resume와 자원 검증을 사용자 승인해 Gate 7 `passed` |
| 7. Tiny 소규모 사전학습 | 승인 데이터로 Tiny pilot 수행 | Phase 6, 승인 데이터 | 고정 validation, 중간 평가, 실패 복구, 자원 기록, 최종 checkpoint | pilot/final checkpoint·평가·실험 기록 | validation loss/perplexity, resume, 생성, 처리량, peak VRAM | Gate 7 통과·Gate 8 승인 | 계획 종료·평가·복원 성공 | Phase 6 또는 데이터 Phase 1 | [검증 완료] canonical Pilot과 Candidate A 10M 단일 실행 완료; 추가 학습 미승인 |
| 8. SFT | 대화 형식과 응답 품질 검증 | Phase 7, 승인 SFT 데이터 | chat template, assistant loss mask, SFT 전후 평가, 생성 품질 비교 | SFT checkpoint·전후 보고서 | role/ID, mask alignment, overfit/smoke, 전후 동일 평가, 누수 검사 | Gate 8·9 통과 | SFT 기준과 복원·평가 통과 | Phase 7 또는 SFT 데이터 준비 | [검증 필요] 미구현 |
| 9. 추론과 서비스 | 검증 model을 로컬 UI까지 연결 | Phase 7 또는 8 | 추론 모듈, 로딩, 생성 옵션, FastAPI, streaming, Next.js | 로컬 추론·API·UI 후보 | model load, generation, API schema, streaming 오류, UI 연동 | Gate 10 통과 | 로컬 end-to-end와 오류 처리 통과 | 추론→API→UI 하위 단계 | [후순위] 미구현 |
| 10. 배포와 외부 평가 | 재현·공개·외부 비교 가능성 검토 | Phase 7~9, 라이선스·평가 승인 | 로컬 재현, Docker, 모델 카드, Benchmark, Leaderboard 검토 | 재현 bundle·모델 카드·검토 보고 | clean setup smoke, artifact hash, 라이선스·누수·Benchmark 계약 | Gate 11 승인 | 승인된 범위의 재현·보고 완료 | 관련 구현·데이터·평가 Phase | [후순위] 미구현 |

- [확정] Phase 3 모델 구성요소는 Phase 2와 일부 병행 가능하지만 모델 통합은 tokenizer 계약 없이 통과할 수 없다.
- [확정] [핵심 개발 기능명세서](../architecture/core-development-feature-specification.md)는 Phase 1~6 구현의 입력·출력·오류·설정·산출물·테스트·Done 계약과 Gate 2~7 검증 항목의 공통 참조다.
- [확정] 이 기능명세서는 최소 로컬 추론까지만 다루며 서비스 API·Frontend·DB 기능명세를 대신하지 않는다.
- [확정] Phase 9·10은 `DohaLM-Tiny`의 학습·평가 검증 이후 진행하는 후순위다.
- [검증 필요] 실제 일정, 담당자, 수치 합격선과 `DohaLM-Small` 진입 Phase는 Tiny 실측 후 결정한다.

## 3. 단계별 Gate

상태는 `planned`, `review`, `approved`, `blocked`, `passed`, `failed` 후보를 사용한다. `passed`는 문서 승인만으로 부여하지 않는다.

| Gate | 필수 문서 | 필수 구현 | 필수 테스트 | 필수 산출물 | 통과 기준 | 실패 조건 | 승인 주체 | 상태 |
|---|---|---|---|---|---|---|---|---|
| Gate 0: 문서 승인 | 프로젝트·범위·개발 규칙, ADR-001~006, 관련 설계 | 없음 | 링크·수치·상태 검토 | 승인/검토 기록 | 구현 대상·제외·테스트·미결정 사항 명확 | 확정 사양 충돌·필수 문서 누락 | 사용자 검토 | `approved` |
| Gate 1: 환경 검증 | 저장소·산출물·재현성·Ready | 환경 확인·설정 loader 최소 후보 | Python/PyTorch/CUDA·CPU smoke·경로 검사 | environment snapshot·resolved config | 기준 환경에서 최소 명령 성공, 비밀·경로 문제 없음 | 의존성 충돌·CUDA 불가·재현 정보 누락 | 사용자 | `passed` |
| Gate 2: 데이터 파이프라인 검증 | [Phase 1 데이터 계약](../data/phase1-data-contract.md), [데이터 전략](../data/data-strategy.md), [데이터 전처리](../data/preprocessing.md), [데이터셋 등록부](../data/dataset-registry.md), [데이터 라이선스 정책](../data/data-license-policy.md), [데이터 품질 체크리스트](../data/data-quality-checklist.md), [데이터 분할 및 누수 정책](../data/data-split-and-leakage-policy.md), ADR-004 | DATA-001~016 최소 read-only 전처리·manifest·split | SHA-256, 원본 불변, schema·NFC·exact dedup, deterministic group split, 직접 누수 fixture | 계약의 10개 필수 artifact와 test 결과 | 승인 fixture의 단계 연결·재실행·artifact 정합성 일치와 사용자 승인 | 원본 변경·계보 유실·split 누수·미승인/PII 입력 통과 | 사용자 | `passed` |
| Gate 3: 토크나이저 검증 | [Phase 2 토크나이저 상세 계약](../training/phase2-tokenizer-contract.md), [후보 등록부](../data/dataset-candidate-registry.md), [구조 분석 요약](../data/analysis/dataset-analysis-summary.md), [라이선스 검토](../data/dataset-license-review.md), [승인 로그](../data/dataset-approval-log.md), [평가 제외 목록](../data/evaluation-exclusion-list.md), ADR-003 | TOK-001~012와 승인 development corpus | 이용조건·목적 승인·fingerprint·split, vocab/ID, encode/decode, unknown·분할, 결정론·artifact·호환성 | tokenizer bundle·manifest·fingerprint·A/B 평가 | 최소 1개 development corpus 승인, 16,000 vocab, ADR-003 ID, 후보 2개, round-trip·Windows·추적 위반 0, 사용자 승인 | 승인·권리·누수·ID·checksum·호환성·의미 보존 실패 | 사용자 검토 | `passed` |
| Gate 4: 모델 단위 구성요소 검증 | [모델 아키텍처](../architecture/model-architecture.md), ADR-002, [테스트 전략](./test-strategy.md) | 각 모델 component | shape, mask, forward/backward, dtype/device, error | 단위 테스트 결과 | 모든 필수 component test pass | 필수 실패·외부 완성 model 대체 | 사용자 검토 | `passed` |
| Gate 5: 모델 통합 검증 | [모델 아키텍처](../architecture/model-architecture.md), [토크나이저 설계](../training/tokenizer-design.md), [평가 계획](../evaluation/evaluation-plan.md), ADR-002·003 | Tiny forward/loss/generation | count, logits, causal 불변성, shift, tying, generation | 통합 test report | count 16,889,856과 계약 일치, 필수 test pass | shape·mask·count·NaN/Inf 실패 | 사용자 검토 | `passed` |
| Gate 6: 학습 파이프라인 검증 | [사전학습 계획](../training/pretraining-plan.md), [실험 관리](../training/experiment-management.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md), [재현성 정책](./reproducibility-policy.md) | trainer, AMP, accumulation, checkpoint/resume | smoke update, round-trip, resume, RNG, log, OOM handling | checkpoint·log·experiment metadata | 최소 step·복원·재개와 필수 기록 성공 | 복원 실패·누락 state·반복 NaN/Inf | 사용자 검토 | `passed` |
| Gate 7: 오버피팅 검증 | [사전학습 계획](../training/pretraining-plan.md), [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [실험 템플릿](../training/experiment-template.md) | end-to-end tiny training | 단일 batch·극소량 overfit, generation, VRAM | 실험 기록·checkpoint·samples | loss 감소·복원·생성과 peak VRAM 기록 | loss 미감소·회귀·OOM 미해결 | 사용자 검토 | `passed` |
| Gate 8: Tiny 사전학습 진입 | [Full Pretraining 실행 계획](../training/full-pretraining-execution-plan.md), [Readiness](../training/full-pretraining-readiness.md), 데이터·평가·위험 문서 | Phase 0~6 구현과 Full 전용 fail-closed backend | Gate 2~7·Pilot 증거, identity·Candidate A 정책·backend·Disk 검증, final approval 차단 | approved data, resolved config, single-use approval, ready experiment | 모든 선행 Gate passed·중단 조건·저장공간·Full 전용 사용자 승인 | 실행 미승인·identity 불일치·복구 불가 | 사용자 명시 승인 | `review` — Candidate A 10M 실행·runtime/checkpoint 검증 완료, Gate 상태 변경은 별도 승인 필요 |
| Gate 9: SFT 진입 | [SFT 계획](../training/sft-plan.md), [평가 계획](../evaluation/evaluation-plan.md), [데이터 분할 및 누수 정책](../data/data-split-and-leakage-policy.md), [생성 평가](../evaluation/generation-evaluation.md) | SFT dataset/template/mask | role·mask·누수·SFT smoke·전 기준선 | approved SFT data·parent checkpoint·baseline | parent 검증, 동일 평가 조건, 데이터 승인 | template/mask 오류·평가 누수 | 사용자 명시 승인 | `planned` |
| Gate 10: 서비스 개발 진입 | 추론·API·frontend 계획 문서 [예정] | 검증 inference module | load·generation·latency 기준선 | 서비스 대상 checkpoint·계약 | Tiny 추론·평가 안정, API/UI 범위 승인 | 학습/추론 오류 미해결·명세 누락 | 사용자 명시 승인 | `planned` |
| Gate 11: 배포 및 외부 평가 진입 | 배포·Benchmark·Leaderboard·라이선스 문서 | packaging·재현 실행 후보 | clean setup, artifact, license/leakage checks | 모델 카드·hash·공식 조건 snapshot | 공개 가능성·재현·평가 계약 승인 | 라이선스 불명확·누수·재현 실패 | 사용자 명시 승인·필요 시 법률 검토 | `planned` |

## 4. Gate 1 승인 기록

- [확정] 승인일: 2026-07-23
- [확정] 승인자: 사용자
- [확정] 검증 revision: `10f5f46959a018a93000987e6c20896f6c263c0a`
- [확정] 자동 테스트: 43개 수집, 43개 통과, 0개 실패(4.09초)
- [확정] CPU smoke와 CUDA smoke가 모두 통과했으며 CUDA tensor 생성·연산·동기화·해제를 확인했다.
- [확정] 검증 GPU는 `NVIDIA GeForce RTX 3060 Ti`, 총 VRAM은 8,192 MiB다.
- [확정] Git 추적 대상의 대용량 산출물 정책 위반은 0건이다.
- [확정] CUDA toolkit compiler(`nvcc`)가 PATH에서 확인되지 않았지만 표준 PyTorch 모델 구현·학습의 차단 사항은 아니다. 사용자 정의 CUDA 확장 또는 소스 빌드가 필요할 때 재검토한다.
- [확정] Gate 1 통과로 Phase 1 데이터 최소 파이프라인 진입을 허용한다. Gate 2 이후의 통과나 구현 완료를 의미하지 않는다.

## 5. Gate 2 승인 기록

- [확정] 승인일: 2026-07-23
- [확정] 승인 주체: 사용자
- [확정] 검증 revision: `c9ea945062796c1193b070cc09c00fdab0942a08`
- [확정] 자동 테스트: 기존 Phase 0 회귀 43개를 포함해 75개 수집, 75개 통과, 실패·오류·skip 0개(5.88초)
- [확정] 실제 CLI validate/build에서 입력 13, accepted 11, rejected 2, duplicate 0과 split train 10, validation 0, test 1을 확인했다.
- [확정] TXT·JSONL, 원본 checksum 불변, SHA-256, schema·NFC, exact dedup, group deterministic split, 직접 leakage 차단과 10개 계보 산출물을 검증했다.
- [확정] 입력 순서와 임시 root가 달라도 records·split·결정론적 statistics·lineage field와 dataset fingerprint가 일치했고 Windows 상대경로 처리를 확인했다.
- [확정] 기존 output 덮어쓰기와 원본 mutation·split leakage·미승인 source/license·PII 비-`clear`를 실패 처리하며 추적 산출물 위반은 0건이다.
- [확정] 이 승인으로 Phase 2 토크나이저 최소 파이프라인의 세부 계약 및 구현 준비에 진입한다. 실제 외부 corpus 승인이나 토크나이저 구현 완료를 의미하지 않는다.

DohaLM Gate 2 데이터 최소 파이프라인 승인을 확정한다. Phase 1은 UTF-8 TXT·JSONL 입력부터 checksum, validation, 정규화, exact duplicate 제거, group split, leakage·승인·라이선스·PII 차단과 계보 산출물까지 지원하며 전체 테스트와 실제 CLI 검증을 통과했다.

## 5.1 Gate 3 승인 기록

- [확정] 승인일·승인자: 2026-07-26, 사용자
- [확정] 최종 운영 tokenizer: `operating-16k-v2/unigram-16k`
- [확정] Artifact identity: bundle manifest SHA-256 `sha256:93dca331e2c82e912e832ecf4252d0638cd55e26f8802aea04d2fe7b3e043e6f`, tokenizer fingerprint `sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff`, model SHA-256 `sha256:11e536f275b9377794a52c8f3f5fadfe358f631c4b7af51bf9e371d2124fff0a`, vocab SHA-256 `sha256:9030a0cdc2fba938ac2a3fc8d0f7ae259d22b30ab22a2c57edb3d7cbcdfab11b`
- [확정] 품질 증거: 16,000 vocabulary, special ID 0~7, 실제 표본 UNK 0%, exact·ID round-trip 100%, synthetic probe 실패 0건, 전체 테스트 558개 통과
- [확정] 출력별 trainer metadata로 binary SHA만 달라도 vocabulary·encode·config·corpus·품질 근거가 모두 같으면 functional reproduction으로 인정한다. 새 binary는 별도 운영 승인이 필요하다.
- [확정] BPE는 비교 산출물로만 유지하며 운영 기본값이 아니다.
- [제외] Gate 3 통과는 Gate 7, Tiny Overfit, Pretraining, SFT, RLHF, Preference Training 또는 모델 학습 승인이 아니다.

## 6. Gate 4·5·6 승인 기록

- [확정] 승인일: 2026-07-24
- [확정] 승인자: `DDORINY`
- [확정] Gate 4·5·6 상태: `passed`
- [확정] Evidence fingerprint: `sha256:4260844cd4c48b385e60c8cd023504cbc6897a8914dfab9ec8dc0f7b746156be`
- [확정] Proposal fingerprint: `sha256:f59573ffc791833247e560da283eb684c4c97246144fea115df16d363b3798c6`
- [확정] 자동 테스트: 514개 통과
- [확정] Gate 4는 모델 구성요소, Gate 5는 전체 Tiny 통합, Gate 6은 합성 CUDA FP16 학습·checkpoint/resume·RNG·sampler·VRAM·처리량 evidence를 근거로 통과했다.
- [확정] Gate 3은 2026-07-26, Gate 7은 2026-07-27 사용자 승인으로 `passed`다. Canonical Pilot과 Candidate A 10M 단일 실행은 완료됐고 추가 학습·후속 Gate 상태 변경은 미승인이다.
- [제외] 이 승인은 실제 데이터 연결, Pilot Pretraining 실행 또는 장시간 학습 승인이 아니다.

## 6.1 Gate 7 제한 실행 기록

- [확정] 2026-07-27 사용자가 AIHUB-71748 Training 64문서와 운영 v2 Unigram을 이용한 최대 500-step Tiny Overfit만 승인했다.
- [확정] 실제 corpus loss는 `252.593750 → 5.355370`, 구간 최저 `3.694955`로 감소했고 NaN/Inf·OOM 없이 checkpoint-10→50→100→200→500 resume를 완료했다.
- [확정] 후속 승인 범위에서 동일 64문서의 LR 3개를 200 step 비교하고 단일 `1e-3` 후보만 1,000 step까지 연장했다.
- [확정] packed top-1 `99.9047%`, loss `0.006235`, 네 prefix의 16-token exact continuation, checkpoint/resume와 fingerprint 일치를 근거로 사용자 최종 승인 후 Gate 7은 `passed`다.
- [제외] 이는 동일 packed 조건의 memorization 승인이다. 전체 Pretraining, Pilot Pretraining, 문서 수 확대와 일반화 성능 승인은 포함하지 않는다.

## 7. Gate 운영 원칙

- [확정] Gate 증거에는 문서 상태, 구현 revision, 실행 명령, test 결과, experiment·artifact ID를 포함한다.
- [확정] 필수 test가 `fail`, `blocked` 또는 미실행이면 Gate를 `passed`로 표시하지 않는다.
- [확정] 실패 시 표의 복귀 단계에서 원인을 수정하고 새 증거로 재검토한다.
- [확정] 이전 Gate의 전제가 깨지면 후속 Gate 통과 상태도 영향 검토 후 무효화할 수 있다.
- [확정] 사용자 승인 없이 장시간 학습·서비스·외부 제출 Gate로 진입하지 않는다.
- [검증 필요] 승인 기록의 실제 schema와 복수 승인자가 필요한 Gate는 구현 전에 확정한다.

## 8. 미결정 사항

- [확정] EOS success, Quick 대표성 및 Candidate B 평가 계약은 2026-07-27 사용자 승인 완료
- [검증 필요] Quick v2 archive lineage와 층화 subset 설계·생성 승인
- [확정] Candidate B 첫 실행은 12,208 step 후 checkpoint 문자열 정렬 버그로 실패했으며 공식 결과·Quick·Full은 없음
- [확정] Numeric checkpoint validator와 향후 post-checkpoint quarantine 정책 보완, `execution_allowed: false`
- [검증 필요] Candidate B 새 실행에는 새 immutable Git identity·Run ID·물리 preflight·single-use training 실행 승인 필요
- [제안] Gate 이후 장기 확장은 [Foundation Model Strategy](../project/foundation-model-strategy.md)와 [Model Family Roadmap](../project/model-family-roadmap.md)의 Track A~D를 사용하되, 기존 Gate 상태나 Candidate 실행 권한을 자동 변경하지 않는다.
- [검증 필요] 각 Gate 정량 합격선과 허용 회귀 폭
- [검증 필요] 일정·담당자·승인 기록 schema
- [검증 필요] Phase 병행 범위와 `DohaLM-Small` 진입 조건
- [검증 필요] 서비스·배포 계획 문서 작성 및 승인 시점
- [검증 필요] 자동 Gate 검사와 수동 승인 경계

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | [확정] Candidate B 첫 실행 실패·승인 소비와 checkpoint validator/quarantine 보완, rerun 별도 승인 경계 반영 |
| 2026-07-28 | [확정] Candidate B backend commit 이후에도 실행 직전 clean immutable Git 재확정·physical·approval가 필요함을 반영 |
| 2026-07-27 | [확정] ADR-007, Candidate A Full baseline, EOS·Quick 대표성·Candidate B 평가 계약 승인과 Quick v2/Candidate B 비승인 경계 반영 |
| 2026-07-27 | [확정] 실제 Training 64문서의 1,000-step packed memorization·exact continuation·checkpoint/resume 증거와 사용자 최종 승인으로 Gate 7을 `passed`로 변경하고 Pretraining 미승인을 유지함 |
| 2026-07-26 | [확정] v2 Unigram 최종 운영 승인과 재현성 판정 기준을 근거로 Gate 3을 `passed`로 변경하고 Gate 7 미승인을 유지함 |
| 2026-07-26 | [검증 필요] AIHUB-71748 v2 Unigram/BPE 기술 evidence와 Unigram 추천을 반영하고 Gate 3은 사용자 승인 대기 `planned`로 유지함 |
| 2026-07-26 | [검증 필요] AIHUB-71748 제한 corpus와 Unigram/BPE 16k 후보 evidence를 연결하되 UNK·round-trip 보완 전 Gate 3 `planned`를 유지함 |
| 2026-07-24 | [확정] `DDORINY` 사용자 승인과 evidence·proposal fingerprint·514개 테스트를 근거로 Gate 4·5·6을 `passed`로 변경하고 Gate 3·7 및 데이터 승인을 유지함 |
| 2026-07-24 | [확정] ignored Tiny 산출물과 514개 테스트를 재검증해 Gate 4·5·6을 `eligible_for_user_approval`로 제안했으나 실제 상태는 `planned`로 유지하고 Pilot readiness `blocked`를 확인함 |
| 2026-07-24 | [확정] 실제 Tiny 합성 batch probe·sampler resume·10-step CUDA·100-step overfit 결과를 반영하고 Gate 6·7 `planned`를 유지함 |
| 2026-07-24 | [확정] Phase 5 합성 Trainer Foundation과 Phase 6 반복 합성 batch 준비 검증을 반영하고 Gate 6·7 `planned`를 유지함 |
| 2026-07-24 | [확정] Phase 4 전체 forward·shifted loss·greedy generation과 CPU·CUDA 검증을 반영하고 Gate 3~5 `planned`를 유지함 |
| 2026-07-24 | [확정] Phase 3 모델 구성요소·CPU/CUDA 단위 검증과 구성요소 count 일치를 반영하고 Gate 4 `planned`를 유지함 |
| 2026-07-24 | [확정] Phase 2 synthetic tokenizer smoke 구현을 반영하고 승인 corpus·운영 후보·Gate 3 미완료 경계를 유지함 |
| 2026-07-23 | [확정] AIHUB-71748 dry-run 추출 0건과 수동 검토 필요를 반영하고 Gate 3 `planned`를 유지함 |
| 2026-07-23 | [확정] AI Hub 후보 5종 구조 분석 완료를 Phase 2 선행 근거로 연결하되 schema·목적별 승인 미완료와 Gate 3 `planned`를 유지함 |
| 2026-07-23 | [확정] revision `c9ea945`의 독립 재검증과 사용자 승인에 따라 Gate 2를 `passed`, Phase 1을 구현·검증 완료로 변경함 |
| 2026-07-23 | [확정] Phase 2 상세 계약을 구현 전 필수 문서와 Gate 3 검증 기준에 연결함; Phase 2 미구현·Gate 3 `planned` 유지 |
| 2026-07-23 | [확정] Phase 2 진입에 목적별 development corpus 승인·공식 조건·fingerprint·평가 분리를 추가함; Gate 3 `planned` 유지 |
| 2026-07-23 | [확정] Phase 1 DATA-001~016 최소 구현과 synthetic fixture·CLI smoke 완료를 반영함; Gate 2 상태는 `planned` 유지 |
| 2026-07-23 | [확정] Phase 1 착수와 Gate 2의 필수 기준 문서로 Phase 1 데이터 계약을 연결함; 구현·Gate 상태는 변경하지 않음 |
| 2026-07-23 | [확정] Phase 1~6와 Gate 2~7의 공통 기능 계약으로 핵심 개발 기능명세서를 연결함; Gate 상태는 변경하지 않음 |
| 2026-07-23 | [확정] 사용자 승인과 검증 revision·43개 테스트·CPU/CUDA smoke 근거에 따라 Gate 1을 `passed`, Phase 0을 구현·검증 완료로 기록함 |
| 2026-07-23 | [확정] 사용자 승인에 따라 Gate 0을 `approved`로 기록함. 구현 완료 또는 후속 Gate 통과를 의미하지 않음 |
| 2026-07-23 | [확정] Phase 0~10과 Gate 0~11의 선행 관계·통과·복귀 원칙 정의 |
