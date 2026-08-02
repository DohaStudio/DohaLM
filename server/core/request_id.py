"""Opaque request ID generation and validation."""

from __future__ import annotations

import re
import uuid

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(r"^req_[A-Za-z0-9_-]{8,128}$")


def request_id(candidate: str | None) -> str:
    if candidate and _REQUEST_ID.fullmatch(candidate):
        return candidate
    return f"req_{uuid.uuid4().hex}"
