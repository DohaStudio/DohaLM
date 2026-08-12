from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.data.checksums import checksum_value

WORKER = Path(__file__).with_name("dataset_publication_process_worker.py")
VERSION_FILE = "dataset-version.json"
MANIFEST_FILE = "dataset-manifest.json"
PAIR_FILES = {VERSION_FILE, MANIFEST_FILE}


def _spawn(
    root: Path,
    result: Path,
    *,
    gate: Path | None = None,
    marker: Path | None = None,
    mode: str = "publish",
    variant: str = "identical",
) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        str(WORKER),
        "--root",
        str(root),
        "--result",
        str(result),
        "--mode",
        mode,
        "--variant",
        variant,
    ]
    if gate is not None:
        command.extend(("--start-gate", str(gate)))
    if marker is not None:
        command.extend(("--marker", str(marker)))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=WORKER.parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=flags,
    )


def _finish(process: subprocess.Popen[str], result: Path) -> dict:
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, (stdout, stderr)
    return json.loads(result.read_text(encoding="utf-8"))


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.kill()
        process.communicate(timeout=30)


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path.name}")


def _pair(root: Path, storage_key: str) -> tuple[Path, dict, dict, dict[str, bytes]]:
    target = root / storage_key
    assert {entry.name for entry in target.iterdir()} == PAIR_FILES
    raw = {name: (target / name).read_bytes() for name in PAIR_FILES}
    version = json.loads(raw[VERSION_FILE])
    manifest = json.loads(raw[MANIFEST_FILE])
    assert version["dataset_manifest_id"] == manifest["dataset_manifest_id"]
    assert version["object_id"] == manifest["source_dataset_version_id"]
    return target, version, manifest, raw


def _fingerprint(version: dict, manifest: dict) -> str:
    return checksum_value({"dataset_manifest": manifest, "dataset_version": version})


def test_two_process_identical_and_conflicting_races_preserve_one_complete_pair(
    tmp_path: Path,
) -> None:
    identical_root = tmp_path / "identical"
    identical_gate = tmp_path / "identical.start"
    identical_results = [tmp_path / f"identical-{index}.json" for index in range(2)]
    identical = [
        _spawn(identical_root, result, gate=identical_gate)
        for result in identical_results
    ]
    try:
        identical_gate.touch()
        identical_outcomes = [
            _finish(process, result)
            for process, result in zip(identical, identical_results, strict=True)
        ]
    finally:
        for process in identical:
            _stop(process)
    assert all(item["outcome"] == "success" for item in identical_outcomes)
    assert sorted(item["published"] for item in identical_outcomes) == [False, True]
    assert len({item["storage_key"] for item in identical_outcomes}) == 1
    storage_key = identical_outcomes[0]["storage_key"]
    _, version, manifest, original = _pair(identical_root, storage_key)
    assert _fingerprint(version, manifest) == identical_outcomes[0]["pair_fingerprint"]

    replay_result = tmp_path / "identical-restart.json"
    replay = _finish(_spawn(identical_root, replay_result), replay_result)
    assert replay["outcome"] == "success"
    assert replay["published"] is False
    assert _pair(identical_root, storage_key)[3] == original

    conflict_root = tmp_path / "conflict"
    conflict_gate = tmp_path / "conflict.start"
    conflict_results = [tmp_path / f"conflict-{index}.json" for index in range(2)]
    conflicting = [
        _spawn(conflict_root, conflict_results[0], gate=conflict_gate, variant="a"),
        _spawn(conflict_root, conflict_results[1], gate=conflict_gate, variant="b"),
    ]
    try:
        conflict_gate.touch()
        conflict_outcomes = [
            _finish(process, result)
            for process, result in zip(conflicting, conflict_results, strict=True)
        ]
    finally:
        for process in conflicting:
            _stop(process)
    assert sorted(item["outcome"] for item in conflict_outcomes) == ["error", "success"]
    loser = next(item for item in conflict_outcomes if item["outcome"] == "error")
    winner = next(item for item in conflict_outcomes if item["outcome"] == "success")
    assert (loser["code"], loser["stage"]) == (
        "PUBLICATION_CONFLICT",
        "verification",
    )
    target, version, manifest, winner_bytes = _pair(
        conflict_root, winner["storage_key"]
    )
    assert manifest["source"]["alias"] in {"a", "b"}
    assert _fingerprint(version, manifest) == winner["pair_fingerprint"]

    retry_result = tmp_path / "conflicting-restart.json"
    other = "b" if manifest["source"]["alias"] == "a" else "a"
    retry = _finish(_spawn(conflict_root, retry_result, variant=other), retry_result)
    assert retry == {
        "outcome": "error",
        "code": "PUBLICATION_CONFLICT",
        "stage": "verification",
    }
    assert {entry.name for entry in target.iterdir()} == PAIR_FILES
    assert _pair(conflict_root, winner["storage_key"])[3] == winner_bytes


def test_process_termination_boundaries_and_orphan_staging_are_fail_closed(
    tmp_path: Path,
) -> None:
    before_root = tmp_path / "before"
    before_result = tmp_path / "before.json"
    before_marker = tmp_path / "before.marker"
    before = _spawn(
        before_root,
        before_result,
        mode="before-rename",
        marker=before_marker,
    )
    try:
        _wait_for(before_marker)
        before.terminate()
        before.communicate(timeout=30)
    finally:
        _stop(before)
    assert before.returncode != 0
    assert not before_result.exists()
    orphan = tuple(before_root.glob(".*.staging-*"))
    assert len(orphan) == 1
    assert {entry.name for entry in orphan[0].iterdir()} == PAIR_FILES
    assert not tuple(
        path for path in before_root.iterdir() if not path.name.startswith(".")
    )

    restart_result = tmp_path / "before-restart.json"
    restart = _finish(_spawn(before_root, restart_result), restart_result)
    assert restart["outcome"] == "success"
    assert restart["published"] is True
    _pair(before_root, restart["storage_key"])
    assert orphan[0].exists()

    after_root = tmp_path / "after"
    after_result = tmp_path / "after.json"
    after_marker = tmp_path / "after.marker"
    after = _spawn(
        after_root,
        after_result,
        mode="after-rename",
        marker=after_marker,
    )
    try:
        _wait_for(after_marker)
        after.terminate()
        after.communicate(timeout=30)
    finally:
        _stop(after)
    assert after.returncode != 0
    assert not after_result.exists()
    finals = tuple(
        path for path in after_root.iterdir() if not path.name.startswith(".")
    )
    assert len(finals) == 1
    _, _, _, committed = _pair(after_root, finals[0].name)

    replay_result = tmp_path / "after-restart.json"
    replay = _finish(_spawn(after_root, replay_result), replay_result)
    assert replay["outcome"] == "success"
    assert replay["published"] is False
    assert _pair(after_root, replay["storage_key"])[3] == committed


def test_cleanup_failure_never_reports_success_or_publishes_final(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cleanup"
    result = tmp_path / "cleanup.json"
    marker = tmp_path / "cleanup.marker"
    process = _spawn(root, result, mode="cleanup-failure", marker=marker)
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, (stdout, stderr)
    assert json.loads(result.read_text(encoding="utf-8")) == {
        "outcome": "error",
        "code": "PUBLICATION_IO_FAILED",
        "stage": "persistence",
    }
    assert marker.read_text(encoding="utf-8") == "cleanup-failed"
    assert len(tuple(root.glob(".*.staging-*"))) == 1
    assert not tuple(path for path in root.iterdir() if not path.name.startswith("."))


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "PUBLICATION_CORRUPT"),
        ("extra", "PUBLICATION_CORRUPT"),
        ("noncanonical", "PUBLICATION_CORRUPT"),
        ("checksum", "PUBLICATION_CONFLICT"),
    ),
)
def test_restart_rejects_corrupt_final_without_repair_or_overwrite(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    root = tmp_path / mutation
    initial_result = tmp_path / f"{mutation}-initial.json"
    initial = _finish(_spawn(root, initial_result), initial_result)
    target, _, manifest, _ = _pair(root, initial["storage_key"])

    if mutation == "missing":
        (target / MANIFEST_FILE).unlink()
    elif mutation == "extra":
        (target / "extra.json").write_text("{}", encoding="utf-8")
    elif mutation == "noncanonical":
        (target / MANIFEST_FILE).write_bytes(b'{ "noncanonical": true }\n')
    else:
        manifest["manifest_checksum"] = "sha256:" + "0" * 64
        (target / MANIFEST_FILE).write_bytes(
            (
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
    before = {
        entry.name: entry.read_bytes() for entry in target.iterdir() if entry.is_file()
    }

    retry_result = tmp_path / f"{mutation}-retry.json"
    retry = _finish(_spawn(root, retry_result), retry_result)
    assert retry == {
        "outcome": "error",
        "code": expected_code,
        "stage": "verification",
    }
    after = {
        entry.name: entry.read_bytes() for entry in target.iterdir() if entry.is_file()
    }
    assert after == before
    assert (
        len(tuple(path for path in root.iterdir() if not path.name.startswith(".")))
        == 1
    )
