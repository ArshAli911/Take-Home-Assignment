"""Centralized logging configuration.

Sets up a rotating file handler so logs persist across restarts
without growing unbounded, plus a console handler for container
environments where stdout is captured by Docker / orchestrator.
"""

import logging
from logging.handlers import RotatingFileHandler

from app.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_BACKUP_COUNT = 3


def setup_logging() -> None:
    """Configure the root logger with file + console handlers."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers on repeated calls (e.g. tests).
    if root.handlers:
        return

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
