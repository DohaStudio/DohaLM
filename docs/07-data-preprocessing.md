# DohaLM 데이터 전처리 정책

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-23 |
| 선행 문서 | [데이터 전략](./06-data-strategy.md), [데이터셋 레지스트리](./23-dataset-registry.md), [데이터 라이선스 정책](./24-data-license-policy.md), [ADR-004](./decisions/ADR-004-data-governance.md) |
| 후속 문서 | [토크나이저 설계](./05-tokenizer-design.md), [사전학습 계획](./08-pretraining-plan.md), [SFT 계획](./09-sft-plan.md), [데이터 품질 체크리스트](./25-data-quality-checklist.md), [데이터 분할 및 누수 방지](./26-data-split-and-leakage-policy.md) |
| 구현 전 필수 여부 | 예 |

- [확정] 현재 전처리 코드와 처리된 실제 데이터는 없다.
- [확정] 이 문서는 단계 간 계약을 정의하며 정확한 임계치와 구현 도구는 데이터 분석 후 확정한다.

## 2. 원본 불변 원칙

- [확정] `data/raw/`의 원본 파일은 직접 수정하거나 덮어쓰지 않는다.
- [확정] 정제 결과는 `data/cleaned/`, 토큰화 결과는 `data/tokenized/`, SFT 변환 결과는 `data/sft/`의 별도 version에 생성한다.
- [확정] 원본 checksum, dataset version, 전처리 version, 적용 설정, 코드 revision과 출력 manifest를 연결한다.
- [확정] 같은 입력·설정·코드 version으로 같은 논리 결과를 재생성할 수 있어야 한다.
- [확정] 원문 삭제 요청이나 라이선스 변경이 발생하면 파생 산출물을 역추적할 수 있어야 한다.
- [확정] 원본과 정제 데이터 본체는 Git에 커밋하지 않는다.

## 3. 전처리 단계

| 단계 | 입력 | 처리 내용 | 출력 | 실패 조건 | 로그 항목 | 재현성 정보 | 검증 방법 | 현재 상태 |
|---:|---|---|---|---|---|---|---|---|
| 1. 입력 파일 탐색 | 승인 dataset 경로·registry | 허용된 파일만 열거하고 상대경로 정렬 | 입력 파일 목록 | 경로 이탈, 미승인 파일, 접근 실패 | 파일 수·경로·제외 사유 | dataset ID·탐색 규칙 | manifest와 실제 파일 대조 | [검증 필요] 미구현 |
| 2. 파일 형식 검증 | 파일 목록 | 확장자보다 실제 형식·schema 확인 | 유효 파일 목록 | 미지원·손상·schema 불일치 | 형식별 수량·오류 | parser version·schema version | 표본 parse·오류 fixture | [검증 필요] 미구현 |
| 3. checksum 확인 | 유효 파일·registry checksum | byte checksum 계산·비교 | 검증된 원본 참조 | 불일치·누락 | 파일별 checksum·결과 | hash 알고리즘·원본 version | 재계산 비교 | [검증 필요] 미구현 |
| 4. 인코딩 정규화 | 검증된 원본 bytes | 선언·탐지 근거로 decode 후 내부 encoding 통일 | decode된 text | 복구 불가 decode 오류 | encoding·대체 문자 수 | decoder·오류 정책 | round-trip·표본 검사 | [검증 필요] 임계치 미정 |
| 5. Unicode 정규화 | decode text | 후보 Unicode normalization 적용 | 정규화 text | 의미 손상·비정상 팽창 | 전후 code point 통계 | normalization rule·version | 전후 diff·회귀 표본 | [검증 필요] rule 미정 |
| 6. HTML·Markdown·제어문자 처리 | 정규화 text | 구조 보존 필요성에 따라 markup 제거·변환, 제어문자 처리 | 본문·구조 metadata | 본문 소실·위험 markup 잔존 | 제거량·태그 종류 | parser·보존 규칙 | 전후 표본 검토 | [검증 필요] 정책 미정 |
| 7. 공백·줄바꿈 정리 | 본문 | 중복 공백·줄바꿈을 명시 규칙으로 정리 | whitespace 정제 text | 문단 경계 손실 | 변환 수·길이 변화 | whitespace rule | golden fixture 비교 | [검증 필요] 미구현 |
| 8. 비정상 반복문자 처리 | 정제 text | 반복 문자·구문 후보 탐지, 보존·축약·제외 | 반복 처리 text·flag | 과도 반복 또는 정상 표현 손상 | pattern·횟수·조치 | 반복 규칙·임계치 | 경계 사례 검토 | [검증 필요] 임계치 미정 |
| 9. 한국어 비율 검사 | 처리 text | 문자·문서별 한국어 비율 산출 | 비율·언어 flag | 목적 기준 미달 | 문자군·언어 통계 | 계산식·분모 규칙 | 표본 수동 비교 | [검증 필요] 임계치 미정 |
| 10. 문서 길이 검사 | 문서 text | 문자·문장·byte 길이와 빈 문서 검사 | 길이 통계·유효 후보 | 빈 문서·손상·범위 밖 | 분포·제외 수 | 길이 단위·경계 | 분포·경계 fixture | [검증 필요] 임계치 미정 |
| 11. 광고·스팸 필터 | 유효 후보 | 홍보 문구·키워드 나열·자동 반복 탐지 | spam score·조치 | 위험 기준 초과 | rule별 hit·표본 | rule/model version | 표본 precision 검토 | [검증 필요] 미구현 |
| 12. 개인정보·민감정보 검사 | 유효 후보 | 연락처·식별자·계정·민감정보 후보 탐지 | risk flag·격리/제외 | 검토되지 않은 고위험 항목 | 유형·수량·조치, 원문 최소화 | detector version·정책 | 비식별 fixture·수동 검토 | [검증 필요] 미구현 |
| 13. 유해 콘텐츠 검사 | 유효 후보 | 유해 범주와 맥락 위험 평가 | risk label·처리 결과 | 목적상 허용되지 않은 위험 | 범주·점수·조치 | 기준·도구 version | 층화 표본 검토 | [검증 필요] 미구현 |
| 14. 정확 중복 제거 | 승인 후보 문서 | 정규화 표현의 fingerprint로 동일 문서 그룹화 | 대표 문서·중복 mapping | hash 충돌 미처리·계보 유실 | 그룹·제거 수·대표 기준 | canonicalization·hash version | 그룹 표본·재실행 비교 | [검증 필요] 미구현 |
| 15. 근사 중복 제거 | exact dedup 결과 | 문서·구간 유사도 후보 생성과 검토 | 대표 문서·near-dup mapping | 과잉 제거·split 교차 잔존 | 임계치·그룹·조치 | 알고리즘·seed·version | 표본 precision/recall 검토 | [검증 필요] 방식·임계치 미정 |
| 16. 품질 점수 산정 | dedup 결과와 검사 feature | 복수 품질 feature 산출, 사유 보존 | 점수·flag·승인 후보 | 설명 불가 점수·필수 feature 누락 | feature·점수·분포 | 산식·version | 층화 표본 검토 | [검증 필요] 산식 미정 |
| 17. 문서 경계 처리 | 품질 통과 문서 | 문서 ID와 경계 보존, BOS/EOS용 metadata 준비 | 경계 보존 문서 | 문서 ID 유실·무관 문서 혼합 | 문서·segment 수 | boundary policy version | 경계 round-trip | [검증 필요] 세부안 미정 |
| 18. train/validation/test 분할 | dedup·경계 문서 | 문서·출처 그룹을 기준으로 deterministic split | split별 manifest | 동일·근사 문서 교차, seed 누락 | split 통계·중복 검사 | split version·seed·group key | fingerprint 교차 비교 | [검증 필요] 비율 미정 |
| 19. 토크나이저 학습 입력 생성 | 승인 train 계열 문서 | 재현 가능한 표본·line corpus 생성 | tokenizer corpus manifest | 평가 전용 데이터 포함·계보 누락 | 표본 기준·문자 통계 | sampling seed·query·version | source ID 역추적 | [검증 필요] 규모 미정 |
| 20. 사전학습 token packing | split 문서·승인 tokenizer | BOS/EOS 추가, encode, context block 구성 | token shard·block manifest | ID 범위·경계·길이 오류 | token·padding·잔여 통계 | tokenizer ID·packing version | decode 표본·경계·shape 검사 | [검증 필요] packing 미정 |
| 21. manifest 및 통계 생성 | 전 단계 출력 | 입력·출력·오류·계보·분포 요약 | versioned manifest·보고서 | 필수 필드·checksum 누락 | 전체 처리·제외·위험 통계 | 모든 version·revision | schema·checksum·재실행 비교 | [검증 필요] schema 미정 |

## 4. 단계 연결과 실패 처리

```text
승인 registry
→ 원본 탐색·형식·checksum 검증
→ 문자열 정규화·정제
→ 품질·개인정보·유해성 필터
→ exact/near dedup
→ 문서 경계 보존
→ split
├─→ tokenizer 학습 입력
└─→ 승인 tokenizer encode·packing
→ manifest·통계
```

- [확정] 필수 단계 실패 문서는 다음 단계로 조용히 전달하지 않고 사유와 원본 ID를 기록한다.
- [확정] 고위험 개인정보 원문을 일반 로그에 복사하지 않고 식별자·범주·조치만 기록한다.
- [확정] 필터 규칙 변경은 새 전처리 version을 만들며 기존 결과를 덮어쓰지 않는다.
- [확정] exact·near dedup과 split의 순서를 기록해 분할 간 중복 검사를 재현할 수 있어야 한다.

## 5. 문서 경계 정책 비교

| 방식 | 장점 | 단점·위험 | Tiny 적용 판단 |
|---|---|---|---|
| 문서마다 EOS 추가 | 경계가 명시되고 무관 문서 전이를 구분 | 짧은 문서가 많으면 경계 token 비중 증가 | [확정] 각 문서는 `<bos>`·`<eos>`를 갖는다 |
| 여러 문서를 단순 연결 | packing 효율이 높고 구현이 단순 | 경계가 없으면 문서 간 의미가 섞임 | [제외] 무경계 연결 금지; 연결 시 최소 `<eos><bos>` |
| 문서별 독립 샘플 | 문서 간 attention 누수 없음 | 짧은 문서 padding 낭비, 긴 문서 처리 필요 | [검증 필요] 기준선 후보 |
| context length까지 packing | 256-token 활용률 향상 가능 | 경계·loss·재현성 구현이 복잡, 무관 문서가 같은 context에 존재 | [가정] Tiny 사전학습 권장 후보, 통계·테스트 후 확정 |

- [확정] SFT에서 서로 무관한 대화를 한 context에 단순 packing하지 않는다.
- [검증 필요] Tiny 사전학습은 문서별 독립 샘플과 `<eos><bos>` 경계 packing의 token 활용률·loss·처리량을 비교해 최종 선택한다.
- [검증 필요] 마지막 잔여 조각의 padding·drop·다음 문서 결합 정책은 실제 길이 분포 후 결정한다.

## 6. 긴 문서 처리

### 6.1 방식 비교

| 방식 | 장점 | 단점·위험 | 적용 후보 |
|---|---|---|---|
| 앞부분만 자르기 | 단순하고 비용이 낮음 | 뒷부분 정보가 일관되게 유실됨 | [제외] 일반 기본값으로 사용하지 않음 |
| 고정 길이 chunk | 균일한 block과 높은 처리량 | 문장 중간 절단 가능 | [가정] 사전학습 후보 |
| 문장 경계 chunk | 의미 단위 보존 | 문장 분리 정확도·가변 길이 비용 | [가정] 사전학습·SFT 전처리 후보 |
| overlap chunk | 경계 문맥 보존 | 중복 학습과 데이터 가중치 증가 | [검증 필요] 기본 비활성 후보 |
| 문서별 최대 chunk 제한 | 특정 긴 문서의 과대표집 완화 | 정보 손실·한도 근거 필요 | [검증 필요] 통계 후 결정 |

### 6.2 사전학습

- [가정] 문서 경계를 보존하면서 문장 경계 또는 고정 길이 chunk를 만들고, 각 문서에 `<bos>`·`<eos>` 의미를 유지한다.
- [확정] overlap을 사용하면 중복 token 수와 문서별 가중치 변화를 통계에 포함한다.
- [검증 필요] chunk 길이, overlap, 짧은 잔여 조각과 문서별 최대 chunk 수는 실제 길이 분포로 정한다.
- [확정] `DohaLM-Tiny` 모델 입력은 최종적으로 256 token 이하여야 한다.

### 6.3 SFT

- [확정] role marker 또는 assistant 답변 중간을 임의 절단해 잘못된 대화 구조를 만들지 않는다.
- [가정] 다중 turn 초과 시 가장 오래된 완결 turn부터 제거하고 현재 user·assistant 쌍을 우선 보존한다.
- [확정] 단일 turn이 256 token을 초과하면 제외 또는 데이터셋별 명시적 축약 규칙을 적용하고 수량을 기록한다.
- [제외] SFT 표본 사이 overlap chunk로 같은 답변을 반복 생성하지 않는다.
- [검증 필요] 기본 system 문구, 줄바꿈 직렬화와 truncation 정책은 실제 길이 분포 후 확정한다.

## 7. 산출물과 저장 위치

| 산출물 | 논리 위치 | 필수 연결 정보 | Git |
|---|---|---|---|
| 원본 | `data/raw/` | dataset ID·source version·checksum | 제외 |
| 정제 문서 | `data/cleaned/` | raw checksum·preprocessing version | 제외 |
| SFT 변환 결과 | `data/sft/` | dataset·template·filter·split version | 제외 |
| token shard | `data/tokenized/` | tokenizer ID·packing·split version | 제외 |
| registry·manifest·통계 | [검증 필요] 문서 또는 향후 metadata 경로 | schema version·checksum·생성 revision | 소형·비민감 항목만 추적 후보 |

상세 Git·산출물 원칙은 [산출물 및 설정 정책](./22-artifact-and-configuration-policy.md)을 따른다.

## 8. 미결정 사항

- [검증 필요] Unicode와 SentencePiece normalization의 책임 경계
- [검증 필요] 한국어 비율, 길이, spam, 반복, 개인정보·유해성 임계치
- [검증 필요] near-duplicate 알고리즘과 임계치
- [검증 필요] 품질 점수 산식과 승인 방식
- [검증 필요] split 비율·seed·시간 기준 분할 여부
- [검증 필요] Tiny packing과 마지막 잔여 조각 처리
- [검증 필요] manifest schema와 metadata 저장 위치

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-23 | [확정] 원본 불변 원칙, 21단계 전처리 계약, 문서 경계·긴 문서 정책 초안 작성 |
