# DohaLM Benchmark 정책

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [평가 계획](./10-evaluation-plan.md), [데이터 라이선스 정책](./24-data-license-policy.md), [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md), [ADR-005](./decisions/ADR-005-evaluation-and-experiment-policy.md) |
| 후속 문서 | [실험 관리](./15-experiment-management.md), [재현성 정책](./29-reproducibility-policy.md), `20-leaderboard-strategy.md` 작성 예정 |
| 구현 전 필수 여부 | 외부 Benchmark 적용 전 예 |

- [확정] 현재 최종 채택한 외부 Benchmark와 실행 결과는 없다.
- [확정] 외부 Benchmark의 최신 규정·버전·라이선스는 실제 적용 시점에 공식 출처에서 다시 확인한다.

## 2. 내부 평가와 외부 Benchmark

| 구분 | 내부 평가 | 외부 Benchmark |
|---|---|---|
| 목적 | 구현·학습 진행·회귀·생성 품질 확인 | 외부 정의 task와의 비교 가능성 검토 |
| 데이터 | 프로젝트가 승인·version 관리 | 외부 제공자 조건·version에 의존 |
| 변경 가능성 | 프로젝트 절차로 version 변경 | 공식 규정에 따라 변경 가능 |
| 결과 해석 | 동일 프로젝트 조건의 상대 비교 중심 | prompt·tokenizer·평가 코드 차이를 포함해 제한적으로 비교 |
| 현재 상태 | [검증 필요] 구현 전 | [후순위] 후보 미정 |

- [확정] 내부 validation과 Benchmark를 같은 이름이나 같은 합격선으로 혼용하지 않는다.
- [확정] 공개 leaderboard 점수와 로컬 재현 점수를 별도 필드로 기록한다.

## 3. 채택 전 검토

1. [확정] 공식 제공자, 데이터·평가 코드 version과 문서 링크를 확인한다.
2. [확정] 평가 데이터 사용·다운로드·변형·결과 공개·재배포 라이선스를 검토한다.
3. [확정] 학습 corpus, SFT 데이터, tokenizer corpus와 문제·정답·해설의 누수 가능성을 검사한다.
4. [확정] 입력 형식, prompt template, zero-shot·few-shot, 생성·채점 조건을 식별한다.
5. [확정] `DohaLM-Tiny`의 context 256과 tokenizer 16,000 제약에서 평가가 성립하는지 확인한다.
6. [검증 필요] task 적합성, 계산 비용과 8GB 환경 실행 가능성을 검토한다.
7. [확정] 근거가 충족되기 전 특정 Benchmark를 공식 평가 대상으로 표시하지 않는다.

## 4. 데이터 누수 방지

- [확정] Benchmark 평가 문제·정답을 학습·SFT 데이터나 고정 prompt에 수동으로 추가하지 않는다.
- [확정] 문제 표현 변경, 답변 포함 문서와 Benchmark 해설을 직접 중복과 별도로 검사한다.
- [확정] 공개 해설·풀이·문제 모음의 fingerprint와 가능한 semantic 후보를 학습 데이터와 비교한다.
- [확정] 오염이 확인되면 해당 결과를 `invalid` 후보로 표시하고 영향 범위를 기록한다.
- [확정] 검사하지 못한 범위는 누수가 없다고 단정하지 않고 한계로 보고한다.
- [제외] 비공개 평가 문제·정답을 복원·추정하거나 결과를 이용해 문제를 수집하려는 시도를 금지한다.

## 5. 실행 조건 기록

| 항목 | 기록 원칙 |
|---|---|
| Benchmark 이름·version | 공식 식별자와 취득·검토일 기록 |
| 평가 코드 version | Git SHA, package version 또는 checksum |
| 모델·checkpoint | model config version, checkpoint ID·hash |
| tokenizer | tokenizer ID·version·fingerprint |
| prompt | 정확한 template와 전처리·truncation 규칙 |
| shot 조건 | zero-shot 또는 few-shot, 예시 선택·순서·seed |
| 생성 설정 | temperature, top-k, top-p, 최대 token, stop 규칙 등 고정 |
| 채점 | parser·normalization·metric과 실패 처리 |
| 데이터 | Benchmark split·version·라이선스·오염 검사 결과 |
| 환경 | Python·PyTorch·CUDA·GPU·precision |
| 실행 명령 | 비밀값·로컬 절대경로를 제거한 재현 명령 |

- [확정] 모델별 tokenizer·prompt 차이가 불가피하면 차이와 예상 영향을 결과 옆에 기록한다.
- [확정] 서로 다른 모델에 동일 생성 설정을 적용할 수 없다면 각 설정을 공개하고 직접 비교 제한을 명시한다.

## 6. 결과 보고 원칙

- [확정] local score, 공식 제출 score, 공개 leaderboard score를 구분한다.
- [확정] 단일 점수만이 아니라 Benchmark version, split, shot, prompt, tokenizer, 평가 코드와 실행일을 함께 보고한다.
- [확정] 실패·파싱 오류·제외 문항 수를 숨기지 않는다.
- [확정] Leaderboard 점수를 범용 한국어 능력이나 실제 서비스 품질의 완전한 증거로 과대 해석하지 않는다.
- [확정] 공개 점수 비교에는 model size, 학습 데이터, tokenizer와 추론 조건 차이가 있음을 명시한다.
- [검증 필요] 여러 seed 또는 bootstrap 등 불확실성 보고 방식은 Benchmark 특성에 따라 결정한다.

## 7. 후보와 확정 상태

| 상태 | 의미 |
|---|---|
| `candidate` | 이름만 식별되었고 조건 검토 전 |
| `reviewing` | 라이선스·누수·형식·비용 검토 중 |
| `approved` | 특정 version과 평가 조건이 승인됨 |
| `rejected` | 목적·권리·오염·비용 문제로 사용하지 않음 |
| `deprecated` | version 변경·오염·대체로 신규 비교 중단 |

- [확정] 현재 모든 외부 Benchmark는 미등록 상태이며 어떤 대상도 `approved`가 아니다.
- [검증 필요] 실제 후보 목록은 평가 목표와 최신 공식 조건을 조사한 뒤 별도 등록한다.

## 8. 미결정 사항

- [검증 필요] 외부 Benchmark 후보·version·라이선스
- [검증 필요] Benchmark registry의 저장 형식과 승인 책임자
- [검증 필요] context 256 초과 입력 처리와 비교 공정성
- [검증 필요] 오염 검사 범위와 semantic leakage 탐지 방법
- [검증 필요] 공식 제출 여부와 최신 Leaderboard 규정

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 내부·외부 평가 구분, Benchmark 채택·누수·실행·보고 원칙 정의 |
