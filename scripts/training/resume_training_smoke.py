"""Resume a bounded synthetic training smoke from an atomic checkpoint."""

from __future__ import annotations

import argparse

from src.model import ModelConfig
from src.runtime.paths import resolve_repository_path
from src.training import CheckpointManager, TrainingError

from ._common import build_trainer, cli_error, config_from_document, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="합성 Trainer checkpoint를 복원해 지정 step까지 계속합니다.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--steps", required=True, type=int, help="도달할 전체 optimizer step")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        checkpoint = resolve_repository_path(args.checkpoint)
        metadata_document = CheckpointManager.metadata(checkpoint)
        model_config = ModelConfig(**metadata_document["model"])
        training_config = config_from_document(metadata_document["training"])
        dataset_value = metadata_document.get("synthetic_dataset")
        if not isinstance(dataset_value, dict) or not dataset_value:
            raise TrainingError("RESUME_STATE_MISMATCH", "synthetic dataset metadata가 없습니다.")
        trainer, _ = build_trainer(
            model_config=model_config,
            training_config=training_config,
            metadata=dataset_value,
            output_root=checkpoint.parent,
            resume=True,
        )
        resumed_from = trainer.resume_from(checkpoint).global_step
        result = trainer.train(target_steps=args.steps)
        print_result(
            {
                "status": "resume_smoke_complete",
                "resumed_from_step": resumed_from,
                "target_step": args.steps,
                "synthetic_only": True,
                **result.to_dict(),
            },
            json_output=args.json,
        )
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
