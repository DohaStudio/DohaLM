from __future__ import annotations

import json
import os
import shutil
import signal
import sys
from pathlib import Path

import pytest

from src.training import v03_tokenization
from src.training.v03_tokenization import V03TokenizationError, _publish_package_files
from src.training.v03_tokenization_runtime import (
    RUN_ID,
    TokenizationStageTracker,
    V03RuntimeError,
    cleanup_worker_state,
    inspect_run_identity,
    output_paths,
    publish_failure_artifact,
    publish_failure_artifact_bounded,
    read_stage_state,
    supervise_worker,
    validate_failure_artifact,
)


def _row() -> dict[str, list[int]]:
    return {"input_ids": [1, 151645], "attention_mask": [1, 1], "labels": [-100, 151645]}


def _publish(root: Path, injection: str | None = None) -> dict[str, str]:
    return _publish_package_files(
        output_root=root,
        train_rows=[_row()],
        validation_rows=[_row()],
        row_alignment={"valid": True},
        lineage_alignment={"valid": True},
        manifest={"schema_version": 1},
        statistics_value={"rows": 2},
        sampler_readiness={"training_allowed": False},
        callback=None,
        failure_injection=injection,
    )


def test_stage_state_is_atomic_and_non_sensitive(tmp_path: Path) -> None:
    tracker = TokenizationStageTracker(tmp_path / "stage-state.json")
    tracker.update("short_tokenization_started", records_seen=128, records_completed=128)
    state = read_stage_state(tracker.path)
    assert state["records_completed"] == 128
    assert not list(tmp_path.glob("*.tmp"))
    assert "input_ids" not in json.dumps(state)


def test_identity_consumes_known_previous_publish_attempt(tmp_path: Path) -> None:
    output = tmp_path / RUN_ID
    assert inspect_run_identity(output)["identity_reusable"] is True
    result = inspect_run_identity(output, previous_publish_attempt_recorded=True)
    assert result["previous_publish_attempt_recorded"] is True
    assert result["identity_reusable"] is False


@pytest.mark.parametrize(
    ("injection", "code"),
    [
        ("artifact_write", "TOKENIZATION_ARTIFACT_WRITE_FAILED"),
        ("file_fsync", "TOKENIZATION_FILE_FSYNC_FAILED"),
        ("checksum", "TOKENIZATION_CHECKSUM_FAILED"),
        ("staging_reload", "TOKENIZATION_STAGING_RELOAD_FAILED"),
        ("atomic_publish", "TOKENIZATION_ATOMIC_PUBLISH_FAILED"),
        ("directory_fsync", "TOKENIZATION_DIRECTORY_FSYNC_FAILED"),
        ("final_reload", "TOKENIZATION_FINAL_RELOAD_FAILED"),
        ("final_checksum", "TOKENIZATION_FINAL_CHECKSUM_FAILED"),
        ("staging_cleanup", "TOKENIZATION_STAGING_CLEANUP_FAILED"),
    ],
)
def test_publish_failure_injection_creates_valid_terminal_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    injection: str,
    code: str,
) -> None:
    monkeypatch.setitem(v03_tokenization.ROWS, "train", 1)
    monkeypatch.setitem(v03_tokenization.ROWS, "validation", 1)
    final = tmp_path / RUN_ID
    with pytest.raises(V03TokenizationError, match=f"^{code}$"):
        _publish(final, injection)
    paths = output_paths(final)
    paths["worker"].mkdir()
    tracker = TokenizationStageTracker(paths["worker"] / "stage-state.json")
    tracker.update("publish_" + injection, records_seen=2, records_completed=2)
    if final.exists():
        os.replace(final, paths["worker"] / "unverified-final")
    hidden = list(tmp_path.glob(f".{RUN_ID}.staging-*"))
    inventory = [*hidden]
    quarantine = paths["worker"] / "unverified-final"
    if quarantine.exists():
        inventory.append(quarantine)
    publish_failure_artifact(
        final,
        state=read_stage_state(tracker.path),
        failure_code=code,
        failure_stage="publish_" + injection,
        exception_type="InjectedFailure",
        exception_message=code,
        worker_exit_code=2,
        inventory_roots=inventory,
    )
    for item in hidden:
        shutil.rmtree(item)
    cleanup_worker_state(final)
    assert validate_failure_artifact(paths["failed"])["failure_code"] == code
    assert not final.exists()
    assert not list(tmp_path.glob(f".{RUN_ID}.staging-*"))


def test_synthetic_success_is_reloadable_and_no_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(v03_tokenization.ROWS, "train", 1)
    monkeypatch.setitem(v03_tokenization.ROWS, "validation", 1)
    final = tmp_path / RUN_ID
    checksums = _publish(final)
    assert checksums
    assert final.is_dir()
    assert not output_paths(final)["failed"].exists()
    assert not list(tmp_path.glob(f".{RUN_ID}.staging-*"))
    with pytest.raises(V03TokenizationError, match="TOKENIZATION_FINAL_COLLISION"):
        _publish(final)


@pytest.mark.parametrize("exit_code", [1, 124])
def test_supervisor_observes_worker_exit(tmp_path: Path, exit_code: int) -> None:
    final = tmp_path / RUN_ID
    code, _, _ = supervise_worker(
        [sys.executable, "-c", f"raise SystemExit({exit_code})"], final=final,
    )
    assert code == exit_code
    cleanup_worker_state(final)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal contract")
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL])
def test_supervisor_observes_worker_signal(tmp_path: Path, sig: signal.Signals) -> None:
    final = tmp_path / RUN_ID
    code, _, _ = supervise_worker(
        [sys.executable, "-c", f"import os,signal; os.kill(os.getpid(), {int(sig)})"],
        final=final,
    )
    assert code < 0
    cleanup_worker_state(final)


def test_supervisor_enforces_heartbeat_timeout(tmp_path: Path) -> None:
    final = tmp_path / RUN_ID
    code, failure, stage = supervise_worker(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        final=final,
        heartbeat_timeout=0.05,
        poll_seconds=0.01,
    )
    assert code != 0
    assert failure == "TOKENIZATION_HEARTBEAT_TIMEOUT"
    assert stage == "preflight"
    cleanup_worker_state(final)


def test_supervisor_enforces_publish_timeout(tmp_path: Path) -> None:
    final = tmp_path / RUN_ID
    state_path = output_paths(final)["worker"] / "stage-state.json"
    command = [
        sys.executable,
        "-c",
        (
            "import time; "
            "from pathlib import Path; "
            "from src.training.v03_tokenization_runtime import TokenizationStageTracker; "
            f"t=TokenizationStageTracker(Path({str(state_path)!r})); "
            "t.update('publish_started'); time.sleep(10)"
        ),
    ]
    code, failure, stage = supervise_worker(
        command,
        final=final,
        heartbeat_timeout=10,
        publish_timeout=0.05,
        poll_seconds=0.01,
    )
    assert code != 0
    assert failure == "TOKENIZATION_PUBLISH_TIMEOUT"
    assert stage == "publish_started"
    cleanup_worker_state(final)


def test_supervisor_does_not_depend_on_stdout_pipe(tmp_path: Path) -> None:
    final = tmp_path / RUN_ID
    command = [sys.executable, "-c", "import os; os.close(1); raise SystemExit(1)"]
    code, _, _ = supervise_worker(command, final=final)
    assert code == 1
    cleanup_worker_state(final)


def test_failure_artifact_publish_failure_writes_emergency_record(tmp_path: Path) -> None:
    final = tmp_path / RUN_ID
    tracker = TokenizationStageTracker(tmp_path / "state.json")
    with pytest.raises(V03RuntimeError, match="TOKENIZATION_FAILURE_PUBLISH_FAILED"):
        publish_failure_artifact(
            final,
            state=tracker.value,
            failure_code="INJECTED",
            failure_stage="artifact_write",
            exception_type="InjectedFailure",
            exception_message="injected",
            worker_exit_code=2,
            injection="artifact_write",
        )
    assert output_paths(final)["emergency"].is_file()


def test_failure_artifact_publish_timeout_writes_emergency_record(tmp_path: Path) -> None:
    final = tmp_path / RUN_ID
    tracker = TokenizationStageTracker(tmp_path / "state.json")
    with pytest.raises(V03RuntimeError, match="TOKENIZATION_FAILURE_PUBLISH_TIMEOUT"):
        publish_failure_artifact_bounded(
            final,
            timeout_seconds=0.05,
            state=tracker.value,
            failure_code="INJECTED",
            failure_stage="artifact_write",
            exception_type="InjectedFailure",
            exception_message="injected",
            worker_exit_code=2,
            injection="timeout",
        )
    assert output_paths(final)["emergency"].is_file()
