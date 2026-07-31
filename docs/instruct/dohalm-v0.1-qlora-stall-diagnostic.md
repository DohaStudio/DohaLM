# DohaLM v0.1 QLoRA Backward Stall 진단

- 문서 상태: `review`
- 진단 ID: `DOHALM-V0.1-QLORA-STALL-DIAG-WSL-20260731-0001`
- 기준 HEAD: `b6c22afcfdacc81fb749db2470688f7273867770`
- 결론: `MEMORY_FRAGMENTATION_STALL`

## 범위와 안전 경계

실패한 Stability 0002는 terminal·non-reusable 상태로 보존했다. 진단은 동일 seed 42,
동일 Dataset·Tokenizer·Model revision·LoRA·loss masking·batch size·gradient
accumulation을 유지했다. 원문, token 배열, decode 결과는 기록하지 않았고 optimizer가
필요한 비교 경로 외에는 optimizer step을 수행하지 않았다. record 제외, 순서 변경,
watchdog 완화, 자동 retry는 수행하지 않았다.

## 문제 batch identity

| 항목 | 값 |
|---|---|
| deterministic dataset index | `9905` |
| sequence / padded length | `536` / `536` |
| valid label tokens | `494` |
| stable record hash | `b9937ec2c8135c4ae524dd7d6a71cb2b5cd1baf41c25b130f754fde50e7f024e` |
| sampler order fingerprint | `efd923d24796b40ee026e27b6030755cc6fa455ad50be0e00d7d4eb9e70c95db` |
| first 64 indices hash | `b93119476af6aba051fac6ada5d2b31042d05c307547661cb26adaf133db02e4` |

`input_ids`, `labels`, `attention_mask`는 SHA-256만 외부 진단 artifact에 기록했다.

## 재현 결과

| 환경 / 경로 | 반복 | 최대 backward | batch 29 | batch 42 | 최대 reserved VRAM |
|---|---:|---:|---:|---:|---:|
| bnb 0.48.2, batch 42 독립 | 3 | 0.494초 | - | 0.456~0.494초 | 3.66 GB |
| bnb 0.48.2, 1~42 no optimizer | 1 | 49.048초 | 49.048초 | 16.689초 | 8.13 GB |
| bnb 0.48.2, 1~42 accumulation | 1 | 49.564초 | 49.564초 | 18.084초 | 8.19 GB |
| bnb 0.46.1, batch 42 독립 | 3 | 0.505초 | - | 0.464~0.505초 | 3.66 GB |
| bnb 0.46.1, 1~42 accumulation | 1 | 58.228초 | 58.228초 | 28.181초 | 8.19 GB |
| bnb 0.48.2, post-batch cache release | 1 | 0.623초 | 0.623초 | 0.393초 | 4.50 GB |
| BF16 base + LoRA forward-only | 1 | forward 0.539초 | - | - | 6.11 GB |

독립 batch는 두 BitsAndBytes 버전에서 모두 정상이다. 반면 연속 경로는 optimizer 유무와
BitsAndBytes 버전에 관계없이 CUDA reserved memory가 물리 VRAM 한계에 접근한 뒤 급격히
느려졌다. 완료 backward 뒤 cached block만 회수한 비교군은 같은 순서와 optimizer 계약에서
reserved memory와 latency를 함께 낮췄다. 따라서 data·sequence·optimizer 단독 원인과 bnb
0.48.2 고유 회귀는 배제한다.

## Backend 결정

현재 조합 `PyTorch 2.7.1+cu118 / BitsAndBytes 0.48.2`를 유지한다. PyTorch는 2.7.1의
CUDA 11.8 wheel을 공식 제공하며, BitsAndBytes 0.48 계열은 PyTorch 2.3 이상과 CUDA
11.8 이상을 지원한다.

- [PyTorch previous versions](https://pytorch.org/get-started/previous-versions/)
- [BitsAndBytes 0.48.2 documentation](https://huggingface.co/docs/bitsandbytes/v0.48.2/en/index)
- [BitsAndBytes release history](https://github.com/bitsandbytes-foundation/bitsandbytes/releases)

BF16 forward-only allocation은 가능했지만 backward와 optimizer 안정성을 검증하지 않았으므로
실행 backend로 승인하지 않는다.

## 최소 수정

Stability manual loop와 Full Trainer microbatch에서 backward 및 CUDA synchronize가 완료된 뒤
`torch.cuda.empty_cache()`를 호출한다. 이 호출은 살아 있는 gradient·optimizer state를
삭제하지 않고 allocator의 사용하지 않는 cached block만 반환한다. Dataset, sampler order,
max sequence length, LoRA rank·target, batch size, accumulation, optimizer, watchdog는 변경하지
않는다. BitsAndBytes package lock도 변경하지 않는다.

## Failure artifact 계약

Supervisor는 worker SIGKILL, exit 124, 비정상 종료 또는 stage hard timeout 뒤 staging을 읽어
다음 정확한 파일 집합을 `<run_id>.failed`에 atomic no-replace로 확정한다.

```text
batch-metrics.jsonl
stage-state.json
environment.json
failure-result.yaml
checksums.sha256
```

상태는 `failed`이고 worker exit code, 마지막 stage, microbatch, optimizer step, memory,
non-identifying batch identity를 포함한다. checksum·reload·residue 검증이 끝나기 전에는 성공을
보고하지 않는다.

## 다음 실행 조건

Hotfix 병합 후 동일 merge HEAD에서 prerequisite 0004 네 개를 새로 생성한다. 모두 통과하고
identity가 일치할 때만 Stability 0003을 실행한다. Full 0003은 Stability 0003 통과와 72시간
이하 runtime estimate가 모두 확인된 경우에만 별도 조건부로 실행한다.
