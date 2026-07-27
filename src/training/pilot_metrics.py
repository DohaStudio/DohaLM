"""Primitive-only pilot summary writing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_pilot_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    staging = path.with_name(f".{path.name}.staging-{os.getpid()}")
    if path.exists() or staging.exists():
        raise FileExistsError(f"기존 Pilot artifact를 덮어쓸 수 없습니다: {path.name}")
    try:
        with staging.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)
