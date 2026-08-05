# General Instruct Adapter 후보 선정 결과

- 문서 상태: `review`
- 마지막 검토일: 2026-08-05
- 기준 브랜치·커밋: `develop` · `74f9b41246502a8c0c255ac74fce082eff12df4c`
- 선정 결과: `no_eligible_candidate`
- 관련 문서: [Instruct Strategy](./instruct-strategy.md), [Adapter Runtime](../service/dohalm-adapter-runtime.md), [Current Project Status](../project/current-project-status.md)

## 1. 범위와 판정

[확정] 이 조사는 문서에 기록된 Qwen 기반 General Instruct QLoRA 계보와 명시적인 Git 외부 artifact root만
읽기 전용으로 확인했다. Foundation Candidate B 계보, 새 학습, weight 수정, 자동 탐색, 네트워크 다운로드와
publication은 범위에서 제외했다.

[확정] v0.1·v0.2의 canonical 평가가 모두 배포 후보를 선택하지 않았고 v0.3는 학습을 시작하지 않았다.
따라서 이번 선정 결과는 `no_eligible_candidate`다. 이 판정에 따라 실제 manifest·runtime metadata를 만들지 않았고,
Base+Adapter GPU load와 Provider Chat·SSE smoke도 시작하지 않았다.

## 2. 후보 inventory

| 후보 | Training Run | Dataset·component | 학습 | Adapter artifact | `adapter_config.json` | `adapter_model.safetensors` | 평가 | Known failure | Runtime·publication 적격성 |
|---|---|---|---|---|---|---|---|---|---|
| Runtime v0.1 final Adapter | `DOHALM-V0.1-QLORA-20260731-0005` | AIHUB-71748 SFT Processing Run 0015, Tokenization 0001 | 3 epoch·1,947 step 완료 | Git 외부 보존, reload 검증 | 있음 | 있음, 73,911,112 bytes | 독립 평가 완료, decoding 평가 완료 | decoding hard blocker 통과 후보 0, `NO_CANDIDATE_PASSED_HARD_BLOCKERS` | Runtime 부적격, publication 미승인 |
| Runtime v0.2 final Adapter·terminal checkpoint | `DOHALM-V0.2-QLORA-20260801-0001` | v0.2 Sidecar·Weighted Tokenization | 2 epoch·1,298 step 완료 | `.failed` 감사 artifact에 보존 | 있음 | 있음, 73,911,112 bytes | evaluation-only recovery 완료 | 원래 `CHECKPOINT_SCHEDULE_INVALID`; recovery 결과 eligible candidate 0 | Runtime 부적격, publication 미승인 |
| Runtime v0.3 | 해당 없음 | Short-answer Dataset·Tokenization 후보 | 미시작 | 없음 | 없음 | 없음 | 없음 | Tokenization publish 관측성 손실, 재시도·QLoRA 미승인 | 후보 제외 |

### 2.1 Identity·metadata·dependency

| 항목 | v0.1 | v0.2 | v0.3 |
|---|---|---|---|
| Base model | `Qwen/Qwen2.5-1.5B-Instruct` | 동일 | 동일 후보 |
| Base revision | `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` | 동일 | 문서 후보만 존재 |
| Tokenizer identity | fingerprint `ad0a85da869c2e4577b9409df0c91e35be70f0395a20c94765c6f4fa02ea6a55` | 동일 | 고정 artifact 없음 |
| Chat Template identity | 공식 Qwen template 사용 기록은 있으나 Task 1용 독립 SHA-256 없음 | 동일 | 없음 |
| Source commit | training `070ff44ee6037d8cb627b88490b1a2d2b6aa0ea4` | training `a4d3ab5e5adf1e4d41789c297bdb28f6ece9810f` | 없음 |
| Evaluation fingerprint | `sha256:1544e55c5018e014e1be339998bc75faab86443bc61493cff97d72c13538752c` | recovery manifest `sha256:7cb07b0d9d186e190db65bff2a1ae633757408870854eb8c2a476e9887bc123a` | 없음 |
| Task 2 runtime metadata | 필요한 lineage는 분산 보존됐지만 canonical metadata artifact 없음 | recovery metadata는 있으나 Task 2 runtime metadata artifact 없음 | 없음 |
| Generation config artifact | Task 1·2 schema에 맞는 별도 immutable artifact 없음 | 동일 | 없음 |
| Dependency tuple | PEFT 0.18.1, Transformers 4.57.6, Torch 2.7.1+cu118 | 동일 | 해당 없음 |
| 보조 dependency | Accelerate 1.12.0; 현재 보존 venv의 Safetensors 0.8.0 | 동일 학습 환경 계보 | 해당 없음 |

[확정] PEFT·Transformers·Torch·Accelerate는 보존된 학습 환경 metadata로 확인했다. Safetensors는 당시 environment에
기록되지 않았고 현재 보존 WSL venv에서 0.8.0만 관측됐으므로 학습 시점의 exact version으로 고정하지 않는다.
적격 후보가 없으므로 `requirements-inference.txt`, `pyproject.toml`과 현재 `.venv`는 변경하지 않았다.

## 3. Artifact checksum과 평가 근거

- v0.1 Training Run root의 기존 `checksums.sha256`: 전체 항목 `OK`
- v0.1 독립 평가의 기존 `checksums.sha256`: 전체 항목 `OK`
- v0.1 decoding 평가의 기존 `checksums.sha256`: 전체 항목 `OK`
- v0.2 recovery의 기존 `checksums.sha256`: 전체 항목 `OK`
- v0.2 failed training artifact는 recovery manifest의 before·after fingerprint가
  `sha256:7543cdb8c0c08a450c8079acda54c6a12c75c6e4127dc3565f4d3f6ff8b6a384`로 동일하다.

[확정] checksum 통과는 artifact 보존 무결성을 의미할 뿐 Runtime eligibility를 부여하지 않는다.

## 4. 후보별 적격성

### v0.1

- 학습·artifact·Base·Tokenizer·source commit·dependency와 최소 평가 evidence는 존재한다.
- 독립 평가는 `CONDITIONAL_PASS`였지만 `serious_regression_rate=0.8125`, `deployment_ready=false`였다.
- 후속 decoding 평가는 `selected_candidate=null`, `NEEDS_MODEL_IMPROVEMENT`,
  `NO_CANDIDATE_PASSED_HARD_BLOCKERS`로 종료됐다.
- Chat Template 독립 hash, Task 2 canonical metadata와 generation config artifact도 없다.
- 판정: 제외.

### v0.2

- 학습은 완료됐고 terminal checkpoint와 final Adapter가 보존됐다.
- evaluation-only recovery는 원본 failure를 수정하지 않고 완료됐다.
- canonical 결과는 `eligible_candidates=[]`, `selected_candidate=null`, `deployment_ready=false`,
  `NEEDS_MODEL_IMPROVEMENT`다.
- 판정: 명시적인 평가 부적격으로 제외.

### v0.3

- Tokenization publish가 완료되지 않았고 QLoRA 학습·Adapter·평가가 없다.
- 판정: 필수 artifact 누락으로 제외.

## 5. Manifest·preflight·GPU 실행 상태

```yaml
candidate_selection: no_eligible_candidate
manifest_created: false
runtime_metadata_created: false
dependency_files_modified: false
task1_manifest_load: not_run_no_manifest
task2_artifact_validation: not_run_no_eligible_candidate
task3_runtime_preflight: not_run_no_eligible_candidate
actual_adapter_load: not_run_fail_closed
runtime_adapter_loading: unavailable_without_approved_artifact
gpu_adapter_smoke: not_started
provider_chat_sse_smoke: not_started
browser_adapter_e2e: not_started
```

[확정] GPU load 전 gate가 후보 선정 단계에서 닫혔다. 따라서 CUDA·free VRAM을 성공 preflight로 기록하지 않았고,
VRAM·load duration·generation·unload 수치도 생성하지 않았다. 확인된 local Base revision 디렉터리의 제한 inventory만으로는
Task 3 Base snapshot 전체 계약을 충족한다고 판정할 수 없으며, 부적격 후보를 이유로 추가 탐색하거나 보완하지 않았다.

## 6. 라이선스와 공개 경계

- AIHUB-71748은 학생·비상업 로컬 연구 범위만 승인돼 있다.
- SFT 목적의 취득·이용조건 증빙과 weight publication은 여전히 별도 검증·승인 대상이다.
- 이번 작업은 보존 artifact의 metadata·checksum·평가 판정만 읽었고 Dataset 원문이나 실제 사용자 데이터를 읽지 않았다.
- Adapter·Base weight, Dataset, evaluation artifact를 수정·복사·공개하지 않았다.

## 7. 후속 recovery 조건

1. 기존 v0.1/v0.2를 deployment-ready로 재해석하지 않는다.
2. 새 학습을 검토한다면 별도 승인된 계보에서 hard blocker를 통과하는 canonical 평가 결과를 먼저 만든다.
3. v0.3는 기존 Run ID를 재사용하지 않고 Tokenization publish 원인 검토와 새 실행 승인을 선행한다.
4. SFT 이용조건 증빙과 로컬 derivative 사용 범위를 확정한다.
5. 적격 후보가 생긴 뒤에만 Chat Template hash, canonical runtime metadata, generation config와 manifest를 생성한다.
6. 그 manifest로 Task 1~3 preflight를 통과한 뒤 독립 GPU smoke를 정확히 한 번 실행한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-05 | v0.1~v0.3 보존 artifact·평가·checksum·dependency를 대조하고 `no_eligible_candidate`로 fail-closed 판정 |
