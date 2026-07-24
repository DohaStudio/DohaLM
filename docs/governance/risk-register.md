# DohaLM 위험 등록부

## 1. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서 상태 | `review` |
| 마지막 검토일 | 2026-07-24 |
| 선행 문서 | [개발 로드맵](../quality/development-roadmap.md), [GPU 메모리 전략](../training/gpu-memory-strategy.md), [실험 관리](../training/experiment-management.md), [데이터 라이선스 정책](../data/data-license-policy.md), [재현성 정책](../quality/reproducibility-policy.md) |
| 후속 문서 | Gate 승인·실험·version 검토 |
| 구현 전 필수 여부 | 예 |

- [확정] 가능성·영향·우선순위는 `low`, `medium`, `high`, `critical`, `unknown`의 정성 등급을 사용한다.
- [확정] 실제 근거 없이 발생 확률을 숫자로 작성하지 않는다.
- [확정] Phase 0 기반과 Phase 1 최소 데이터 파이프라인은 구현·검증됐다. 실제 외부 데이터·토크나이저·모델·학습은 미구현이므로 관련 위험은 `monitoring`, `mitigating` 또는 `open`으로 유지한다.

## 2. 위험 상태

`open`, `monitoring`, `mitigating`, `accepted`, `closed`, `materialized`를 사용한다. `accepted`에는 수용 근거와 승인자를 기록한다.

## 3. 위험 목록

| Risk ID | 설명 | 가능성 | 영향 | 우선순위 | 조기 징후 | 예방 조치 | 대응 조치 | 책임 영역 | 현재 상태 |
|---|---|---|---|---|---|---|---|---|---|
| R-001 | RTX 3060 Ti 8GB CUDA OOM | `unknown` | `high` | `high` | peak 급증·첫 optimizer step 실패 | micro-batch 1 기준, detached log, 사전 profiler | 환경·누수→micro-batch→accumulation→checkpointing→불필요 GPU 보존 제거→sequence 운영값→optimizer·연산 전략→ADR 기반 사양 변경 순 대응 | training/model | `monitoring` |
| R-002 | 학습 시간이 과도함 | `unknown` | `high` | `high` | 낮은 tokens/sec·pilot 예상 초과 | tiny pilot·처리량 측정·token budget gate | 범위·budget·설정 재검토, Small 연기 | training/project | `open` |
| R-003 | 저장공간 부족 | `unknown` | `high` | `high` | checkpoint·shard·log 증가 | 실행 전 여유 확인·보존 정책·hash | 학습 중단, 안전한 artifact 정리·외부 저장 검토 | artifact/training | `open` |
| R-004 | 데이터 라이선스 불명확 | `unknown` | `critical` | `critical` | 공식 조건·provider·version 누락 | registry·명시적 `approved` 상태·공식 조건·목적별 승인 | 사용 중단·rejected·법률 검토 | data/governance | `mitigating` (Gate 2 상태 차단 검증, 실제 외부 데이터 미승인) |
| R-005 | 개인정보·민감정보 포함 | `unknown` | `critical` | `critical` | 연락처·식별자·민감 sample | 명시적 PII `clear` 요구·탐지·제한 검토·원문 최소 접근 | 격리·삭제·영향 계보·재학습 검토 | data/security | `mitigating` (Gate 2 비-clear 차단 검증, 고급 자동 탐지 미구현) |
| R-006 | 평가 데이터 누수 | `unknown` | `critical` | `critical` | 비정상 고점·중복·해설 hit | group split·exact fingerprint·고정 prompt 차단 | 결과 invalid·train 제외·split 재생성 | data/evaluation | `mitigating` (Gate 2 직접 누수 차단 검증, near·semantic 미구현) |
| R-007 | Tokenizer 품질 부족 | `unknown` | `high` | `high` | unknown·token 길이·문자 붕괴 | 승인 corpus·coverage/normalization/fallback 비교 | corpus·설정 재검토, 호환성 ADR | tokenizer/data | `open` |
| R-008 | Loss 미감소 | `unknown` | `high` | `high` | overfit 실패·gradient 0·정렬 오류 | 단위·단일 batch overfit·mask test | data/shift/mask/optimizer 단계 진단 | model/training | `open` |
| R-009 | NaN/Inf 발생 | `unknown` | `high` | `high` | scaler 감소·skipped step·gradient 폭증 | AMP 순서·finite check·짧은 smoke | 중단·정상 checkpoint 복구·LR/연산 진단 | training/model | `open` |
| R-010 | Checkpoint 손상 | `unknown` | `high` | `high` | hash·load·필수 key 실패 | atomic save·저장 직후 load·checksum | 손상본 격리·직전 정상본 복구 | training/artifact | `open` |
| R-011 | Resume 실패 | `unknown` | `high` | `high` | step·LR·loss·data 순서 불연속 | optimizer/scheduler/AMP/RNG/sampler 저장·test | 장시간 학습 중단·schema 수정·재검증 | training | `open` |
| R-012 | 설정 불일치 | `unknown` | `high` | `high` | metadata와 실행값·checkpoint shape 차이 | resolved config·schema·override 기록 | 결과 invalid·호환성 검사·재실행 | config/experiment | `open` |
| R-013 | 문서·코드 불일치 | `unknown` | `high` | `high` | parameter·shape·상태 차이 | 문서 우선·같은 변경에서 갱신·regression | Gate 중단·기준 확인·ADR/코드 수정 | governance/all | `monitoring` |
| R-014 | 실험 재현 실패 | `unknown` | `high` | `high` | 같은 config에서 큰 차이·환경 누락 | Git/data/tokenizer/seed/environment 연결 | divergence 분석·새 attempt·invalid 판정 | experiment | `mitigating` (Phase 1 fingerprint·입력 순서·임시 root 결정론 검증, 학습 재현 미검증) |
| R-015 | 프로젝트 범위 과다 | `medium` | `high` | `high` | Tiny 전 서비스·Small·외부 기능 병행 | Phase·Gate·MVP·제외 범위 | 후순위로 복귀·작업 분할 | project | `monitoring` |
| R-016 | FastAPI·Next.js 조기 개발 | `medium` | `medium` | `medium` | Tiny 학습·추론 미검증 상태 UI 작업 | Gate 10과 후순위 명시 | 서비스 중단·추론/평가 Phase 복귀 | service/project | `monitoring` |
| R-017 | Small 모델 조기 확정 | `medium` | `high` | `high` | Tiny 실측 전 Layer·batch 확정 | ADR-001·Tiny Gate | 사양 철회·Tiny 실측 후 후속 ADR | model/project | `monitoring` |
| R-018 | Benchmark 과적합 | `unknown` | `high` | `high` | 반복 prompt 조정·test 점수 기반 학습 | validation/test 분리·사용 기록 | 결과 한계 공개·새 holdout 검토 | evaluation | `open` |
| R-019 | 대용량 파일 Git commit | `low` | `high` | `high` | status에 data/checkpoint/log | ignore·pre-commit 후보·diff 검토 | commit 중단·안전한 제거·노출 영향 확인 | repository/artifact | `monitoring` (Gate 1 추적 산출물 위반 0건) |
| R-020 | 비밀정보 노출 | `unknown` | `critical` | `critical` | `.env`, token, credential, 개인 endpoint | secret 분리·scan·최소 로그 | 즉시 중단·폐기/회전·이력 영향 보고 | security/all | `monitoring` (환경 identity 제외·설정/로그 masking 검증) |
| R-021 | Windows와 Linux의 경로·줄바꿈 차이로 재현 또는 도구 실행 실패 | `unknown` | `medium` | `medium` | OS별 상대경로 해석 차이·혼합 줄바꿈·shell 명령 실패 | 상대경로·플랫폼 중립 경로 API 사용, 텍스트 감사와 OS별 smoke 계획 | 실패 OS에서 재현하고 영향 파일·명령만 최소 교정 | repository/reproducibility | `monitoring` (Windows 경로·UTF-8/LF 검증, Linux 미검증) |
| R-022 | CUDA·PyTorch·NVIDIA Driver 조합의 호환 실패 | `unknown` | `high` | `high` | CUDA 미인식·kernel load 실패·지원되지 않는 compute capability | Phase 0에서 버전 조합과 환경 snapshot 검증 | 호환 행렬을 재검토하고 검증된 조합으로 환경 재구성 | environment/training | `monitoring` (PyTorch 2.7.1+cu118·Driver 610.62 CUDA smoke 통과, `nvcc` 미확인) |
| R-023 | SentencePiece 설정 또는 artifact 변경으로 checkpoint 호환성 손상 | `unknown` | `high` | `high` | tokenizer fingerprint·vocab ID·embedding shape 불일치 | tokenizer artifact와 fingerprint를 checkpoint·실험 기록에 고정 | 로드를 차단하고 호환 checkpoint 사용 또는 명시적 migration 검토 | tokenizer/model/artifact | `open` |
| R-024 | FP16 attention softmax overflow로 NaN/Inf 발생 | `unknown` | `high` | `high` | attention score 급증·softmax 비유한값·skipped step | 안정적 mask 값·AMP 경계·finite 검사를 단위 및 smoke test로 검증 | 즉시 중단하고 dtype·mask·scale·정상 checkpoint를 단계별 진단 | model/training | `open` |
| R-025 | Weight tying이 checkpoint 저장·복원 과정에서 분리됨 | `unknown` | `high` | `high` | token embedding과 LM Head가 같은 storage를 공유하지 않음 | 저장·복원 round-trip에서 alias와 값 일치를 모두 검사 | checkpoint schema·load 순서를 수정하고 영향 checkpoint 재검증 | model/training/artifact | `open` |
| R-026 | DataLoader resume 시 sample 순서가 불연속 또는 중복됨 | `unknown` | `high` | `high` | 재개 경계에서 sample ID 누락·중복·loss 궤적 단절 | sampler·RNG·epoch·offset 상태 저장과 고정 fixture 재개 테스트 | 학습을 중단하고 마지막 연속 checkpoint에서 loader state를 복구 | data/training/reproducibility | `open` |
| R-027 | 외부 평가 형식 연동 비용이 예상보다 큼 | `unknown` | `medium` | `medium` | 변환 schema·제출 형식·공식 도구 요구가 반복 변경됨 | 내부 평가 계약을 우선 고정하고 외부 형식은 Gate 11에서 snapshot | 외부 연동 범위를 축소하거나 adapter 작업을 후순위로 재계획 | evaluation/project | `open` |
| R-028 | 문서 과잉으로 핵심 구현 일정이 지연됨 | `medium` | `medium` | `medium` | 같은 결정의 반복 문서화·Gate 문서만 증가·Phase 0 미착수 | 단일 기준 문서와 Ready 최소 요건을 적용하고 중복 설명을 링크로 대체 | 중복 문서를 통합·deprecated 후보로 분류하고 구현 차단 문서만 우선 처리 | governance/project | `monitoring` |
| R-029 | 전역 Python 환경의 기존 패키지 충돌 | `medium` | `medium` | `medium` | `pip check`에서 프로젝트 외 패키지의 버전 불일치 | 격리된 `.venv`와 최소 의존성만 사용 | clean 가상환경을 재생성하고 공식 PyTorch 설치 조합으로 재검증 | environment | `monitoring` (격리 환경 검증 통과) |
| R-030 | AI 생성 문서에 중복 또는 과도한 규칙이 누적됨 | `medium` | `medium` | `medium` | 같은 규칙의 표현 차이·우선순위 충돌·검증 불가능한 요구 증가 | AGENTS 우선순위와 인덱스를 기준으로 적대적 감사·중복 검사 | 충돌 규칙을 기준 문서에 맞춰 최소 수정하고 변경 근거 기록 | governance/documentation | `monitoring` |
| R-031 | 개인 PC 장시간 학습 중 발열·전원 문제·강제 종료 발생 | `unknown` | `high` | `high` | 온도 상승·clock throttling·전원 불안정·비정상 종료 | pilot로 열·전력·저장 주기를 확인하고 충분한 냉각·여유 공간 확보 | 학습 중단·하드웨어 상태 점검·정상 checkpoint 복구·운영 시간 축소 | operations/training | `open` |
| R-032 | 환경 보고 값의 YAML·JSON 직렬화 계약 회귀 | `low` | `medium` | `medium` | `TorchVersion` 등 비표준 객체로 진단 CLI 실패·출력 형식 불일치 | 수집 계층 primitive 정규화와 실제 PyTorch YAML/JSON 회귀 테스트 | Gate 진단 중단·문제 field 식별·직렬화 계약과 테스트 수정 | environment/cli | `monitoring` (revision `10f5f469`에서 회귀 수정·검증) |
| R-033 | 처리 중 원본 데이터 변조 | `unknown` | `critical` | `critical` | 처리 전후 file checksum·파일 집합 불일치 | 원본 read-only 취급과 publish 직전 SHA-256 재검사 | `RAW_FILE_MUTATED`로 전체 실패·산출물 미게시 | data/artifact | `monitoring` (Gate 2 mutation 주입 차단 검증) |
| R-034 | 비결정적 split 또는 플랫폼 경로 차이 | `unknown` | `high` | `high` | 입력 순서·root·경로 표기 변경 시 split·fingerprint 차이 | SHA-256 group split·POSIX 상대경로·고정 seed | 결과 invalid·경로 정규화와 split 재검증 | data/reproducibility | `monitoring` (Windows·입력 순서·임시 root 검증, Linux 실측 미검증) |
| R-035 | 부분 산출물 노출 또는 기존 dataset version 덮어쓰기 | `low` | `high` | `high` | staging 잔존·필수 파일 누락·기존 output 변경 | sibling staging·검증 후 atomic publish·overwrite 거부 | 전체 실패·안전한 staging 정리·기존 version 보존 | data/artifact | `monitoring` (Gate 2 failure injection·overwrite 차단 검증) |
| R-036 | manifest count 또는 artifact checksum 불일치 | `low` | `high` | `high` | record·split·source 합계 또는 SHA-256 불일치 | publish 전 count 불변식·artifact checksum 검사 | `MANIFEST_MISMATCH` 또는 `CHECKSUM_MISMATCH`로 전체 실패 | data/artifact | `monitoring` (Gate 2 10개 artifact 정합성 검증) |
| R-037 | 승인되지 않은 source 또는 목적 상태의 데이터 처리 | `unknown` | `critical` | `critical` | approval 상태 누락·pending·rejected 입력이 pipeline에 진입 | 명시적 `approved` 상태 요구와 source 단위 사전 차단 | `UNAPPROVED_SOURCE`로 전체 실패·승인 기록 재검토 | data/governance | `monitoring` (Gate 2 pending/rejected 차단 검증) |
| R-038 | 대용량 데이터에서 메모리·처리 시간·atomic staging 비용 증가 | `unknown` | `high` | `high` | 메모리 급증·처리 지연·staging 공간 부족 | 실제 데이터 전 pilot·용량 측정·streaming 설계 검토 | 실행 중단·batch/streaming/multiprocessing 후속 설계 | data/operations | `open` (Phase 1은 소형 in-memory fixture 범위) |
| R-039 | 승인된 실제 tokenizer corpus 미확보 또는 source 분포 편향 | `unknown` | `high` | `high` | 승인 source 부족·한 source 기여율 과다·한국어 domain 편중 | Phase 1 승인 계약, source별 sampling 전후 record·문자·weight 통계 | 운영 후보 승인을 중단하고 corpus 구성·비율 재검토 | tokenizer/data | `open` |
| R-040 | NFC 입력과 SentencePiece whitespace 처리 차이로 의미·형식 손실 | `unknown` | `high` | `high` | 연속 공백·줄바꿈·문장 시작 공백 round-trip 실패 | `identity` normalization과 whitespace 문자군 fixture·실패 사례 보존 | wrapper·SentencePiece option·후보 corpus를 재검토하고 Gate 3 중단 | tokenizer/data | `mitigating` |
| R-041 | SentencePiece 비결정성 또는 운영 vocabulary 16,000 미충족 | `unknown` | `high` | `high` | 동일 입력 재학습의 piece·checksum 차이, actual piece count 부족 | version·thread·seed·resolved config 기록, `hard_vocab_limit=true`, 다층 결정론 검사 | 후보를 invalid 처리하고 corpus·option·dependency를 재검토 | tokenizer/reproducibility | `open` |
| R-042 | byte fallback의 vocabulary 잠식 또는 희귀 문자 UNK 증가 | `unknown` | `high` | `high` | 한국어 다문자 piece 감소·byte sequence 증가·UNK record 집중 | fallback off/on A/B와 coverage·UNK·piece 품질 통계 | coverage·fallback·corpus 구성을 재검토하고 승자를 보류 | tokenizer/data | `open` |
| R-043 | tokenizer 부분 artifact·version 혼동·model/checkpoint 오적용 | `unknown` | `critical` | `critical` | 필수 파일 누락·checksum/fingerprint 불일치·같은 version에 다른 mapping | 8개 필수 artifact, staging atomic publish, overwrite 차단, model/checkpoint fingerprint 연결 | load·학습을 차단하고 정상 호환 bundle로 복구 | tokenizer/model/artifact | `mitigating` |
| R-044 | AI Hub 일반 정책을 개별 dataset·subset 허가로 확대 해석 | `unknown` | `critical` | `critical` | 일반 정책만으로 학습·공개 승인 처리 | 후보·라이선스·목적별 승인 분리, 공식 원문 snapshot | 다운로드·학습 중단, 승인 철회와 공식 문의 | data/governance | `mitigating` |
| R-045 | 모델 weight·tokenizer artifact 공개 범위 불확실 | `unknown` | `critical` | `critical` | 문의 없이 Hugging Face·GitHub 공개 준비 | 공개 목적을 별도 `pending`, 공식 문의와 release gate | 공개 중단·artifact 격리·권리자 협의 | data/release | `open` |
| R-046 | 국외 반출·해외 cloud 처리 위반 | `unknown` | `critical` | `critical` | 해외 region·자동 cloud backup·국외 사용자 제공 | 저장 위치·backup 점검, 별도 합의 전 국외 처리 금지 | 전송 중단·복제본 삭제·공식 보고·영향 추적 | data/security | `mitigating` |
| R-047 | 원본·가공 text 재배포 또는 복수 source CCL 혼합 오류 | `unknown` | `critical` | `critical` | source 권리 필드 누락·다른 CCL을 단일 허가로 처리 | source/record별 권리·CCL, 원본 외부 업로드 금지 | 배포 중단·영향 subset 격리·manifest 재작성 | data/license | `open` |
| R-048 | 구매도서 corpus 암기·verbatim 재현 | `unknown` | `critical` | `critical` | 긴 원문 overlap·고유 문장 재현 | 결정론적 표본 후보, dedup·memorization·verbatim 검사 | 해당 corpus·checkpoint 공개 중단, 구성·학습 범위 재검토 | data/model | `open` |
| R-049 | 감성 대화·판례 데이터의 개인정보·민감정보 포함 | `unknown` | `critical` | `critical` | 연락처·사건정보·상담·위기 발화 탐지 | source별 PII review·대화/session 격리·원문 최소 접근 | 사용 중단·신고·삭제·영향 계보 추적 | data/security | `mitigating` |
| R-050 | 평가 subset·교정 정답·instruction QA가 학습에 혼입 | `unknown` | `critical` | `critical` | 평가 점수 급증·동일 prompt/answer·split fingerprint 교차 | 평가 제외 목록, subset 분리, exact·near·group 검사 | 결과 invalid·학습 corpus 제거·재처리 | data/evaluation | `mitigating` |
| R-051 | 공식 문의 미완료 상태에서 다운로드·학습·공개 진행 | `unknown` | `critical` | `critical` | `pending_official_confirmation`을 허용으로 취급 | approval log gate와 사용자 승인, pending 시 fail closed | 즉시 중단·상태 `restricted`·공식 확인 후 재개 | data/governance | `open` |
| R-052 | 외부 ZIP 내부의 절대·상위 이동 entry 경로로 안전하지 않은 추출 발생 | `high` | `critical` | `critical` | 중앙 디렉터리에서 안전하지 않은 entry 경로 탐지 | 자동 압축 해제 금지·경로 마스킹·격리 root·CRC·checksum·atomic publish 검증 | 추출 중단, 별도 승인된 수동 mapping과 격리 절차 검토 | data/security | `mitigating` (일반 차단 유지; 승인 mapping dry-run rule 매칭 573/0·실제 추출 0·원본 불변) |
| R-053 | 제한된 대용량 JSON prefix 구조를 전체 schema·PII 부재로 과대 해석 | `unknown` | `high` | `high` | truncated 결과를 complete schema로 기록·Tokenizer 승인 근거로 사용 | entry·전체 read byte 상한, completeness·truncated 명시, key hash·허용명만 기록 | 실제 추출·corpus 승인을 중단하고 별도 schema·PII 검토 범위 승인 | data/security | `mitigating` (5개·각 2 MiB·전체 10 MiB 관측, 모두 truncated·추출 0) |
| R-054 | 제한 read 구간의 JSON record 표본을 전체 파일 분포·PII 부재로 과대 해석 | `unknown` | `critical` | `critical` | 앞쪽 32 MiB·10개 record 통계를 전체 corpus 승인 근거로 사용 | bounded read·stable rank 범위 명시, 값 비노출, schema·PII 승인 분리 | corpus 생성을 중단하고 별도 층화·PII 검토 범위를 사용자 승인 | data/security | `mitigating` (2개 entry·3,489 record 경계 관측·10개 구조 선택·전체 parse/추출 0) |
| R-055 | 층화 후보가 단일 archive에 집중되거나 field-name 미탐지를 PII 부재로 오해 | `high` | `critical` | `critical` | 요청 archive 수 미충족·`no_field_name_signal`을 clear로 승격 | archive·entry 상한, 실제 strata 보고, 자동 `conditionally_clear` 금지, 자유서술 review 유지 | corpus 승인을 중단하고 공식 schema·비식별 설명과 비공개 사람 검토 | data/security | `mitigating` (후보 571개가 단일 archive, entry 2개·64 MiB·PII review_required 1·preview 0) |
| R-056 | 비공개 preview에 PII가 잔존하거나 보존기한 이후 남음 | `unknown` | `critical` | `critical` | Redaction 누락·review note 원문 복사·만료 파일 잔존 | 승인 만료·외부 경로·최소 text·문자 상한·수동 review·deletion manifest | review 중단, 파일 수동 삭제와 deletion 검증, 영향 범위 확인 | data/security | `mitigating` (기본 pending·실제 preview 0건, 합성 redaction·경로·만료 회귀 검증) |
| R-057 | Dataset adapter 성공을 실제 corpus·tokenizer 승인으로 오해 | `unknown` | `critical` | `critical` | `adapted` record를 승인 로그 확인 없이 split·학습에 사용 | 구조 변환과 usage 상태 분리, pending 차단 사유·content read 0 dry-run 검증 | corpus 게시·학습 중단, 영향 artifact 격리와 승인 상태 재확인 | data/governance | `mitigating` (AIHUB-71748 synthetic adapter만 구현, 실제 read·publish 0) |

## 4. 운영 원칙

- [확정] Phase·Gate·실험 시작과 완료 시 관련 위험을 재검토한다.
- [확정] 위험이 현실화되면 상태를 `materialized`로 바꾸고 incident·experiment·artifact를 연결한다.
- [확정] `critical` 위험은 사용자 검토 없이 수용하지 않는다.
- [확정] 한 조치가 다른 위험을 키우는지 기록한다. 예: checkpoint 보존은 저장공간 위험을 높일 수 있다.
- [검증 필요] 등급 산정 rubric, owner 개인 지정과 검토 주기는 프로젝트 운영 시 확정한다.

## 5. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-24 | [확정] dataset adapter 성공과 실제 corpus 승인을 혼동하는 위험 R-057 및 fail-closed 대응을 등록함 |
| 2026-07-24 | [확정] 비공개 최소 preview의 redaction 한계와 보존 만료 위험 R-056을 등록함 |
| 2026-07-24 | [확정] 단일 archive 집중과 PII field-name 미탐지 오해 위험 R-055 및 fail-closed review 대응을 등록함 |
| 2026-07-24 | [확정] 제한 record 표본 과대 해석 위험 R-054와 bounded parser·비노출·승인 분리 대응을 등록함 |
| 2026-07-24 | [확정] R-052에 rule별 mapping 관측성을 반영하고 제한 JSON 구조의 과대 해석 위험 R-053과 bounded streaming 대응을 등록함 |
| 2026-07-23 | [확정] R-052 대응으로 안전 표본 추출기와 AIHUB-71748 dry-run 전량 거부·원본 불변 근거를 반영함 |
| 2026-07-23 | [확정] AI Hub ZIP 중앙 디렉터리 분석에서 안전하지 않은 entry 경로 위험 R-052를 등록하고 자동 추출 금지를 유지함 |
| 2026-07-23 | [확정] Gate 2 결과로 라이선스·PII·누수·재현 위험을 `mitigating`으로 갱신하고 원본 변조·split·partial artifact·manifest·승인·대용량 위험 R-033~038을 등록함 |
| 2026-07-23 | [확정] Phase 2 corpus·normalization/whitespace·SentencePiece 결정론·fallback·artifact 호환성 위험 R-039~043을 등록함 |
| 2026-07-23 | [확정] AI Hub 조건 해석·공개·국외 처리·재배포·도서 암기·PII·평가 누수·미완료 문의 위험 R-044~051을 등록함 |
| 2026-07-23 | [확정] Gate 1 근거로 CUDA·경로·비밀·대용량 산출물 위험을 재검토하고 환경 출력 직렬화 회귀 위험 R-032를 등록함 |
| 2026-07-23 | [확정] 중복 Risk ID를 해소하기 위해 문서 누적 위험을 R-030, 장시간 학습 운영 위험을 R-031로 정정함 |
| 2026-07-23 | [확정] 격리 `.venv`의 clean 설치·`pip check`·CPU/CUDA smoke 통과로 R-029 완화 확인 |
| 2026-07-23 | [검증 필요] Phase 0 전역 환경 `pip check` 충돌을 R-029로 등록 |
| 2026-07-23 | [확정] Phase 0 현재 CUDA 조합 smoke 통과를 R-022 monitoring 근거로 반영 |
| 2026-07-23 | [확정] 플랫폼·환경 호환성·artifact 복원·수치 안정성·운영 및 문서화 위험 10개 추가 |
| 2026-07-23 | [확정] 하드웨어·데이터·학습·품질·범위·보안 위험 20개와 예방·대응 원칙 등록 |
