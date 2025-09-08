# core/metrics.py
"""
Simple metrics helpers: Timer and a metrics container.

"""
import time
from typing import Dict, Any

class Timer:
    def __init__(self):
        self._start = None
        self._end = None

    def start(self):
        self._start = time.time()
        self._end = None

    def stop(self):
        if self._start is None:
            return
        self._end = time.time()

    @property
    def elapsed(self) -> float:
        if self._start is None:
            return 0.0
        if self._end is None:
            return time.time() - self._start
        return self._end - self._start

class Metrics:
    def __init__(self):
        self.counters = {}
        self.timers = {}

    def incr(self, name: str, by: int = 1):
        self.counters[name] = self.counters.get(name, 0) + by

    def get_counter(self, name: str) -> int:
        return int(self.counters.get(name, 0))

    def start_timer(self, name: str):
        t = Timer()
        t.start()
        self.timers[name] = t

    def stop_timer(self, name: str):
        t = self.timers.get(name)
        if t:
            t.stop()

    def get_timer(self, name: str) -> float:
        t = self.timers.get(name)
        return float(t.elapsed) if t else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "timers": {k: v.elapsed for k, v in self.timers.items()}
        }
