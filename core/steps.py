# core/steps.py
"""Helpers to mark test steps: context manager + decorator + helper for pytest.
"""
from __future__ import annotations
import time
import functools
import logging
from contextlib import contextmanager
from typing import Callable, Any, Optional
from allure import step as allure_step  # type: ignore

logger = logging.getLogger("sagetest.steps")

@contextmanager
def step(name: str, *, level: str = "INFO"):
    """
    Context manager for a test step.
    Logs start/end to the global logger, writes elapsed time, and attaches an Allure step.
    Example:
        with step("Open page"):
            driver.get(url)
    """
    start = time.time()
    try:
        logger.log(getattr(logging, level.upper(), logging.INFO), "STEP START: %s", name)
    except Exception:
        pass

    # Allure context manager (if allure present)
    try:
        with allure_step(name):
            yield
    except Exception:
        # still yield exception to caller, but ensure logging
        raise
    finally:
        elapsed = time.time() - start
        try:
            logger.log(getattr(logging, level.upper(), logging.INFO), "STEP END  : %s (%.3fs)", name, elapsed)
        except Exception:
            pass


def step_decorator(name: Optional[str] = None, *, level: str = "INFO"):
    """
    Decorator factory that wraps a function in a step.
    Usage:
        @step_decorator("Fill login form")
        def fill_login(...):
            ...
    If name is None, function.__name__ will be used.
    """
    def _decorator(fn: Callable[..., Any]):
        step_name = name or fn.__name__

        if hasattr(fn, "__call__"):
            @functools.wraps(fn)
            def _sync_wrapper(*a, **k):
                with step(step_name, level=level):
                    return fn(*a, **k)
            return _sync_wrapper
        else:
            # unlikely: fallback
            @functools.wraps(fn)
            def _fallback(*a, **k):
                with step(step_name, level=level):
                    return fn(*a, **k)
            return _fallback
    return _decorator
