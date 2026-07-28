"""Run the approved, evaluation-only EOS generation diagnostic once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.evaluation.artifacts import ArtifactRegistry
from src.evaluation.config import EvaluationConfig
from src.evaluation.generation_diagnostics import GenerationDiagnosticConfig, run_generation_diagnostic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/eos-generation-diagnostic.example.yaml")
    parser.add_argument("--diagnostic-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("explicit --execute is required")
    diagnostic = GenerationDiagnosticConfig.from_yaml(Path(args.config))
    evaluation = EvaluationConfig.from_yaml(Path(diagnostic.evaluation_config), profile="full")
    registry = ArtifactRegistry.load(evaluation.repository_path(evaluation.artifact_registry))
    print(json.dumps(run_generation_diagnostic(
        diagnostic, evaluation, registry, diagnostic_id=args.diagnostic_id,
    ), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
