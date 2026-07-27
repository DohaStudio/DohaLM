# DohaLM Definition of Done

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 규칙](./development-rules.md), [개발 로드맵](../quality/development-roadmap.md), [Definition of Ready](./definition-of-ready.md), [테스트 전략](../quality/test-strategy.md), [ADR-006](../decisions/ADR-006-development-quality-gates.md) |
| 후속 문서 | [테스트 체크리스트](../quality/testing-checklist.md), [Codex 작업 절차](./codex-workflow.md) |
| 구현 전 필수 여부 | 모든 작업 완료 판정 전 예 |

- [확정] “코드가 생성됐다”, “문서가 존재한다”, “학습이 시작됐다”만으로 완료 처리하지 않는다.
- [확정] Done은 요청 범위의 결과와 검증 증거가 모두 갖춰진 상태다.

## 2. 공통 Done 조건

- [확정] 요청 범위가 구현·작성됐고 누락이 없다.
- [확정] 요청 범위 밖 변경이 없거나 명시적으로 승인·보고됐다.
- [확정] 관련 필수 테스트가 통과했으며 실패 test가 없다.
- [확정] 실행하지 못한 test는 완료로 숨기지 않고 미검증·차단 상태로 공개한다.
- [확정] 문서·ADR·설정과 실제 구현 상태가 일치한다.
- [확정] 전체 Git diff와 최종 status를 검토했다.
- [확정] 비밀정보·credential·불필요한 개인 경로가 없다.
- [확정] 승인되지 않은 대용량 데이터·checkpoint·로그가 Git 변경에 없다.
- [확정] 완료 보고에 변경, 검증, 미실행 항목, 위험과 Git 상태가 포함된다.
- [확정] 추정·미결정·미검증 항목을 `[가정]` 또는 `[검증 필요]`로 공개한다.

## 3. 문서 Done

- [확정] 요청된 필수 목차와 표 필드가 모두 있다.
- [확정] 문서 생명주기와 본문 상태 태그가 구분돼 있다.
- [확정] 저장소 전체 Markdown 상대 링크 검사를 통과했다.
- [확정] 모델·데이터·평가 수치와 용어가 기준 문서·ADR과 일치한다.
- [확정] 존재하지 않는 예정 파일은 Markdown 링크가 아닌 코드 표기로 작성했다.
- [확정] 변경 이력과 마지막 검토일을 기록했다.
- [확정] 문서 인덱스의 목적·선후·상태·필수 여부·미결정 사항을 동기화했다.
- [확정] 결정 추가·변경 시 ADR과 ADR 인덱스를 동기화했다.
- [확정] 구현되지 않은 기능을 `implemented` 또는 완료로 표시하지 않았다.

## 4. 모델 Done

| 항목 | 완료 증거 |
|---|---|
| Shape | 모든 component·통합 input/output·residual shape test pass |
| Parameter count | DohaLM-Tiny `16,889,856` 자동 test 일치 |
| Causal mask | 미래 token 변경이 이전 logits에 영향 없음, mask 위치·broadcast 검증 |
| Forward | 정상·경계 입력 logits와 loss 계약 통과 |
| Backward | gradient 존재·finite·update 확인 |
| Weight tying | embedding·LM Head가 같은 parameter storage 사용 |
| dtype/device | CPU·GPU 후보와 FP16 경로의 의도된 dtype/device 확인 |
| 오류 조건 | 잘못된 shape·ID·context·config에 명시적 실패 |

- [확정] 외부 완성형 GPT model class로 핵심 구현을 대체하면 모델 Done이 아니다.

## 5. 학습 Done

- [확정] 고정 단일 batch에서 의도적 overfit을 검증했다.
- [확정] checkpoint를 저장하고 필수 key·hash·format을 확인했다.
- [확정] 새 process 또는 동등한 격리 조건에서 checkpoint 복원을 검증했다.
- [확정] optimizer·scheduler·AMP·RNG·sampler·step을 포함한 resume 연속성을 검증했다.
- [확정] FP16 autocast·GradScaler 순서와 skipped step·NaN/Inf 기록을 확인했다.
- [확정] gradient accumulation의 loss normalization·update 주기를 확인했다.
- [확정] training 중 NaN/Inf 감지와 중단·실패 기록을 확인했다.
- [확정] peak allocated/reserved VRAM, tokens/sec와 step time을 기록했다.
- [확정] 데이터·tokenizer·model config·experiment ID가 checkpoint와 연결된다.

## 6. 실험 Done

| 항목 | 완료 증거 |
|---|---|
| Experiment ID | 고유 ID·상태·parent/attempt 관계 |
| Git SHA | commit·branch·working tree clean 여부 |
| Resolved config | 실제 적용된 최종값·override |
| 데이터·토크나이저 fingerprint | dataset/preprocess/split·tokenizer ID/hash |
| 환경 기록 | Python·PyTorch·CUDA·Driver·GPU·OS |
| 결과 | 계획한 평가·결론·한계 |
| 실패 기록 | OOM·NaN/Inf·중단·누수 등 발생·미발생 근거 |
| 산출물 hash | checkpoint·metric·sample·환경 artifact 식별 |

- [확정] `completed`는 성능이 좋다는 의미가 아니라 계획한 실행·기록이 정상 종료됐다는 의미다.
- [확정] 누수·잘못된 설정이 발견된 실험은 결과가 있어도 `invalid`이며 Done 성공 근거로 사용하지 않는다.

### Candidate 평가 Done

- [확정] Candidate 공식 완료 판정에는 동일 identity의 Full Evaluation이 필요하며 Quick만으로 완료 처리하지 않는다.
- [확정] Candidate B는 승인된 [평가 계약](../evaluation/candidate-b-evaluation-contract.md)의 EOS·범주·position·stability·불변성·privacy·lineage 지표를 모두 보고한다.
- [확정] 임의 종합 점수 대신 지표별 필수 통과와 참고 결과를 구분한다.

## 7. API·Frontend·배포 Done 경계

- [후순위] API는 schema·오류·lifecycle·streaming·model load test를 통과해야 한다.
- [후순위] Frontend는 요청·응답·loading·오류·접근성·API 통합 test가 필요하다.
- [후순위] 배포는 clean 환경 재현, artifact hash, 비밀 분리, rollback과 모델 카드 검토가 필요하다.
- [확정] FastAPI·Next.js 파일이 존재하는 것만으로 Done이 아니다.

## 8. Done 불충족 처리

- [확정] 필수 test가 `fail`, `blocked`, `not_run`이면 완료 대신 현재 상태와 원인을 보고한다.
- [확정] 예상 실패는 명시된 test 계약과 근거가 있을 때만 구분하며 실제 회귀를 숨기지 않는다.
- [확정] 범위 안에서 고칠 수 없는 문제는 위험·선행 조건·필요 결정과 함께 넘긴다.
- [확정] 실패 결과·로그를 삭제해 완료 조건을 맞추지 않는다.

## 9. 미결정 사항

- [검증 필요] test별 정확한 합격선·허용 오차
- [검증 필요] Done 승인 기록과 승인자
- [검증 필요] 서비스·배포 상세 Done 기준

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | ADR-007에 따른 Candidate 공식 Full Evaluation과 Candidate B 평가 Done 기준 추가 |
| 2026-07-23 | [확정] 공통·문서·모델·학습·실험의 검증 기반 완료 조건 정의 |
