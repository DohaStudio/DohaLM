# DohaLM 위험 등록부

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 로드맵](../quality/development-roadmap.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md), [실험 관리](../training/experiment-management.md), [데이터 라이선스 정책](../data/data-license-policy.md), [재현성 정책](../quality/reproducibility-policy.md) |
| 후속 문서 | Gate 승인·실험·version 검토 |
| 구현 전 필수 여부 | 예 |

- [확정] 가능성·영향·우선순위는 `low`, `medium`, `high`, `critical`, `unknown`의 정성 등급을 사용한다.
- [확정] 실제 근거 없이 발생 확률을 숫자로 작성하지 않는다.
- [확정] 현재 구현·데이터·학습이 없으므로 위험 상태는 대부분 `open` 또는 `monitoring`이다.

## 2. 위험 상태

`open`, `monitoring`, `mitigating`, `accepted`, `closed`, `materialized`를 사용한다. `accepted`에는 수용 근거와 승인자를 기록한다.

## 3. 위험 목록

| Risk ID | 설명 | 가능성 | 영향 | 우선순위 | 조기 징후 | 예방 조치 | 대응 조치 | 책임 영역 | 현재 상태 |
|---|---|---|---|---|---|---|---|---|---|
| R-001 | RTX 3060 Ti 8GB CUDA OOM | `unknown` | `high` | `high` | peak 급증·첫 optimizer step 실패 | micro-batch 1 기준, detached log, 사전 profiler | 환경·누수→micro-batch→accumulation→checkpointing→불필요 GPU 보존 제거→sequence 운영값→optimizer·연산 전략→ADR 기반 사양 변경 순 대응 | training/model | `monitoring` |
| R-002 | 학습 시간이 과도함 | `unknown` | `high` | `high` | 낮은 tokens/sec·pilot 예상 초과 | tiny pilot·처리량 측정·token budget gate | 범위·budget·설정 재검토, Small 연기 | training/project | `open` |
| R-003 | 저장공간 부족 | `unknown` | `high` | `high` | checkpoint·shard·log 증가 | 실행 전 여유 확인·보존 정책·hash | 학습 중단, 안전한 artifact 정리·외부 저장 검토 | artifact/training | `open` |
| R-004 | 데이터 라이선스 불명확 | `unknown` | `critical` | `critical` | 공식 조건·provider·version 누락 | registry·공식 조건·목적별 승인 | 사용 중단·rejected·법률 검토 | data/governance | `open` |
| R-005 | 개인정보·민감정보 포함 | `unknown` | `critical` | `critical` | 연락처·식별자·민감 sample | 탐지·제한 검토·원문 최소 접근 | 격리·삭제·영향 계보·재학습 검토 | data/security | `open` |
| R-006 | 평가 데이터 누수 | `unknown` | `critical` | `critical` | 비정상 고점·중복·해설 hit | group split·fingerprint·고정 prompt 차단 | 결과 invalid·train 제외·split 재생성 | data/evaluation | `open` |
| R-007 | Tokenizer 품질 부족 | `unknown` | `high` | `high` | unknown·token 길이·문자 붕괴 | 승인 corpus·coverage/normalization/fallback 비교 | corpus·설정 재검토, 호환성 ADR | tokenizer/data | `open` |
| R-008 | Loss 미감소 | `unknown` | `high` | `high` | overfit 실패·gradient 0·정렬 오류 | 단위·단일 batch overfit·mask test | data/shift/mask/optimizer 단계 진단 | model/training | `open` |
| R-009 | NaN/Inf 발생 | `unknown` | `high` | `high` | scaler 감소·skipped step·gradient 폭증 | AMP 순서·finite check·짧은 smoke | 중단·정상 checkpoint 복구·LR/연산 진단 | training/model | `open` |
| R-010 | Checkpoint 손상 | `unknown` | `high` | `high` | hash·load·필수 key 실패 | atomic save·저장 직후 load·checksum | 손상본 격리·직전 정상본 복구 | training/artifact | `open` |
| R-011 | Resume 실패 | `unknown` | `high` | `high` | step·LR·loss·data 순서 불연속 | optimizer/scheduler/AMP/RNG/sampler 저장·test | 장시간 학습 중단·schema 수정·재검증 | training | `open` |
| R-012 | 설정 불일치 | `unknown` | `high` | `high` | metadata와 실행값·checkpoint shape 차이 | resolved config·schema·override 기록 | 결과 invalid·호환성 검사·재실행 | config/experiment | `open` |
| R-013 | 문서·코드 불일치 | `unknown` | `high` | `high` | parameter·shape·상태 차이 | 문서 우선·같은 변경에서 갱신·regression | Gate 중단·기준 확인·ADR/코드 수정 | governance/all | `monitoring` |
| R-014 | 실험 재현 실패 | `unknown` | `high` | `high` | 같은 config에서 큰 차이·환경 누락 | Git/data/tokenizer/seed/environment 연결 | divergence 분석·새 attempt·invalid 판정 | experiment | `open` |
| R-015 | 프로젝트 범위 과다 | `medium` | `high` | `high` | Tiny 전 서비스·Small·외부 기능 병행 | Phase·Gate·MVP·제외 범위 | 후순위로 복귀·작업 분할 | project | `monitoring` |
| R-016 | FastAPI·Next.js 조기 개발 | `medium` | `medium` | `medium` | Tiny 학습·추론 미검증 상태 UI 작업 | Gate 10과 후순위 명시 | 서비스 중단·추론/평가 Phase 복귀 | service/project | `monitoring` |
| R-017 | Small 모델 조기 확정 | `medium` | `high` | `high` | Tiny 실측 전 Layer·batch 확정 | ADR-001·Tiny Gate | 사양 철회·Tiny 실측 후 후속 ADR | model/project | `monitoring` |
| R-018 | Benchmark 과적합 | `unknown` | `high` | `high` | 반복 prompt 조정·test 점수 기반 학습 | validation/test 분리·사용 기록 | 결과 한계 공개·새 holdout 검토 | evaluation | `open` |
| R-019 | 대용량 파일 Git commit | `low` | `high` | `high` | status에 data/checkpoint/log | ignore·pre-commit 후보·diff 검토 | commit 중단·안전한 제거·노출 영향 확인 | repository/artifact | `monitoring` |
| R-020 | 비밀정보 노출 | `unknown` | `critical` | `critical` | `.env`, token, credential, 개인 endpoint | secret 분리·scan·최소 로그 | 즉시 중단·폐기/회전·이력 영향 보고 | security/all | `monitoring` |
| R-021 | Windows와 Linux의 경로·줄바꿈 차이로 재현 또는 도구 실행 실패 | `unknown` | `medium` | `medium` | OS별 상대경로 해석 차이·혼합 줄바꿈·shell 명령 실패 | 상대경로·플랫폼 중립 경로 API 사용, 텍스트 감사와 OS별 smoke 계획 | 실패 OS에서 재현하고 영향 파일·명령만 최소 교정 | repository/reproducibility | `open` |
| R-022 | CUDA·PyTorch·NVIDIA Driver 조합의 호환 실패 | `unknown` | `high` | `high` | CUDA 미인식·kernel load 실패·지원되지 않는 compute capability | Phase 0에서 버전 조합과 환경 snapshot 검증 | 호환 행렬을 재검토하고 검증된 조합으로 환경 재구성 | environment/training | `open` |
| R-023 | SentencePiece 설정 또는 artifact 변경으로 checkpoint 호환성 손상 | `unknown` | `high` | `high` | tokenizer fingerprint·vocab ID·embedding shape 불일치 | tokenizer artifact와 fingerprint를 checkpoint·실험 기록에 고정 | 로드를 차단하고 호환 checkpoint 사용 또는 명시적 migration 검토 | tokenizer/model/artifact | `open` |
| R-024 | FP16 attention softmax overflow로 NaN/Inf 발생 | `unknown` | `high` | `high` | attention score 급증·softmax 비유한값·skipped step | 안정적 mask 값·AMP 경계·finite 검사를 단위 및 smoke test로 검증 | 즉시 중단하고 dtype·mask·scale·정상 checkpoint를 단계별 진단 | model/training | `open` |
| R-025 | Weight tying이 checkpoint 저장·복원 과정에서 분리됨 | `unknown` | `high` | `high` | token embedding과 LM Head가 같은 storage를 공유하지 않음 | 저장·복원 round-trip에서 alias와 값 일치를 모두 검사 | checkpoint schema·load 순서를 수정하고 영향 checkpoint 재검증 | model/training/artifact | `open` |
| R-026 | DataLoader resume 시 sample 순서가 불연속 또는 중복됨 | `unknown` | `high` | `high` | 재개 경계에서 sample ID 누락·중복·loss 궤적 단절 | sampler·RNG·epoch·offset 상태 저장과 고정 fixture 재개 테스트 | 학습을 중단하고 마지막 연속 checkpoint에서 loader state를 복구 | data/training/reproducibility | `open` |
| R-027 | 외부 평가 형식 연동 비용이 예상보다 큼 | `unknown` | `medium` | `medium` | 변환 schema·제출 형식·공식 도구 요구가 반복 변경됨 | 내부 평가 계약을 우선 고정하고 외부 형식은 Gate 11에서 snapshot | 외부 연동 범위를 축소하거나 adapter 작업을 후순위로 재계획 | evaluation/project | `open` |
| R-028 | 문서 과잉으로 핵심 구현 일정이 지연됨 | `medium` | `medium` | `medium` | 같은 결정의 반복 문서화·Gate 문서만 증가·Phase 0 미착수 | 단일 기준 문서와 Ready 최소 요건을 적용하고 중복 설명을 링크로 대체 | 중복 문서를 통합·deprecated 후보로 분류하고 구현 차단 문서만 우선 처리 | governance/project | `monitoring` |
| R-029 | AI 생성 문서에 중복 또는 과도한 규칙이 누적됨 | `medium` | `medium` | `medium` | 같은 규칙의 표현 차이·우선순위 충돌·검증 불가능한 요구 증가 | AGENTS 우선순위와 인덱스를 기준으로 적대적 감사·중복 검사 | 충돌 규칙을 기준 문서에 맞춰 최소 수정하고 변경 근거 기록 | governance/documentation | `monitoring` |
| R-030 | 개인 PC 장시간 학습 중 발열·전원 문제·강제 종료 발생 | `unknown` | `high` | `high` | 온도 상승·clock throttling·전원 불안정·비정상 종료 | pilot로 열·전력·저장 주기를 확인하고 충분한 냉각·여유 공간 확보 | 학습 중단·하드웨어 상태 점검·정상 checkpoint 복구·운영 시간 축소 | operations/training | `open` |

## 4. 운영 원칙

- [확정] Phase·Gate·실험 시작과 완료 시 관련 위험을 재검토한다.
- [확정] 위험이 현실화되면 상태를 `materialized`로 바꾸고 incident·experiment·artifact를 연결한다.
- [확정] `critical` 위험은 사용자 검토 없이 수용하지 않는다.
- [확정] 한 조치가 다른 위험을 키우는지 기록한다. 예: checkpoint 보존은 저장공간 위험을 높일 수 있다.
- [검증 필요] 등급 산정 rubric, owner 개인 지정과 검토 주기는 프로젝트 운영 시 확정한다.

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 플랫폼·환경 호환성·artifact 복원·수치 안정성·운영 및 문서화 위험 10개 추가 |
| 2026-07-23 | [확정] 하드웨어·데이터·학습·품질·범위·보안 위험 20개와 예방·대응 원칙 등록 |
