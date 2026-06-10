"""Main-app heartbeat: writes a unix timestamp to Redis every 10s so the
watchdog (separate process) can detect app death. Failing to write is loud —
a broken heartbeat will eventually flatten positions via the watchdog, which
is the designed failure mode, not an error to swallow silently."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from goldguard.core.logging import get_logger

log = get_logger("heartbeat")

HEARTBEAT_KEY = "goldguard:heartbeat"
INTERVAL_S = 10


class Heartbeat:
    def __init__(self, write: Callable[[str, str], None], interval_s: float = INTERVAL_S):
        self._write = write
        self._interval = interval_s
        self.beats = 0

    def beat(self) -> None:
        self._write(HEARTBEAT_KEY, str(time.time()))
        self.beats += 1

    async def run(self) -> None:  # pragma: no cover - exercised via beat()
        while True:
            try:
                self.beat()
            except Exception:
                log.exception("heartbeat write failed — watchdog will react")
            await asyncio.sleep(self._interval)
