"""Run the approved AIHUB-71748 aggregate-only join-integrity inspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.aihub_71748_join import scan_aihub_71748_join


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    args = parser.parse_args()
    result = scan_aihub_71748_join(args.dataset_root)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
