# DohaLM 산출물 및 설정 정책

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [개발 규칙](./02-development-rules.md), [시스템 아키텍처](./03-system-architecture.md), [저장소 구조](./21-repository-structure.md) |
| 후속 문서 | `15-experiment-management.md`, `19-deployment-plan.md` 작성 예정 |
| 구현 전 필수 여부 | 예 |

- [확정] 이 문서는 설정의 기준 위치와 실행 산출물의 추적·호환성 원칙을 정의한다.
- [확정] 현재 실제 설정 로더, 실험 manifest, 체크포인트 패키지 형식은 구현되지 않았다.
- [확정] 이 문서의 Git 제외 정책은 원칙이며, 이번 단계에서 `.gitignore`를 수정하지 않는다.

## 2. 설정 범위

| 설정 범주 | 주요 항목 | 기준 상태 |
|---|---|---|
| 모델 | layer, hidden size, head, context, vocabulary, FFN, normalization, bias, weight tying | DohaLM-Tiny 구조는 [확정], Dropout·초기화는 [검증 필요] |
| 토크나이저 | SentencePiece 방식, vocabulary, 특수 토큰, normalization | Unigram·16,000은 [확정], 세부 옵션은 [검증 필요] |
| 데이터 전처리 | 입력 registry, 정제·중복 제거·분할·packing | [검증 필요] |
| 사전학습 | precision, batch, accumulation, optimizer, LR, warmup, 저장 주기 | FP16 mixed precision은 [확정], 나머지 수치는 [검증 필요] |
| SFT | 대화 템플릿, loss mask, truncation, 학습 설정 | 템플릿 원칙은 [확정], 데이터 기반 세부값은 [검증 필요] |
| 평가 | 데이터셋, metric, 생성 조건, 합격 기준 | [검증 필요] |
| 추론 | checkpoint, tokenizer, sampling, 최대 생성 길이 | [검증 필요] |
| API | host, port, timeout, 동시성, streaming | [후순위] 및 [검증 필요] |
| 프론트엔드 | API endpoint, 표시 옵션, 환경 구분 | [후순위] 및 [검증 필요] |

## 3. 설정 관리 원칙

- [확정] 실행에 영향을 주는 설정은 `configs/` 또는 명시적 실행 인자로 관리하고 소스에 중복 하드코딩하지 않는다.
- [확정] 비밀값과 개인 환경 경로는 버전 관리 설정에 넣지 않고 환경 변수 또는 로컬 전용 설정으로 주입한다.
- [확정] 개발·평가·배포 환경의 차이는 설정으로 표현하되 모델 구조 호환성을 바꾸는 값은 별도로 식별한다.
- [확정] 모든 학습·평가 실행은 적용된 최종 설정, Git revision, tokenizer ID, 데이터 ID를 기록해야 한다.
- [확정] 확정 ADR과 충돌하는 설정 변경은 일반 실험값 변경으로 처리하지 않고 ADR 재검토를 거친다.
- [확정] 체크포인트를 만들 때 적용된 모델·토크나이저 설정 snapshot을 함께 저장한다.
- [검증 필요] 설정 파일 형식, 로더 구현, schema validation 도구는 구현 전에 결정한다.

## 4. 설정 우선순위 후보

일반 설정의 권장 병합 순서는 우선순위가 높은 것부터 다음과 같다.

1. [가정] 명시적 명령행 인자
2. [가정] 실험별 설정
3. [가정] 버전 관리되는 기본 설정 파일
4. [가정] 안전한 코드 기본값

- [검증 필요] 실제 구현 전 우선순위와 병합 규칙을 승인해야 한다.
- [확정] 비밀값은 위 일반 설정 병합 체계와 분리해 환경 변수 또는 비밀 관리 수단으로만 공급한다.
- [확정] 우선순위 적용 후의 최종값을 실행 기록에 남겨야 하며 입력 파일만 기록해서는 안 된다.
- [검증 필요] 정의되지 않은 키, 형식 오류, 호환되지 않는 override를 경고로 둘지 오류로 중단할지 결정해야 한다.

## 5. 산출물 등록 정책

크기는 실측 전 확정하지 않는다. 아래의 `예상 크기 상태`는 수치가 아니라 Git 적합성을 판단하기 위한 정성 상태이다.

| 산출물 | 생산자 | 소비자 | Git 추적 | 버전 식별자 | 보존 원칙 | 재생성 가능성 | 무결성 확인 | 예상 크기 상태 |
|---|---|---|---|---|---|---|---|---|
| 원천 데이터 | 수집·반입 절차 | 정제 파이프라인 | 아니요 | dataset ID·원천 revision | 라이선스와 원천 정책 준수 | 원천 접근성에 의존 | checksum·registry | 대용량 가능, 미측정 |
| 정제 데이터 | 정제 파이프라인 | tokenizer·dataset builder | 아니요 | dataset ID·preprocess ID | 사용 실험 재현 기간 | 조건부 가능 | checksum·처리 manifest | 대용량 가능, 미측정 |
| 토큰화 데이터 | dataset builder | 사전학습·SFT loader | 아니요 | dataset ID·tokenizer ID | 원본과 재생성 비용 고려 | 가능 | shard checksum·token 범위 검사 | 대용량 가능, 미측정 |
| SentencePiece 모델 | tokenizer 학습 | 전 학습·추론 단계 | [검증 필요] | tokenizer ID | 호환 checkpoint 존속 기간 | corpus가 있으면 가능 | checksum·설정 snapshot | 미측정 |
| vocabulary 파일 | tokenizer 학습 | 검토·디버깅·추론 | [검증 필요] | tokenizer ID | SentencePiece 모델과 동일 | 가능 | checksum·크기 검사 | 미측정 |
| 모델 체크포인트 | 학습 루프 | 복원·평가·추론 | 아니요 | checkpoint ID·step | best·latest·release 정책에 따름 | 재학습 필요 | checksum·load test | 대용량, 미측정 |
| optimizer state | 학습 루프 | 학습 재개 | 아니요 | checkpoint ID·step | 재개 가능 구간 | 동일 상태 재생성 어려움 | load test·구조 검사 | 대용량 가능, 미측정 |
| scheduler state | 학습 루프 | 학습 재개 | 아니요 | checkpoint ID·step | optimizer state와 함께 | 동일 상태 재생성 어려움 | load test·step 검사 | 미측정 |
| AMP scaler state | 학습 루프 | FP16 학습 재개 | 아니요 | checkpoint ID·step | 재개 checkpoint와 함께 | 동일 상태 재생성 어려움 | load test·필드 검사 | 미측정 |
| 학습 로그 | trainer·실험 관리 | 모니터링·비교 | 원본은 아니요 | experiment ID·run ID | 요약과 원본을 구분 | 실행 재현 시 조건부 | 행 수·schema·checksum | 누적 증가, 미측정 |
| 평가 결과 | 평가 루프 | 모델 선택·보고 | 요약만 후보 | evaluation ID·checkpoint ID | 비교 대상 존속 기간 | 재평가 가능 | metric schema·checksum | 미측정 |
| 생성 샘플 | 평가·추론 | 정성 검토 | 선별본만 후보 | generation ID·checkpoint ID | 승인 근거가 되는 표본 보존 | 재생성은 seed에 의존 | prompt·설정·seed 기록 | 미측정 |
| 모델 카드 | 문서화·릴리스 절차 | 사용자·배포 검토 | 예 | model release ID | 해당 릴리스 존속 기간 | 편집 가능 | 링크·사양 검토 | 소형 문서 |
| 배포 산출물 | 패키징 절차 | 추론 서버 | 원본은 아니요 | release ID·checkpoint ID | 배포·rollback 기간 | 원본 checkpoint로 재생성 | checksum·smoke test | 대용량 가능, 미측정 |

## 6. Git 제외 원칙

다음 항목은 저장소에 직접 커밋하지 않는 것을 원칙으로 한다.

- [확정] `data/raw/`의 원천 데이터
- [확정] `data/cleaned/`의 정제 데이터 본체
- [확정] `data/tokenized/`의 shard와 캐시
- [확정] `data/sft/`의 실제 학습 데이터
- [확정] `checkpoints/`의 모델·옵티마이저 복원 상태
- [확정] 대용량 학습 로그와 profiler trace
- [확정] 환경 변수 파일과 API key 등 비밀정보
- [확정] 로컬 캐시, 임시 파일, 빌드 결과

예외적으로 추적할 수 있는 것은 라이선스·출처 registry, schema, 소형 synthetic fixture, 설정, 요약 결과, 모델 카드처럼 검토 가능하고 비밀정보가 없는 파일이다. 크기 한도와 승인 절차는 [검증 필요]이다.

## 7. 체크포인트와 설정 호환성

- [확정] 체크포인트에는 모델 state, optimizer state, scheduler state, AMP scaler state, global step/epoch, RNG state, 모델 설정, tokenizer ID, 데이터·실험 식별자, Git revision을 저장 대상으로 둔다.
- [확정] 최소 호환성 키는 vocabulary size, layer 수, hidden size, head 수, FFN size, context length, normalization, bias, weight tying, 위치 임베딩 방식이다.
- [확정] DohaLM-Tiny의 기준 사양과 예상 파라미터 16,889,856은 [모델 아키텍처](./04-model-architecture.md)와 [ADR-002](./decisions/ADR-002-tiny-model-architecture.md)를 따른다.
- [확정] tokenizer ID 또는 특수 토큰 ID가 다르면 명시적 변환 절차 없이는 호환으로 간주하지 않는다.
- [검증 필요] 체크포인트 schema version, 파일 분할, atomic save, 손상 복구와 migration 정책을 구현 전에 확정한다.

## 8. 산출물 manifest 최소 후보

| 필드 | 목적 | 상태 |
|---|---|---|
| artifact ID·type·schema version | 종류와 형식 식별 | [확정] 필요 |
| 생성 시각·생산 단계 | 계보 추적 | [확정] 필요 |
| Git revision·experiment ID | 소스와 실행 연결 | [확정] 필요 |
| config snapshot ID | 적용 설정 연결 | [확정] 필요 |
| dataset·tokenizer·checkpoint ID | 입력 의존성 연결 | [확정] 해당 시 필요 |
| 파일 목록·크기·checksum | 무결성 검증 | [확정] 필요 |
| 라이선스·접근 등급 | 사용 가능 범위 확인 | [확정] 데이터 계열에 필요 |
| 보존 기한·상태 | 정리와 rollback 판단 | [검증 필요] |

## 9. 보존과 정리 원칙

- [확정] `latest`, `best`, 배포 승인본, 실패 분석에 필요한 checkpoint의 역할을 구분한다.
- [확정] 산출물을 삭제하기 전에 상위 입력과 하위 소비자의 참조 여부를 확인한다.
- [확정] 재생성 가능하다는 이유만으로 원천 접근권·라이선스·설정 snapshot 확인 없이 삭제하지 않는다.
- [검증 필요] 보존 개수, 기간, 저장 매체, 원격 백업, 정리 승인 절차는 실제 산출물 크기와 학습 비용을 측정한 뒤 결정한다.

## 10. 미결정 사항

- [검증 필요] 설정 파일 형식과 schema validation 구현
- [검증 필요] experiment ID, artifact ID, tokenizer ID, checkpoint ID 명명 규칙
- [검증 필요] SentencePiece 모델과 vocabulary의 Git 추적 여부
- [검증 필요] 평가 요약과 생성 선별본의 크기 한도
- [검증 필요] 체크포인트 schema와 migration 정책
- [검증 필요] 로컬·외부 저장소 경계와 보존 기간
- [검증 필요] 실제 VRAM·디스크 사용량과 산출물 크기

## 11. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 설정 우선순위 후보, 산출물 registry, Git 제외 및 체크포인트 호환성 원칙의 초안 작성 |
