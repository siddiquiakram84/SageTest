# core/logger.py
"""
Centralized logger helper.

Usage:
    from core.logger import get_logger
    logger = get_logger("/path/to/logdir", "20250907_201820")
    logger.info("hello")
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": getattr(record, "created", None),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)

def get_logger(log_dir: str | Path, ts: str, level: str = "INFO") -> logging.Logger:
    """
    Return a configured logger that writes JSON-lines to log_dir/<ts>/suite.log
    and also writes friendly messages to console.

    Idempotent: calling repeatedly returns the same logger instance (handlers
    are not duplicated).
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_path = log_path / "suite.log"

    logger = logging.getLogger("sagetest")
    # Avoid re-adding handlers if called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler (human-friendly)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    # File handler (JSON lines)
    fh = logging.FileHandler(str(file_path), encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)

    # Don't propagate to root logger
    logger.propagate = False
    logger.info(f"Logger initialized; writing json-lines to {file_path}")
    return logger
