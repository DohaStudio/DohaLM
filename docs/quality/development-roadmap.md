# DohaLM 개발 로드맵과 단계별 Gate

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [범위와 목표](../project/scope-and-goals.md), [개발 규칙](../governance/development-rules.md), [시스템 아키텍처](../architecture/system-architecture.md), [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](../training/experiment-management.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서 | [테스트 체크리스트](./testing-checklist.md), [Definition of Ready](../governance/definition-of-ready.md), [Definition of Done](../governance/definition-of-done.md), [테스트 전략](./test-strategy.md), [위험 등록부](../governance/risk-register.md), [버전 계획](../project/version-plan.md), [Codex 작업 절차](../governance/codex-workflow.md) |
| 구현 전 필수 여부 | 예 |

- [확정] 현재는 문서화 단계이며 모델·학습·평가·서비스 구현은 완료되지 않았다.
- [확정] Phase 번호는 선행 관계를 나타내며 일정·기간을 뜻하지 않는다.
- [확정] Gate를 통과하지 못하면 후속 Phase를 완료 상태로 처리하지 않는다.

## 2. 개발 Phase

| Phase | 목적 | 선행 조건 | 작업 항목 | 결과물 | 필수 테스트 | 진입 조건 | 통과 조건 | 실패 시 복귀 | 현재 상태 |
|---|---|---|---|---|---|---|---|---|---|
| 0. 저장소와 환경 기반 | 재현 가능한 구현 기반 마련 | 기준 문서·ADR 확인 | 구조 확정, Python 기준, CUDA·PyTorch 호환 검토, 의존성·설정 구조, 기본 테스트 환경, 로그·산출물 경로 | 환경 기준, 설정 계약, 테스트 진입점 | 설정 parse, CPU smoke, CUDA 가용성 후보, 경로·Git 제외 검사 | Gate 0 통과 | Gate 1 통과와 환경 snapshot 가능 | Gate 0 문서 보완 | [검증 필요] 미구현 |
| 1. 데이터 최소 파이프라인 | 안전한 최소 입출력·계보 검증 | Phase 0, 데이터 정책 | 가상/극소량 로컬 sample, 형식 검증, 정제 흐름, manifest, checksum, split 검증 | 소형 fixture 처리 결과·manifest | 원본 불변, checksum, deterministic split, 누수 fixture | Gate 1 통과·허용 fixture 준비 | Gate 2 통과 | Phase 0 설정·경로 | [검증 필요] 미구현 |
| 2. 토크나이저 | 한국어 token 계약 확정 | Phase 1, 승인 corpus 정책 | corpus 승인, SentencePiece 학습, 특수 token, encode/decode, fingerprint, 한국어 분할 품질 | `.model`·`.vocab` 후보, mapping, 평가 보고 | vocab 16,000, ID 0~7, round-trip, fingerprint, token 통계 | Gate 2 통과·corpus approved | Gate 3 통과 | Phase 1 데이터·정규화 | [검증 필요] 미구현 |
| 3. 모델 구성요소 | 핵심 layer를 독립 검증 | Phase 0, ADR-002 | Config, token/position embedding, causal self-attention, MHA, FFN, Pre-LN, block, LM Head, weight tying | 직접 구현 모듈·단위 테스트 | shape, causal mask, backward, dtype/device, error, tying alias | Gate 1·모델 문서 승인 | Gate 4 통과 | 해당 구성요소·Config | [검증 필요] 미구현 |
| 4. 모델 통합 | DohaLM-Tiny forward·생성 연결 | Phase 2·3 | 전체 forward, loss, parameter count, dtype/device, causal mask, 최소 generation | 통합 model·loss·generation | count 16,889,856, logits shape, shift, mask, forward/backward, deterministic generation | Gate 3·4 통과 | Gate 5 통과 | Phase 2 또는 3 | [검증 필요] 미구현 |
| 5. 학습 기반 | 재개 가능한 학습 loop 구축 | Phase 1·4 | Dataset/DataLoader, AdamW, scheduler, FP16 AMP, accumulation, clipping, checkpoint, resume, log | trainer·checkpoint·log 계약 | smoke update, AMP, accumulation equivalence 후보, round-trip, resume, NaN/Inf | Gate 5 통과 | Gate 6 통과 | Phase 1 데이터 또는 4 모델 | [검증 필요] 미구현 |
| 6. 초소형 검증 | 장시간 학습 전 end-to-end 검증 | Phase 5 | 단일 batch·극소량 overfit, loss 감소, round-trip, resume, sample, CUDA peak VRAM | overfit 실험 기록·checkpoint·sample | overfit, resume 연속성, 생성, peak allocated/reserved | Gate 6 통과·experiment ready | Gate 7 통과 | Phase 4·5 | [검증 필요] 미구현 |
| 7. Tiny 소규모 사전학습 | 승인 데이터로 Tiny pilot 수행 | Phase 6, 승인 데이터 | 고정 validation, 중간 평가, 실패 복구, 자원 기록, 최종 checkpoint | pilot/final checkpoint·평가·실험 기록 | validation loss/perplexity, resume, 생성, 처리량, peak VRAM | Gate 7 통과·Gate 8 승인 | 계획 종료·평가·복원 성공 | Phase 6 또는 데이터 Phase 1 | [검증 필요] 미구현 |
| 8. SFT | 대화 형식과 응답 품질 검증 | Phase 7, 승인 SFT 데이터 | chat template, assistant loss mask, SFT 전후 평가, 생성 품질 비교 | SFT checkpoint·전후 보고서 | role/ID, mask alignment, overfit/smoke, 전후 동일 평가, 누수 검사 | Gate 8·9 통과 | SFT 기준과 복원·평가 통과 | Phase 7 또는 SFT 데이터 준비 | [검증 필요] 미구현 |
| 9. 추론과 서비스 | 검증 model을 로컬 UI까지 연결 | Phase 7 또는 8 | 추론 모듈, 로딩, 생성 옵션, FastAPI, streaming, Next.js | 로컬 추론·API·UI 후보 | model load, generation, API schema, streaming 오류, UI 연동 | Gate 10 통과 | 로컬 end-to-end와 오류 처리 통과 | 추론→API→UI 하위 단계 | [후순위] 미구현 |
| 10. 배포와 외부 평가 | 재현·공개·외부 비교 가능성 검토 | Phase 7~9, 라이선스·평가 승인 | 로컬 재현, Docker, 모델 카드, Benchmark, Leaderboard 검토 | 재현 bundle·모델 카드·검토 보고 | clean setup smoke, artifact hash, 라이선스·누수·Benchmark 계약 | Gate 11 승인 | 승인된 범위의 재현·보고 완료 | 관련 구현·데이터·평가 Phase | [후순위] 미구현 |

- [확정] Phase 3 모델 구성요소는 Phase 2와 일부 병행 가능하지만 모델 통합은 tokenizer 계약 없이 통과할 수 없다.
- [확정] Phase 9·10은 `DohaLM-Tiny`의 학습·평가 검증 이후 진행하는 후순위다.
- [검증 필요] 실제 일정, 담당자, 수치 합격선과 `DohaLM-Small` 진입 Phase는 Tiny 실측 후 결정한다.

## 3. 단계별 Gate

상태는 `planned`, `review`, `approved`, `blocked`, `passed`, `failed` 후보를 사용한다. `passed`는 문서 승인만으로 부여하지 않는다.

| Gate | 필수 문서 | 필수 구현 | 필수 테스트 | 필수 산출물 | 통과 기준 | 실패 조건 | 승인 주체 | 상태 |
|---|---|---|---|---|---|---|---|---|
| Gate 0: 문서 승인 | 프로젝트·범위·개발 규칙, ADR-001~006, 관련 설계 | 없음 | 링크·수치·상태 검토 | 승인/검토 기록 | 구현 대상·제외·테스트·미결정 사항 명확 | 확정 사양 충돌·필수 문서 누락 | 사용자 검토 | `review` |
| Gate 1: 환경 검증 | 저장소·산출물·재현성·Ready | 환경 확인·설정 loader 최소 후보 | Python/PyTorch/CUDA·CPU smoke·경로 검사 | environment snapshot·resolved config | 기준 환경에서 최소 명령 성공, 비밀·경로 문제 없음 | 의존성 충돌·CUDA 불가·재현 정보 누락 | 사용자 검토 또는 [검증 필요] | `planned` |
| Gate 2: 데이터 파이프라인 검증 | 06·07·23~26, ADR-004 | 최소 read-only 전처리·manifest·split | checksum, 원본 불변, 정제, deterministic split, 누수 fixture | 소형 manifest·통계 | 승인 fixture의 단계 연결·재실행 일치 | 원본 변경·계보 유실·split 누수 | 사용자 검토 | `planned` |
| Gate 3: 토크나이저 검증 | 05, ADR-003, 데이터 정책 | SentencePiece 학습·wrapper | vocab/ID, encode/decode, unknown·분할 통계 | tokenizer artifact·fingerprint | 16,000 vocab, special ID, round-trip·품질 검토 | ID 불일치·권리 문제·의미 손상 | 사용자 검토 | `planned` |
| Gate 4: 모델 단위 구성요소 검증 | 04, ADR-002, test strategy | 각 모델 component | shape, mask, forward/backward, dtype/device, error | 단위 테스트 결과 | 모든 필수 component test pass | 필수 실패·외부 완성 model 대체 | 사용자 검토 | `planned` |
| Gate 5: 모델 통합 검증 | 04·05·10, ADR-002·003 | Tiny forward/loss/generation | count, logits, causal 불변성, shift, tying, generation | 통합 test report | count 16,889,856과 계약 일치, 필수 test pass | shape·mask·count·NaN/Inf 실패 | 사용자 검토 | `planned` |
| Gate 6: 학습 파이프라인 검증 | 08·15·16·29 | trainer, AMP, accumulation, checkpoint/resume | smoke update, round-trip, resume, RNG, log, OOM handling | checkpoint·log·experiment metadata | 최소 step·복원·재개와 필수 기록 성공 | 복원 실패·누락 state·반복 NaN/Inf | 사용자 검토 | `planned` |
| Gate 7: 오버피팅 검증 | 08·10·15·30 | end-to-end tiny training | 단일 batch·극소량 overfit, generation, VRAM | 실험 기록·checkpoint·samples | loss 감소·복원·생성과 peak VRAM 기록 | loss 미감소·회귀·OOM 미해결 | 사용자 검토 | `planned` |
| Gate 8: Tiny 사전학습 진입 | 데이터·사전학습·평가·위험 문서 | Phase 0~6 구현 | Gate 2~7 증거, fixed validation·failure recovery | approved data, resolved config, ready experiment | 모든 선행 Gate passed·중단 조건·저장공간 확인 | 데이터 미승인·필수 test 미통과·복구 불가 | 사용자 명시 승인 | `planned` |
| Gate 9: SFT 진입 | 09·10·26·28 | SFT dataset/template/mask | role·mask·누수·SFT smoke·전 기준선 | approved SFT data·parent checkpoint·baseline | parent 검증, 동일 평가 조건, 데이터 승인 | template/mask 오류·평가 누수 | 사용자 명시 승인 | `planned` |
| Gate 10: 서비스 개발 진입 | 추론·API·frontend 계획 문서 [예정] | 검증 inference module | load·generation·latency 기준선 | 서비스 대상 checkpoint·계약 | Tiny 추론·평가 안정, API/UI 범위 승인 | 학습/추론 오류 미해결·명세 누락 | 사용자 명시 승인 | `planned` |
| Gate 11: 배포 및 외부 평가 진입 | 배포·Benchmark·Leaderboard·라이선스 문서 | packaging·재현 실행 후보 | clean setup, artifact, license/leakage checks | 모델 카드·hash·공식 조건 snapshot | 공개 가능성·재현·평가 계약 승인 | 라이선스 불명확·누수·재현 실패 | 사용자 명시 승인·필요 시 법률 검토 | `planned` |

## 4. Gate 운영 원칙

- [확정] Gate 증거에는 문서 상태, 구현 revision, 실행 명령, test 결과, experiment·artifact ID를 포함한다.
- [확정] 필수 test가 `fail`, `blocked` 또는 미실행이면 Gate를 `passed`로 표시하지 않는다.
- [확정] 실패 시 표의 복귀 단계에서 원인을 수정하고 새 증거로 재검토한다.
- [확정] 이전 Gate의 전제가 깨지면 후속 Gate 통과 상태도 영향 검토 후 무효화할 수 있다.
- [확정] 사용자 승인 없이 장시간 학습·서비스·외부 제출 Gate로 진입하지 않는다.
- [검증 필요] 승인 기록의 실제 schema와 복수 승인자가 필요한 Gate는 구현 전에 확정한다.

## 5. 미결정 사항

- [검증 필요] 각 Gate 정량 합격선과 허용 회귀 폭
- [검증 필요] 일정·담당자·승인 기록 schema
- [검증 필요] Phase 병행 범위와 `DohaLM-Small` 진입 조건
- [검증 필요] 서비스·배포 계획 문서 작성 및 승인 시점
- [검증 필요] 자동 Gate 검사와 수동 승인 경계

## 6. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] Phase 0~10과 Gate 0~11의 선행 관계·통과·복귀 원칙 정의 |
