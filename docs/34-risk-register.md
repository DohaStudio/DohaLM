# DohaLM 위험 등록부

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 로드맵](./17-development-roadmap.md), [GPU 메모리 전략](./16-gpu-memory-strategy.md), [실험 관리](./15-experiment-management.md), [데이터 라이선스 정책](./24-data-license-policy.md), [재현성 정책](./29-reproducibility-policy.md) |
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

## 4. 운영 원칙

- [확정] Phase·Gate·실험 시작과 완료 시 관련 위험을 재검토한다.
- [확정] 위험이 현실화되면 상태를 `materialized`로 바꾸고 incident·experiment·artifact를 연결한다.
- [확정] `critical` 위험은 사용자 검토 없이 수용하지 않는다.
- [확정] 한 조치가 다른 위험을 키우는지 기록한다. 예: checkpoint 보존은 저장공간 위험을 높일 수 있다.
- [검증 필요] 등급 산정 rubric, owner 개인 지정과 검토 주기는 프로젝트 운영 시 확정한다.

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 하드웨어·데이터·학습·품질·범위·보안 위험 20개와 예방·대응 원칙 등록 |
