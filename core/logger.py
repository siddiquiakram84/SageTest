# core/logger.py
"""
Centralized logger helper.

Usage:
    from core.logger import get_logger, enable_verbose_console
    logger = get_logger("/path/to/logs", "20250907_201820")
    enable_verbose_console(logger, level="DEBUG")   # optional: show very detailed steps
    logger.info("hello")
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional, Union

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

def get_logger(log_dir: Union[str, Path], ts: str, level: str = "INFO") -> logging.Logger:
    """
    Return a configured logger that writes JSON-lines to log_dir/<ts>/suite.log
    and also writes friendly messages to console.

    Idempotent per ts: calling repeatedly with same ts returns same logger instance.
    """
    log_dir = Path(log_dir)

    if log_dir.name == ts:
        file_dir = log_dir
    else:
        file_dir = log_dir / ts

    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / "suite.log"

    logger_name = f"sagetest.{ts}"
    logger = logging.getLogger(logger_name)

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

    logger.propagate = False

    try:
        logger.info(f"Logger initialized; writing json-lines to {file_path}")
    except Exception:
        pass

    return logger

def enable_verbose_console(logger: logging.Logger, level: str | int = logging.DEBUG, show_module: bool = False) -> None:
    """
    Add (or adjust) a verbose console handler to the provided logger.
    - level: logging level or string ("DEBUG", "INFO", ...)
    - show_module: if True, include module name in console messages
    This is idempotent (won't add duplicate handlers).
    """
    lvl = level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.DEBUG)

    # Avoid adding duplicate 'verbose' handlers: look for a handler with attribute 'sagetest_verbose'
    for h in getattr(logger, "handlers", []):
        if getattr(h, "sagetest_verbose", False):
            h.setLevel(lvl)
            return

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    if show_module:
        fmt = "%(asctime)s [%(levelname)s] %(name)s:%(module)s:%(lineno)d - %(message)s"

    h = logging.StreamHandler()
    h.setLevel(lvl)
    h.setFormatter(logging.Formatter(fmt))
    # mark handler so we don't re-add duplicates
    setattr(h, "sagetest_verbose", True)
    logger.addHandler(h)

    # also set logger level so debug messages will be emitted
    logger.setLevel(min(logger.level, lvl))
