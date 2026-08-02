"""Observable worker lifecycle and terminal failure artifacts for v0.3 tokenization."""

from __future__ import annotations

import json
import multiprocessing
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.data.artifacts import AtomicArtifactDirectory, _fsync_directory, write_json, write_yaml
from src.data.checksums import file_checksum


RUN_ID = "DOHALM-V0.3-TOKENIZATION-20260802-0001"
HEARTBEAT_TIMEOUT_SECONDS = 600.0
PUBLISH_TIMEOUT_SECONDS = 300.0
FAILURE_PUBLISH_TIMEOUT_SECONDS = 300.0
FAILURE_FILES = frozenset({
    "artifact-inventory.json", "checksums.sha256", "environment.json",
    "failure-result.yaml", "stage-state.json",
})


class V03RuntimeError(RuntimeError):
    """Stable fail-closed runtime error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def output_paths(final: Path) -> dict[str, Path]:
    return {
        "final": final,
        "staging": final.with_name(final.name + ".staging"),
        "failed": final.with_name(final.name + ".failed"),
        "identity": final.with_name(final.name + ".identity.json"),
        "worker": final.with_name("." + final.name + ".worker"),
        "emergency": final.with_name("." + final.name + ".failure-emergency.json"),
    }


def inspect_run_identity(
    final: str | Path, *, previous_publish_attempt_recorded: bool = False
) -> dict[str, object]:
    destination = Path(final).resolve()
    paths = output_paths(destination)
    hidden = (
        sorted(destination.parent.glob(f".{destination.name}.staging-*"))
        if destination.parent.exists() else []
    )
    result = {
        "final_absent": not paths["final"].exists(),
        "staging_absent": not paths["staging"].exists(),
        "failed_absent": not paths["failed"].exists(),
        "hidden_staging_absent": not hidden,
        "identity_record_absent": not paths["identity"].exists(),
        "worker_state_absent": not paths["worker"].exists(),
        "emergency_record_absent": not paths["emergency"].exists(),
        "previous_publish_attempt_recorded": previous_publish_attempt_recorded,
        "hidden_staging_count": len(hidden),
    }
    result["identity_reusable"] = all(
        bool(result[name]) for name in (
            "final_absent", "staging_absent", "failed_absent",
            "hidden_staging_absent", "identity_record_absent",
            "worker_state_absent", "emergency_record_absent",
        )
    ) and not previous_publish_attempt_recorded
    return result


def _atomic_json_replace(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(dict(value), stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


class TokenizationStageTracker:
    """Atomically persist non-sensitive worker progress and heartbeat."""

    def __init__(self, path: Path, *, run_id: str = RUN_ID) -> None:
        self.path = path
        self.started_at = utc_now()
        self.value: dict[str, object] = {
            "schema_version": 1,
            "run_id": run_id,
            "worker_pid": os.getpid(),
            "stage": "preflight",
            "status": "running",
            "records_seen": 0,
            "records_completed": 0,
            "files_written": 0,
            "started_at": self.started_at,
            "updated_at": self.started_at,
        }
        _atomic_json_replace(self.path, self.value)

    def update(
        self,
        stage: str,
        *,
        status: str = "running",
        records_seen: int | None = None,
        records_completed: int | None = None,
        files_written: int | None = None,
    ) -> None:
        if status not in {"running", "completed", "failed"}:
            raise V03RuntimeError("TOKENIZATION_STAGE_STATE_INVALID")
        self.value.update({"stage": stage, "status": status, "updated_at": utc_now()})
        if records_seen is not None:
            self.value["records_seen"] = int(records_seen)
        if records_completed is not None:
            self.value["records_completed"] = int(records_completed)
        if files_written is not None:
            self.value["files_written"] = int(files_written)
        _atomic_json_replace(self.path, self.value)


def read_stage_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V03RuntimeError("TOKENIZATION_STAGE_STATE_INVALID") from None
    required = {
        "schema_version", "run_id", "worker_pid", "stage", "status",
        "records_seen", "records_completed", "files_written", "started_at", "updated_at",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("run_id") != RUN_ID:
        raise V03RuntimeError("TOKENIZATION_STAGE_STATE_INVALID")
    return value


def restricted_inventory(roots: Sequence[Path]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                values.append({
                    "root": root.name,
                    "relative_path": path.relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": file_checksum(path).removeprefix("sha256:"),
                })
    return values


def _environment() -> dict[str, object]:
    return {
        "schema_version": 1,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "model_weight_loaded": False,
        "training_started": False,
        "optimizer_steps": 0,
    }


def _safe_exception_message(value: str, exception_type: str) -> str:
    message = value.strip()
    if re.fullmatch(r"[A-Z0-9_ .:-]{1,128}", message):
        return message
    return exception_type


def _write_failure_checksums(root: Path) -> dict[str, str]:
    names = sorted(FAILURE_FILES - {"checksums.sha256"})
    checksums = {name: file_checksum(root / name).removeprefix("sha256:") for name in names}
    with (root / "checksums.sha256").open("x", encoding="ascii", newline="\n") as stream:
        for name, digest in checksums.items():
            stream.write(f"{digest}  {name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return checksums


def validate_failure_artifact(root: str | Path) -> dict[str, object]:
    base = Path(root)
    if not base.is_dir() or {item.name for item in base.iterdir()} != FAILURE_FILES:
        raise V03RuntimeError("TOKENIZATION_FAILURE_FILE_SET_INVALID")
    try:
        state = json.loads((base / "stage-state.json").read_text(encoding="utf-8"))
        failure = yaml.safe_load((base / "failure-result.yaml").read_text(encoding="utf-8"))
        environment = json.loads((base / "environment.json").read_text(encoding="utf-8"))
        inventory = json.loads((base / "artifact-inventory.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        raise V03RuntimeError("TOKENIZATION_FAILURE_INVALID") from None
    if (
        not isinstance(state, Mapping) or not isinstance(failure, Mapping)
        or not isinstance(environment, Mapping) or not isinstance(inventory, Mapping)
        or state.get("status") != "failed" or failure.get("status") != "failed"
        or state.get("run_id") != RUN_ID or failure.get("run_id") != RUN_ID
    ):
        raise V03RuntimeError("TOKENIZATION_FAILURE_INVALID")
    expected = {}
    for line in (base / "checksums.sha256").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
    actual = {
        name: file_checksum(base / name).removeprefix("sha256:")
        for name in FAILURE_FILES - {"checksums.sha256"}
    }
    if expected != actual:
        raise V03RuntimeError("TOKENIZATION_FAILURE_CHECKSUM_INVALID")
    return dict(failure)


def publish_failure_artifact(
    final: Path,
    *,
    state: Mapping[str, object],
    failure_code: str,
    failure_stage: str,
    exception_type: str,
    exception_message: str,
    worker_exit_code: int,
    final_created: bool = False,
    inventory_roots: Sequence[Path] = (),
    injection: str | None = None,
) -> dict[str, object]:
    paths = output_paths(final)
    if paths["final"].exists() or paths["failed"].exists():
        raise V03RuntimeError("TOKENIZATION_FAILURE_COLLISION")
    failed_at = utc_now()
    failed_state = dict(state)
    failed_state.update({"stage": "failed", "status": "failed", "updated_at": failed_at})
    completed = int(state.get("records_completed", 0))
    stage = str(state.get("stage", ""))
    failure = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "status": "failed",
        "failure_code": failure_code,
        "failure_stage": failure_stage,
        "exception_type": exception_type,
        "exception_message": _safe_exception_message(exception_message, exception_type),
        "records_seen": int(state.get("records_seen", 0)),
        "records_completed": completed,
        "original_rows_reused": min(completed, 10374),
        "short_rows_tokenized": min(max(completed - 10374, 0), 7265),
        "validation_rows_prepared": min(max(completed - 17639, 0), 1287),
        "staging_created": any(".staging-" in root.name for root in inventory_roots),
        "publish_started": stage.startswith("publish_") or stage in {
            "artifact_files_written", "checksums_created",
        },
        "final_created": bool(final_created),
        "worker_pid": int(state.get("worker_pid", 0)),
        "worker_exit_code": int(worker_exit_code),
        "occurred_at": failed_at,
        "failed_at": failed_at,
    }
    try:
        atomic = AtomicArtifactDirectory(paths["failed"])
        with atomic as staging:
            if injection == "timeout":
                time.sleep(60)
            if injection == "artifact_write":
                raise OSError("injected artifact write failure")
            write_json(staging / "stage-state.json", failed_state)
            write_yaml(staging / "failure-result.yaml", failure)
            write_json(staging / "environment.json", _environment())
            write_json(staging / "artifact-inventory.json", {
                "schema_version": 1,
                "artifacts": restricted_inventory(inventory_roots),
            })
            _write_failure_checksums(staging)
            validate_failure_artifact(staging)
            atomic.publish()
        result = validate_failure_artifact(paths["failed"])
        if paths["final"].exists():
            raise V03RuntimeError("TOKENIZATION_FAILURE_FINAL_PRESENT")
        return result
    except Exception as exc:
        emergency = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "status": "failure_artifact_publish_failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:512],
            "failed_at": utc_now(),
        }
        if not paths["emergency"].exists():
            _atomic_json_replace(paths["emergency"], emergency)
        raise V03RuntimeError("TOKENIZATION_FAILURE_PUBLISH_FAILED") from exc


def _failure_publish_target(
    queue: multiprocessing.Queue,
    final: Path,
    values: dict[str, object],
) -> None:
    try:
        result = publish_failure_artifact(final, **values)
        queue.put({"result": result})
    except Exception as exc:
        queue.put({"error": str(exc), "error_type": type(exc).__name__})


def publish_failure_artifact_bounded(
    final: Path,
    *,
    timeout_seconds: float = FAILURE_PUBLISH_TIMEOUT_SECONDS,
    **values: object,
) -> dict[str, object]:
    """Publish terminal failure evidence in a killable, bounded process."""
    context = multiprocessing.get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_failure_publish_target,
        args=(queue, final, dict(values)),
        daemon=False,
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(10)
        emergency = output_paths(final)["emergency"]
        if not emergency.exists():
            _atomic_json_replace(emergency, {
                "schema_version": 1,
                "run_id": RUN_ID,
                "status": "failure_artifact_publish_timeout",
                "error_type": "SupervisorTimeout",
                "error_message": "TOKENIZATION_FAILURE_PUBLISH_TIMEOUT",
                "failed_at": utc_now(),
            })
        raise V03RuntimeError("TOKENIZATION_FAILURE_PUBLISH_TIMEOUT")
    try:
        message = queue.get(timeout=1)
    except Exception:
        raise V03RuntimeError("TOKENIZATION_FAILURE_PUBLISH_FAILED") from None
    if "error" in message:
        raise V03RuntimeError(str(message["error"]))
    return dict(message["result"])


def cleanup_worker_state(final: Path) -> None:
    worker = output_paths(final)["worker"]
    if worker.exists():
        shutil.rmtree(worker)
        _fsync_directory(worker.parent)


def supervise_worker(
    command: Sequence[str],
    *,
    final: Path,
    heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
    publish_timeout: float = PUBLISH_TIMEOUT_SECONDS,
    poll_seconds: float = 0.1,
) -> tuple[int, str, str]:
    paths = output_paths(final)
    if paths["worker"].exists():
        raise V03RuntimeError("TOKENIZATION_WORKER_STATE_COLLISION")
    paths["worker"].mkdir(parents=True)
    state_path = paths["worker"] / "stage-state.json"
    stdout_path = paths["worker"] / "stdout.log"
    stderr_path = paths["worker"] / "stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(list(command), stdout=stdout, stderr=stderr, text=True)
        last_update = time.monotonic()
        last_timestamp = ""
        last_stage = "preflight"
        while process.poll() is None:
            if state_path.is_file():
                state = read_stage_state(state_path)
                last_stage = str(state["stage"])
                timestamp = str(state["updated_at"])
                if timestamp != last_timestamp:
                    last_timestamp = timestamp
                    last_update = time.monotonic()
                timeout = publish_timeout if str(state["stage"]).startswith("publish_") else heartbeat_timeout
            else:
                timeout = heartbeat_timeout
            if time.monotonic() - last_update > timeout:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=30)
                return int(process.returncode or -9), "TOKENIZATION_PUBLISH_TIMEOUT" if timeout == publish_timeout else "TOKENIZATION_HEARTBEAT_TIMEOUT", last_stage
            time.sleep(poll_seconds)
    return int(process.returncode or 0), "", ""


def worker_command(script: Path, arguments: Sequence[str], *, state_path: Path) -> list[str]:
    return [sys.executable, str(script), *arguments, "--worker", "--state-path", str(state_path)]
