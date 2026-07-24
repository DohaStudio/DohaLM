"""Primitive-only pilot summary writing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_pilot_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
