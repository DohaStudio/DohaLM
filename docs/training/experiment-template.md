# DohaLM 실험 기록 템플릿

## 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [평가 계획](../evaluation/evaluation-plan.md), [실험 관리](./experiment-management.md), [재현성 정책](../quality/reproducibility-policy.md) |
| 후속 문서 | 실제 실험 기록 [검증 필요] |
| 구현 전 필수 여부 | 실험 시작 전 예 |

- [확정] 아래는 새 실험 문서에 복사해 사용하는 양식이다.
- [확정] 대괄호 placeholder는 실제 근거로 교체하며 임의 수치를 채우지 않는다.
- [확정] 비밀정보, credential, 불필요한 사용자 로컬 절대경로를 기록하지 않는다.

---

# [실험 ID] [실험명]

## 1. 실험 ID

- `experiment_id`: `[EXP-NNNN-purpose]`
- `run/attempt_id`: `[검증 필요]`
- 상태: `[planned | ready | running | completed | failed | stopped | invalid | archived]`
- 생성일: `[YYYY-MM-DD 및 timezone]`
- 시작일: `[미실행 | timestamp]`
- 종료일: `[미종료 | timestamp]`

## 2. 실험명

`[사람이 읽을 수 있는 짧은 이름]`

## 3. 목적

- 확인할 질문: `[한 문장]`
- 실험 유형: `[구현 검증 | overfit | 사전학습 | SFT | 평가 | 자원 | 회귀 | 기타]`

## 4. 가설

`[변경 변수가 어떤 관측 결과를 만들 것으로 예상하는지와 반증 조건]`

## 5. 배경

`[이 실험이 필요한 이유와 관련 문제]`

## 6. 선행 실험

| 실험 ID | 관계 | 참고 결과 |
|---|---|---|
| `[없음 또는 ID]` | `[baseline | parent | 재시도 | 비교]` | `[링크 또는 요약]` |

## 7. 변경 변수

| 변수 | 기준값 | 실험값 | 변경 이유 |
|---|---|---|---|
| `[변수]` | `[값]` | `[값]` | `[근거]` |

## 8. 고정 변수

| 범주 | 고정 항목 | 값·version |
|---|---|---|
| 코드 | Git revision | `[SHA]` |
| 모델 | 구조·설정 | `[model config version]` |
| 토크나이저 | model·special token | `[tokenizer ID/version]` |
| 데이터 | dataset·preprocessing | `[ID/version]` |
| 분할 | split·seed | `[version/seed]` |
| 평가 | validation·prompt·metric | `[evaluation version]` |

## 9. 모델 설정

| 항목 | 값 |
|---|---|
| 모델명 | `[DohaLM-Tiny | DohaLM-Small]` |
| 설정 version | `[ID]` |
| Context Length | `[resolved value]` |
| Precision | `[resolved value]` |
| Gradient Checkpointing | `[on | off]` |
| 기타 override | `[없음 또는 목록]` |

## 10. 토크나이저

- Tokenizer ID/version: `[ID/version]`
- Model·vocab hash: `[hash]`
- Vocabulary Size: `[resolved value]`
- Special-token mapping version: `[version]`
- Normalization·byte fallback: `[resolved setting]`

## 11. 데이터셋

| 목적 | Dataset ID/version | Preprocessing version | Fingerprint |
|---|---|---|---|
| train | `[ID/version]` | `[version]` | `[hash]` |
| validation | `[ID/version]` | `[version]` | `[hash]` |
| test | `[해당 없음 또는 ID/version]` | `[version]` | `[hash]` |

## 12. 분할

- Split version: `[version]`
- Split seed: `[seed]`
- Group·leakage 검사: `[결과 참조]`
- 평가 데이터 오염 상태: `[not_checked | pass | warning | fail]`

## 13. 학습 설정

| 항목 | 값 |
|---|---|
| Optimizer / Scheduler | `[resolved value]` |
| Learning Rate | `[resolved value]` |
| Weight Decay | `[resolved value와 parameter group]` |
| Warmup | `[step 또는 비율]` |
| Micro-batch Size | `[resolved value]` |
| Gradient Accumulation | `[resolved value]` |
| Effective Batch | `[산식과 값]` |
| Max Steps | `[resolved value]` |
| Token Budget | `[resolved value와 token 정의]` |
| Checkpoint Interval | `[단위와 값]` |
| Evaluation Interval | `[단위와 값]` |
| Seed map | `[재현성 기록 참조]` |

## 14. 실행 환경

| 항목 | 값 |
|---|---|
| OS | `[version]` |
| Python | `[version]` |
| PyTorch | `[version/build]` |
| CUDA / Driver | `[version]` |
| GPU / VRAM | `[name/capacity]` |
| Git commit / branch | `[SHA/branch]` |
| Working tree clean | `[true | false]` |
| 환경 snapshot | `[artifact 참조]` |

## 15. 실행 명령

```text
[비밀값과 개인 절대경로를 제거한 재현 명령]
```

## 16. 평가 방법

- Evaluation ID/version: `[ID/version]`
- Validation split: `[ID/version]`
- Metrics: `[목록과 집계 방식]`
- Generation prompt/config: `[version]`
- Benchmark: `[해당 없음 또는 승인 ID/version]`
- 비교 baseline: `[experiment/checkpoint ID]`

## 17. 성공 기준

- `[실행 전 정의한 상태·지표·기능 기준]`
- [검증 필요] 수치 기준은 기준 실험 근거를 링크한다.

## 18. 중단 기준

- `[OOM, NaN/Inf, 손실, 시간, 데이터·누수, 복원 등 해당 기준]`

## 19. 결과

- 최종 상태: `[미실행 | 상태]`
- 요약: `[실행 후 작성]`
- Result artifact: `[참조]`

## 20. 정량 지표

| 지표 | 기준선 | 결과 | 단위·데이터 범위 | 해석 |
|---|---:|---:|---|---|
| Training Loss | `[미측정]` | `[미측정]` | `[정의]` | `[실행 후]` |
| Validation Loss | `[미측정]` | `[미측정]` | `[정의]` | `[실행 후]` |
| Perplexity | `[미측정]` | `[미측정]` | `[평가 계약]` | `[실행 후]` |
| Tokens/sec | `[미측정]` | `[미측정]` | `[측정 구간]` | `[실행 후]` |

## 21. 생성 샘플

- Prompt set/version: `[ID/version]`
- Generation config: `[ID 또는 전체 resolved 값 참조]`
- 전체 sample artifact: `[참조]`
- 대표 성공·실패 사례: `[실행 후, 선택 기준 포함]`

## 22. 자원 사용량

| 항목 | 값 | 측정 조건 |
|---|---|---|
| Peak allocated VRAM | `[미측정]` | `[구간·warm-up]` |
| Peak reserved VRAM | `[미측정]` | `[구간·warm-up]` |
| Step Time | `[미측정]` | `[optimizer/micro-step 구분]` |
| First-token Latency | `[미측정 또는 해당 없음]` | `[prompt·동기화]` |
| Total Duration | `[미측정]` | `[시작·종료 범위]` |
| Checkpoint Size | `[미측정]` | `[포함 state]` |

## 23. 실패 및 이상 현상

| 시각/step | 유형 | 관측 | 영향 | 조치·artifact |
|---|---|---|---|---|
| `[없음 또는 값]` | `[OOM | NaN/Inf | loss | data | checkpoint | environment | leakage | 기타]` | `[내용]` | `[범위]` | `[조치]` |

## 24. 결론

- 가설 판정: `[미판정 | 지지 | 기각 | 불충분]`
- 근거: `[지표·샘플·실패 참조]`
- 한계: `[비결정성·데이터·평가·자원 제한]`

## 25. 다음 작업

- `[후속 실험·수정·문서 검토]`

## 26. 관련 commit

- Git commit: `[SHA]`
- 관련 PR/변경: `[없음 또는 참조]`

## 27. 관련 checkpoint

| 역할 | Checkpoint ID | Hash | Parent | 상태 |
|---|---|---|---|---|
| `[latest | best | final | failure-analysis]` | `[ID]` | `[hash]` | `[parent]` | `[존재 | 삭제 | 손상 | 해당 없음]` |

## 템플릿 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 평가·재현성·실패·산출물 연결을 포함한 실험 기록 양식 작성 |
