# DohaLM 생성 품질 평가

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [평가 계획](./10-evaluation-plan.md), [토크나이저 설계](./05-tokenizer-design.md), [SFT 계획](./09-sft-plan.md), [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md) |
| 후속 문서 | [실험 관리](./15-experiment-management.md), [재현성 정책](./29-reproducibility-policy.md), `11-inference-design.md` 작성 예정 |
| 구현 전 필수 여부 | 생성 평가 구현 전 예 |

- [확정] 현재 고정 prompt 원문, 생성 결과와 평가 점수는 없다.
- [확정] 이 문서는 prompt 범주와 등록·판정 형식만 정의하며 대량 평가 문장을 만들지 않는다.

## 2. 고정 프롬프트 세트

| 범주 | 확인 목적 | 등록 시 주의점 |
|---|---|---|
| 짧은 문장 완성 | 문법·완결·EOS | 정답 하나를 강제하지 않는 입력 후보 |
| 한국어 상식 질문 | 관련성·사실 오류 | 검증 가능한 reference·검토일 필요 |
| 간단한 설명 요청 | 이해 가능성·구조 | 대상 난이도와 기대 요소 기록 |
| 요약 요청 | 핵심 보존·환각 | 입력 본문 라이선스·길이·reference 기록 |
| 단계별 추론 요구 | 단계 연결·형식 | 내부 추론 공개를 강제하지 않고 답변 구조 평가 |
| 형식 준수 요청 | 목록·JSON 등 지시 준수 | 정확한 schema와 parser 후보 기록 |
| 영문·숫자 혼합 입력 | 혼합 문자·숫자 보존 | 원문과 변형 diff 확인 |
| 특수문자 입력 | tokenizer·decode 안정성 | 비정상 제어문자·안전한 fixture 구분 |
| 긴 입력 | context 유지·truncation | prompt token 수와 보존할 정보 기록 |
| 반복 유도 입력 | 반복 억제·붕괴 | 안전한 반복 경계와 판정 규칙 필요 |
| 알 수 없는 질문 | 불확실성 표현 | 사실을 꾸미지 않는지 확인 |
| 안전성 검토 입력 | 부적절한 응답 위험 | 민감 원문 최소화·검토 권한 구분 |

### 2.1 프롬프트 등록 필드

| 필드 | 설명 |
|---|---|
| prompt ID·version | 안정적인 식별자와 변경 version |
| category | 위 범주 중 하나 이상 |
| input·messages | 원문 또는 role 구조 |
| expected properties | 포함·회피·형식·종료 조건 |
| reference facts | 사실 검증 근거와 검토일, 해당 시 |
| source·license | 직접 작성 여부 또는 공식 출처·조건 |
| leakage fingerprint | 학습·SFT corpus 차단·검사 식별자 |
| context tokens | 사용 tokenizer 기준 입력 길이 |
| status | candidate/reviewing/approved/deprecated 후보 |
| notes | 위험·해석 한계 |

- [확정] 고정 prompt는 train·SFT 데이터와 분리하고 fingerprint로 오염 여부를 검사한다.
- [확정] prompt 변경은 기존 version을 덮어쓰지 않는다.

## 3. 생성 설정 고정

| 항목 | 기록 내용 |
|---|---|
| `temperature` | 값과 greedy 적용 여부 |
| `top-k` | 값 또는 비활성 상태 |
| `top-p` | 값 또는 비활성 상태 |
| repetition penalty | 값·적용 방식·미사용 여부 |
| maximum new tokens | 상한과 context 합산 규칙 |
| EOS 처리 | `<|end|>`, `<eos>`, 최대 길이와 stop reason |
| seed | generation seed와 sample별 파생 규칙 |
| batch size | 동시 prompt 수 |
| prompt template | template ID·version·직렬화 결과 hash 후보 |
| system message | 정확한 문구 또는 생략 정책 |
| tokenizer version | tokenizer ID·fingerprint |
| checkpoint | checkpoint ID·hash·parent experiment |

- [확정] checkpoint 비교 시 가능한 한 prompt version과 생성 설정을 동일하게 유지한다.
- [확정] tokenizer·context·stop token 차이로 동일 조건을 유지할 수 없으면 차이와 직접 비교 한계를 기록한다.
- [검증 필요] 기준 temperature·sampling·최대 생성 길이는 추론 설계와 pilot 후 확정한다.

## 4. 반복 및 붕괴 검사

| 검사 | 판정 대상 | 기록할 신호 |
|---|---|---|
| 동일 token 반복 | 같은 token의 비정상 연속 | 최대 run·위치·token ID |
| 동일 구문 반복 | n-gram·문장·문단 loop | 반복 구간·빈도 |
| EOS 미출력 | 종료 token 없이 상한 도달 | stop reason·생성 token 수 |
| 무한 생성 | 제한 없이는 계속될 패턴 | 상한 강제 종료·반복 상태 |
| 입력 복사 | prompt를 과도하게 되풀이 | overlap 후보·구간 |
| 빈 응답 | assistant 본문 없이 즉시 종료 | 생성 token·stop token |
| 비정상 특수문자 | decode 깨짐·제어문자·희귀 기호 폭증 | Unicode 분포·원문 |
| 한국어 붕괴 | 조사·어미·음절 조합이 이해 불가 | 상태·대표 구간 |
| 언어 전환 | 요구 없는 지속적 타 언어 전환 | 언어 구간·입력 조건 |
| 무관한 답변 | 질문·지시와 관련 없는 응답 | 상태·근거 |

- [확정] 자동 규칙은 후보 flag를 만들고 의미·맥락 판단은 별도 검토한다.
- [검증 필요] n-gram 길이, 반복률과 상태 판정 임계치는 기준 결과 후 확정한다.

## 5. 상태형 정성 평가

기본 상태는 `pass`, `warning`, `fail`, `not_checked`다. 각 판정은 문장 완결성, 한국어 문법, 반복, 의미 일관성, 관련성, 사실성, 지시 준수, 안전성, 혼합 문자, 긴 문맥과 EOS를 [평가 계획](./10-evaluation-plan.md)에 따라 기록한다.

- [확정] 상태만 기록하지 않고 근거가 되는 출력 구간과 오류 유형을 남긴다.
- [확정] 사실 오류, 안전성 위험과 주관적 선호를 분리한다.
- [검증 필요] 상태를 집계 점수로 변환할지는 평가자 일치도와 사용 목적을 검토한 후 결정한다.

## 6. 사람 평가

- [확정] 평가자 ID는 공개 결과에서 익명화하되 내부 감사 가능한 mapping은 접근 제한한다.
- [확정] prompt·모델 출력 순서를 무작위화하고 순서 seed를 기록한다.
- [가정] 가능한 비교에서는 모델명·checkpoint 정보를 평가자에게 숨기는 blind 평가를 사용한다.
- [확정] 같은 prompt의 모델별 출력을 같은 기준표로 비교한다.
- [확정] 평가자에게 범주 정의, `pass/warning/fail` anchor와 사실 오류 기록법을 제공한다.
- [확정] 평가자 간 불일치를 삭제하지 않고 원판정·합의 여부·사유를 보존한다.
- [확정] “선호한다”와 “사실 오류가 있다”를 별도 필드로 기록한다.
- [검증 필요] 평가자 수, 중복 평가 비율, 일치도 통계와 합의 절차는 실제 운영 전 확정한다.

## 7. SFT 전후 비교

1. [확정] SFT checkpoint의 정확한 parent pretraining checkpoint를 기준선으로 사용한다.
2. [확정] prompt set, tokenizer, chat template, system message, generation config와 평가 순서를 고정한다.
3. [확정] 같은 seed 결과와 필요 시 복수 seed 분포를 구분한다.
4. [확정] 질문 관련성·지시 준수 개선과 반복·사실성·언어·종료 회귀를 함께 본다.
5. [확정] 좋은 예시뿐 아니라 전체 상태 분포와 failure sample을 보존한다.
6. [검증 필요] SFT 성공·회귀의 수치 기준은 기준선 실행 후 결정한다.

## 8. 결과 기록

- [확정] generation evaluation ID, experiment ID, prompt version, checkpoint·tokenizer ID, 생성 설정과 환경을 연결한다.
- [확정] raw generation, decode 결과, stop reason, input/output token 수, latency와 판정을 함께 저장한다.
- [확정] 라이선스·개인정보·안전상 공개할 수 없는 prompt·출력은 접근 제한과 요약을 구분한다.
- [검증 필요] `samples.jsonl` schema와 Git 추적 가능한 선별본의 크기는 구현 전에 확정한다.

## 9. 미결정 사항

- [검증 필요] 실제 고정 prompt 원문과 승인 절차
- [검증 필요] 생성 기준 설정과 복수 seed 정책
- [검증 필요] 반복·붕괴 자동 flag 임계치
- [검증 필요] 사람 평가자 수·일치도·blind 적용 범위
- [검증 필요] 안전성 범주와 제한 결과 보관 위치

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 고정 prompt 범주·생성 설정·붕괴 검사·사람 평가·SFT 전후 비교 정책 정의 |
