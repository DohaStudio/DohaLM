"""Run the approved aggregate-only AIHUB-71748 SFT leakage scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import threading

from src.data.aihub_71748_leakage import scan_aihub_71748_leakage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--execution-id", required=True)
    args = parser.parse_args()
    cancelled = threading.Event()

    def request_cancellation(_signum, _frame) -> None:
        cancelled.set()

    signal.signal(signal.SIGINT, request_cancellation)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_cancellation)
    result = scan_aihub_71748_leakage(
        args.dataset_root,
        args.repository_root,
        execution_id=args.execution_id,
        cancelled=cancelled.is_set,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
