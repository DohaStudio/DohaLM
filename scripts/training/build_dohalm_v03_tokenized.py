"""Validate or execute the single DohaLM v0.3 tokenization run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.training.sft_tokenization import SFTTokenizationError
from src.training.v03_tokenization import V03TokenizationError, build_package, validate_source
from src.training.v03_tokenization_runtime import (
    RUN_ID,
    TokenizationStageTracker,
    V03RuntimeError,
    cleanup_worker_state,
    output_paths,
    publish_failure_artifact_bounded,
    read_stage_state,
    supervise_worker,
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, text=True).stdout.strip()


def validate_git(repository: Path, expected_head: str) -> dict[str, object]:
    try:
        branch = _git(repository, "branch", "--show-current")
        head = _git(repository, "rev-parse", "HEAD")
        origin = _git(repository, "rev-parse", "origin/develop")
        status = _git(repository, "status", "--porcelain=v1")
    except (OSError, subprocess.CalledProcessError):
        raise V03TokenizationError("GIT_STATE_INVALID") from None
    if branch != "develop" or head != expected_head or origin != head or status:
        raise V03TokenizationError("GIT_STATE_INVALID")
    return {"branch": branch, "head": head, "origin_develop": origin, "clean": True}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--source-root", type=Path, required=True)
    value.add_argument("--reuse-root", type=Path, required=True)
    value.add_argument("--tokenizer-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    value.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    value.add_argument("--state-path", type=Path, help=argparse.SUPPRESS)
    value.add_argument("--failure-injection", help=argparse.SUPPRESS)
    return value


def _fallback_state() -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "worker_pid": 0,
        "stage": "preflight",
        "status": "running",
        "records_seen": 0,
        "records_completed": 0,
        "files_written": 0,
        "started_at": now,
        "updated_at": now,
    }


def _last_worker_error(path: Path) -> tuple[str, str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return "TOKENIZATION_WORKER_ABNORMAL_EXIT", "WorkerExit", "worker exited without result"
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("error"):
            return str(value["error"]), str(value.get("exception_type", "WorkerError")), str(value.get("exception_message", value["error"]))
    return "TOKENIZATION_WORKER_ABNORMAL_EXIT", "WorkerExit", "worker exited without structured result"


def _supervise(arguments: argparse.Namespace, raw: list[str]) -> int:
    final = arguments.output_root.resolve()
    paths = output_paths(final)
    state_path = paths["worker"] / "stage-state.json"
    command = [sys.executable, str(Path(__file__).resolve()), *raw, "--worker", "--state-path", str(state_path)]
    return_code, supervisor_code, supervisor_stage = supervise_worker(command, final=final)
    stdout_path = paths["worker"] / "stdout.log"
    if return_code == 0:
        output = stdout_path.read_text(encoding="utf-8") if stdout_path.is_file() else ""
        cleanup_worker_state(final)
        print(output, end="")
        return 0
    try:
        state = read_stage_state(state_path)
    except V03RuntimeError:
        state = _fallback_state()
    code, exception_type, message = _last_worker_error(stdout_path)
    if supervisor_code:
        code, exception_type, message = supervisor_code, "SupervisorTimeout", supervisor_code
    final_created = paths["final"].exists()
    if final_created:
        quarantine = paths["worker"] / "unverified-final"
        os.replace(paths["final"], quarantine)
    hidden = sorted(final.parent.glob(f".{final.name}.staging-*"))
    inventory_roots = [*hidden]
    quarantine = paths["worker"] / "unverified-final"
    if quarantine.exists():
        inventory_roots.append(quarantine)
    failure = publish_failure_artifact_bounded(
        final,
        state=state,
        failure_code=code,
        failure_stage=supervisor_stage or str(state.get("stage", "worker_exit")),
        exception_type=exception_type,
        exception_message=message,
        worker_exit_code=return_code,
        final_created=final_created,
        inventory_roots=inventory_roots,
    )
    for root in hidden:
        if root.exists():
            shutil.rmtree(root)
    cleanup_worker_state(final)
    print(json.dumps({"status": "failed_closed", "failure": failure, "failure_artifact_validated": True, "training_started": False, "optimizer_steps": 0}, sort_keys=True))
    return 2


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(raw)
    if args.execute and not args.worker:
        return _supervise(args, raw)
    tracker = TokenizationStageTracker(args.state_path) if args.worker and args.state_path else None
    try:
        git = validate_git(args.repository.resolve(), args.expected_head)
        if not args.source_root.resolve().is_dir() or not args.reuse_root.resolve().is_dir() or not args.tokenizer_root.resolve().is_dir() or not args.output_root.resolve().is_absolute():
            raise V03TokenizationError("PATH_INVALID")
        validate_source(args.source_root.resolve())
        result = ({"status": "validated_not_executed"} if not args.execute else build_package(source_root=args.source_root.resolve(), reuse_root=args.reuse_root.resolve(), tokenizer_root=args.tokenizer_root.resolve(), output_root=args.output_root.resolve(), git_head=str(git["head"]), stage_callback=(tracker.update if tracker else None), failure_injection=args.failure_injection))
        result = {**result, "git": git, "training_started": False, "optimizer_steps": 0}
        if tracker:
            tracker.update("publish_completed", status="completed", records_seen=18926, records_completed=18926)
    except (V03TokenizationError, V03RuntimeError, SFTTokenizationError, OSError, ValueError) as exc:
        if tracker:
            tracker.update(str(tracker.value.get("stage", "failed")), status="failed")
        print(json.dumps({"status": "failed_closed", "error": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:512], "training_started": False, "optimizer_steps": 0}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
