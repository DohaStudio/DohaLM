"""Run the approved DohaLM v0.2 evaluation-only recovery exactly once."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.evaluation.qlora_sft import environment_snapshot
from src.training.v02_qlora_recovery import RECOVERY_ID, recover_dohalm_v02_training_evaluation
from src.training.v02_qlora_training import load_weighted_context, validate_config


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--approved-recovery-id", required=True)
    value.add_argument("--evaluation-governance-head", required=True)
    value.add_argument("--repository", type=Path, default=Path.cwd())
    value.add_argument("--failed-training-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--config", type=Path, default=Path("configs/training/dohalm-v0.2-qlora.yaml"))
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--sidecar-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    return value


def run(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.approved_recovery_id != RECOVERY_ID:
        raise RuntimeError("RECOVERY_ID_NOT_APPROVED")
    validate_config(arguments.config)
    context = load_weighted_context(arguments.tokenized_root, arguments.sidecar_root)
    environment = environment_snapshot()
    environment["execution_command"] = [sys.executable, *sys.argv]
    environment["mode"] = "evaluation_only"
    environment["training_calls"] = 0
    return recover_dohalm_v02_training_evaluation(
        failed_root=arguments.failed_training_root,
        output_root=arguments.output_root,
        config_path=arguments.config,
        cache_root=arguments.model_cache_root,
        context=context,
        sidecar_root=arguments.sidecar_root,
        repository=arguments.repository,
        evaluation_governance_head=arguments.evaluation_governance_head,
        environment=environment,
    )


def main() -> int:
    try:
        result = run(parser().parse_args())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({
        "status": result["status"],
        "recovery_id": result["recovery_id"],
        "artifact": result["artifact"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
