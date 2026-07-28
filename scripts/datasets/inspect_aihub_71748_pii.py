"""Run the approved aggregate-only AIHUB-71748 SFT PII candidate scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.aihub_71748_pii import scan_aihub_71748_pii


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    args = parser.parse_args()
    result = scan_aihub_71748_pii(args.dataset_root)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"].startswith("completed_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
