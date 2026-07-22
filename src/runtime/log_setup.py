"""중복 핸들러와 민감 정보 노출을 막는 로깅 설정."""

from __future__ import annotations

import logging
import re
from pathlib import Path

_HANDLER_MARKER = "_dohalm_handler"
_PATTERNS = (
    re.compile(r"(?i)\b(password|api[_-]?key|access[_-]?token|secret|credential)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
)


def mask_message(message: str) -> str:
    masked = _PATTERNS[0].sub(lambda match: f"{match.group(1)}=***", message)
    return _PATTERNS[1].sub("Bearer ***", masked)


class MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return mask_message(rendered)


def configure_logging(
    *,
    level: str = "INFO",
    log_file: str | Path | None = None,
    experiment_id: str | None = None,
    logger_name: str = "dohalm",
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(level.upper())
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    experiment = f" experiment={experiment_id}" if experiment_id else ""
    formatter = MaskingFormatter(
        f"%(asctime)s %(levelname)s %(name)s{experiment} %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    setattr(console, _HANDLER_MARKER, True)
    logger.addHandler(console)

    if log_file is not None:
        destination = Path(log_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(destination, encoding="utf-8")
        file_handler.setFormatter(formatter)
        setattr(file_handler, _HANDLER_MARKER, True)
        logger.addHandler(file_handler)
    return logger
