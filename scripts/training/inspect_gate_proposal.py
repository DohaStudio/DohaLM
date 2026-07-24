"""Inspect a generated status proposal without changing Gate state."""

from __future__ import annotations

import argparse
import json

from src.data.checksums import checksum_value
from src.runtime.paths import resolve_repository_path
from src.training import TrainingError

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate status proposal의 계약을 검사합니다.")
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def inspect(path_value: str) -> dict[str, object]:
    path = resolve_repository_path(path_value)
    try:
        proposal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingError("GATE_PROPOSAL_INVALID", "status proposal을 읽을 수 없습니다.") from exc
    required = {
        "current_status", "proposed_status", "eligible", "evidence_fingerprint", "blocking_reasons",
        "user_approval_required", "approved_by", "approved_at",
    }
    if not isinstance(proposal, dict) or not required.issubset(proposal):
        raise TrainingError("GATE_PROPOSAL_INVALID", "status proposal 필수 field가 없습니다.")
    if proposal.get("user_approval_required") is not True or proposal.get("approved_by") is not None or proposal.get("approved_at") is not None:
        raise TrainingError("GATE_PROPOSAL_INVALID", "사용자 승인 전 approval metadata는 null이어야 합니다.")
    return {
        "status": "proposal_valid",
        "proposal_file_name": path.name,
        "eligible": proposal["eligible"],
        "evidence_fingerprint": proposal["evidence_fingerprint"],
        "proposal_fingerprint": checksum_value(proposal),
        "user_approval_required": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(inspect(args.proposal), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
