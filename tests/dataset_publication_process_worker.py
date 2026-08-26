"""Subprocess worker for Dataset publication process-boundary tests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType


def _fixtures() -> ModuleType:
    fixture_path = Path(__file__).with_name("test_dataset_publication.py")
    spec = importlib.util.spec_from_file_location(
        "_dataset_publication_process_fixtures", fixture_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("publication fixture module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wait_for(path: Path) -> None:
    while not path.exists():
        time.sleep(0.01)


def _pause_at_publish(stage: str, marker: Path) -> None:
    import src.data.dataset_publication as publication

    original_publish = publication.AtomicArtifactDirectory.publish

    def publish(transaction) -> None:
        if stage == "after-rename":
            original_publish(transaction)
        marker.write_text(stage, encoding="utf-8")
        while True:
            time.sleep(0.05)

    publication.AtomicArtifactDirectory.publish = publish


def _inject_cleanup_failure(marker: Path) -> None:
    import src.data.dataset_publication as publication
    from src.data import artifacts
    from src.data.errors import DataIssue, DataPipelineError

    def fail_publish(_transaction) -> None:
        raise DataPipelineError(
            DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "synthetic")
        )

    def fail_cleanup(_path) -> None:
        marker.write_text("cleanup-failed", encoding="utf-8")
        raise OSError("synthetic cleanup failure")

    publication.AtomicArtifactDirectory.publish = fail_publish
    artifacts.shutil.rmtree = fail_cleanup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--start-gate", type=Path)
    parser.add_argument("--marker", type=Path)
    parser.add_argument(
        "--mode",
        choices=(
            "publish",
            "read",
            "before-rename",
            "after-rename",
            "cleanup-failure",
        ),
        default="publish",
    )
    parser.add_argument("--variant", default="identical")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    fixtures = _fixtures()

    if args.start_gate is not None:
        _wait_for(args.start_gate)
    if args.mode in {"before-rename", "after-rename"}:
        if args.marker is None:
            raise RuntimeError("pause marker is required")
        _pause_at_publish(args.mode, args.marker)
    elif args.mode == "cleanup-failure":
        if args.marker is None:
            raise RuntimeError("cleanup marker is required")
        _inject_cleanup_failure(args.marker)

    try:
        if args.mode == "read":
            from src.data.dataset_publication import (
                FilesystemDatasetPublicationAuthority,
            )

            record = FilesystemDatasetPublicationAuthority(
                args.root
            ).read_authoritative_publication(fixtures.approved_version().identity)
            outcome = {
                "outcome": "success",
                "dataset_version": record.dataset_version,
                "dataset_manifest": record.dataset_manifest,
                "pair_fingerprint": record.pair_fingerprint,
            }
        else:
            metadata = fixtures.metadata()
            if args.variant != "identical":
                metadata = fixtures.metadata(source={"alias": args.variant})
            publication = fixtures.publish(args.root, metadata=metadata)
            outcome = {
                "outcome": "success",
                "published": publication.published,
                "storage_key": publication.storage_key,
                "pair_fingerprint": publication.pair_fingerprint,
            }
    except fixtures.DatasetPublicationError as exc:
        outcome = {"outcome": "error", "code": exc.code, "stage": exc.stage}
    except Exception as exc:  # noqa: BLE001 - sanitize test worker failures
        outcome = {"outcome": "unexpected-error", "type": type(exc).__name__}
    args.result.write_text(
        json.dumps(outcome, ensure_ascii=True, sort_keys=True), encoding="utf-8"
    )
    return 0 if outcome["outcome"] != "unexpected-error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
