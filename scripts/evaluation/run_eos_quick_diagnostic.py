"""Execute the approved read-only EOS and Quick/Full diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.evaluation.artifacts import ArtifactRegistry
from src.evaluation.config import EvaluationConfig
from src.evaluation.diagnostics import run_diagnostic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/evaluation.example.yaml")
    parser.add_argument("--diagnostic-id", required=True)
    parser.add_argument("--artifact-id", default="candidate-a-final")
    parser.add_argument(
        "--quick-reference",
        default="candidate-a-final:initial-pilot-candidate-a-quick-20260727-01",
    )
    parser.add_argument(
        "--full-reference",
        default="candidate-a-final:candidate-a-final-full-20260727-01",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("explicit --execute is required")
    config = EvaluationConfig.from_yaml(Path(args.config), profile="full")
    registry = ArtifactRegistry.load(config.repository_path(config.artifact_registry))
    print(json.dumps(run_diagnostic(
        config,
        registry,
        diagnostic_id=args.diagnostic_id,
        artifact_id=args.artifact_id,
        quick_reference=args.quick_reference,
        full_reference=args.full_reference,
    ), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
