"""Server logger built on the repository's secret-masking formatter."""

from __future__ import annotations

import logging

from src.runtime.log_setup import configure_logging


def configure_server_logging(level: str) -> logging.Logger:
    return configure_logging(level=level, logger_name="dohalm.api")
