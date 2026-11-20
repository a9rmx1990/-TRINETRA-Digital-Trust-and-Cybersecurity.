"""Injectable clock. Tests replace `_source` to get deterministic time."""
from __future__ import annotations

import time
from typing import Callable

_source: Callable[[], int] = lambda: int(time.time() * 1000)

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def now_ms() -> int:
    return _source()


def set_source(fn: Callable[[], int]) -> None:
    global _source
    _source = fn


def reset() -> None:
    set_source(lambda: int(time.time() * 1000))


class FakeClock:
    def __init__(self, start_ms: int = 1_790_000_000_000):
        self.t = start_ms

    def __call__(self) -> int:
        return self.t

    def advance(self, ms: int) -> None:
        self.t += ms
