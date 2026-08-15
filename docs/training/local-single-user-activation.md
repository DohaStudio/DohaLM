# 로컬 단일 사용자 Training Activation

- 문서 상태: `review`
- 마지막 검토일: 2026-08-16
- 선행 계약: [C3 PostgreSQL composition](../architecture/c3-postgresql-training-composition.md),
  [ADR-021](../decisions/ADR-021-production-training-adapters-and-durable-journal.md)
- 범위: Windows 로컬 단일 사용자 PostgreSQL Activation과 non-training readiness

## 활성화 경계

[확정] 기본 provider는 계속 `disabled`다. `local_single_user`는 ignored local JSON에서 명시적으로 선택해야
하며 `127.0.0.1`과 TLS disable만 허용한다. 원격 `production`의 `verify-full` 계약은 바뀌지 않는다.
import와 configuration construction은 Docker, DB, Dataset, CUDA와 Training side effect가 0이다.

[확정] 로컬 configuration은 C3 composition을 구성할 권한만 제공한다. Training은 별도의 immutable run
package와 PostgreSQL decision/issuer/approver snapshot이 exact match할 때만 기존 Host에서 가능하다. readiness는
approval을 소비하거나 journal claim/transition 또는 backend 호출을 하지 않는다. 이번 구현 및 검증에서 실제
Training, Evaluation, checkpoint와 publication은 수행하지 않는다.

## 로컬 상태와 credential

[확정] tracked example은 `configs/local-training-activation.example.json`과
`configs/local-training-run-package.example.json`이다. 실제 파일은 각각
`configs/local-training-activation.json`, `configs/local-training-run-package.json`이며 Git ignored다.
Dataset root, output root, run package와 credential directory는 environment variable로만 연결한다.

Credential directory는 repository 밖에 두고 다음 네 파일을 서로 다른 값으로 만든다.

```text
migration_owner.password
producer.password
resolver.password
journal.password
```

PowerShell 예시에서 실제 값을 명령행 인자로 전달하지 않는다.

```powershell
$state = Join-Path $env:LOCALAPPDATA "DohaLM\local-training"
New-Item -ItemType Directory -Force $state | Out-Null
$env:DOHALM_LOCAL_CREDENTIAL_DIRECTORY = $state
$env:DOHALM_LOCAL_DATASET_ROOT = "<local-dataset-root>"
$env:DOHALM_LOCAL_OUTPUT_ROOT = "<local-output-root>"
$env:DOHALM_LOCAL_RUN_PACKAGE = "<approved-run-package-json>"
```

[확정] raw password, DSN과 Dataset absolute path는 configuration, log, exception, `repr`과 PR에 기록하지
않는다. credential rotation 후 새 process가 새 composition/factory를 구성하며, shutdown된 기존 Host와 factory는
C3 revocable lease 때문에 재사용할 수 없다.

## Durable PostgreSQL

[확정] bootstrap은 기존 exact PostgreSQL 16.15 Alpine digest와 immutable `0001 → 0002 → 0003`을
재사용한다. 별도 labelled bridge network, persistent volume과 container를 만들며 `--internal`은 사용하지 않는다.
PostgreSQL 5432는 host `127.0.0.1`의 동적 port에만 publish한다. `docker port`, container inspect,
host listener와 loopback connect를 모두 확인하며 wildcard/LAN/IPv6 wildcard는 fail closed다.

[확정] migration owner만 advisory-lock migration을 적용하고 checksum/currentness를 검증한다. producer,
resolver와 journal password는 분리한다. resolver는 호출별 `REPEATABLE READ READ ONLY`, journal은 호출별
`READ COMMITTED` transaction을 유지한다. bootstrap은 current DB에 idempotent하며 drift, non-terminal run과
ambiguous mutation을 자동 reset/retry/resume하지 않는다.

`stop`은 container만 중지하고 volume을 보존한다. `destroy`는 exact correlation 확인을 요구하며 이
configuration label이 일치하는 container/volume/network만 삭제한다.

## Dataset와 authority/run package

[확정] DatasetVersion/Manifest identity는 local Dataset path와 분리한다. mapping은 root 아래 manifest,
train/evaluation split, tokenizer reference와 training config reference의 존재 및 expected manifest SHA-256을
검사한다. readiness는 Dataset sample이나 학습 loader를 호출하지 않고 파일을 수정·이동·삭제하지 않는다.

[확정] run package는 Host intent의 DatasetVersion/Manifest, pair/config/readiness fingerprint, run/output,
decision evidence를 한 번만 제공한다. process boundary, decision authority와 policy는 local immutable
configuration이 제공한다. runner와 adapter는 authority ID, fingerprint, approver 또는 approval time을 생성하지
않는다. package가 없으면 `NOT_APPROVED`, Dataset mapping이 없으면 `NOT_CONFIGURED`다. producer credential과
mapping boundary는 준비하지만 accepted authority/approval record 생성은 이번 범위 밖이다.

## 명령과 상태

```powershell
Copy-Item configs/local-training-activation.example.json configs/local-training-activation.json
python -m scripts.training.run_full_pretraining bootstrap --config configs/local-training-activation.json
python -m scripts.training.run_full_pretraining readiness --config configs/local-training-activation.json
python -m scripts.training.run_full_pretraining stop --config configs/local-training-activation.json
```

향후 exact run package와 별도 Training 승인이 존재할 때만 다음 형태를 사용한다.

```powershell
python -m scripts.training.run_full_pretraining execute --config configs/local-training-activation.json
```

`--execute` 문자열만으로는 실행할 수 없고 기존 legacy CLI도 approval 발급을 하지 않는다. 상태는 `READY`,
`NOT_CONFIGURED`, `NOT_APPROVED`, `ENVIRONMENT_ERROR`, `CONTRACT_ERROR`로 구분한다. 결과에는 raw path,
credential, DSN과 database exception을 포함하지 않는다.

명시적 data 삭제는 correlation ID를 다시 입력해야 한다.

```powershell
python -m scripts.training.run_full_pretraining destroy --config configs/local-training-activation.json --confirm-correlation-id <configured-correlation-id>
```

## Readiness 불변조건

- dependency import, configuration redaction, PostgreSQL migration/role connectivity를 확인한다.
- prerequisite/decision typed snapshot과 journal read만 수행한다.
- Dataset mapping/reference, CUDA/GPU/VRAM/FP16 metadata와 output root probe를 확인한다.
- output probe file은 즉시 삭제한다.
- model weight, optimizer, Dataset loader, one-batch Training을 만들지 않는다.
- journal/event mutation, approval consume, checkpoint/evaluation/publication은 0이다.
- 모든 성공·실패·interrupt 경로는 C3 shutdown으로 끝난다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-08-16 | [확정] 로컬 단일 사용자 Activation, durable PostgreSQL bootstrap, run package와 non-training readiness 구현 계약 기록 |
