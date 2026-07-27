# 외부 Benchmark 정책

- 문서 상태: `review`
- 마지막 검토일: 2026-07-27
- 태그: `evaluation`, `benchmark`, `license`, `contamination`

현재 외부 benchmark는 `disabled`다. 프레임워크나 CLI는 dataset을 다운로드하지 않고 승인되지 않은 adapter를 실행하지 않는다.

코드 interface는 `src/evaluation/benchmarks.py`의 `BenchmarkRegistration`과 `BenchmarkAdapter`다. 등록 정보가 모두 충족돼도 공개 example config의 `external_benchmark: disabled`를 별도 승인 없이 바꾸지 않는다.

향후 adapter는 dataset ID/version, license 검토, evaluation 목적 승인, contamination 검사, redistribution 상태, download 상태와 local logical path를 선언해야 한다. 하나라도 미확정이면 `not_approved` 또는 `evaluation_blocked`로 종료한다. API 기반 LLM judge도 별도 승인 대상이다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-27 | 외부 benchmark interface의 fail-closed 필드와 다운로드 금지 반영 |
