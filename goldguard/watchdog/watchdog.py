"""GOLDGUARD watchdog — independent dead-man's switch (spec §6).

Runs in its own container with its own broker session. It shares NOTHING
with the main app except environment configuration. Its only powers are:
read a heartbeat, read positions, flatten, alert. It cannot place entries,
cannot change risk config, cannot un-halt anything.

Logic: if the main app's Redis heartbeat is stale for more than
``stale_after_s`` (default 60) AND the broker shows open positions, flatten
everything through this process's own broker connection, then alert.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Callable

log = logging.getLogger("goldguard.watchdog")

CHECK_INTERVAL_S = 10


class Watchdog:
    def __init__(
        self,
        heartbeat_age_s: Callable[[], float | None],  # None = no heartbeat ever seen
        open_position_count: Callable[[], int],
        flatten: Callable[[], None],
        alert: Callable[[str], None],
        stale_after_s: float = 60.0,
    ):
        self._heartbeat_age_s = heartbeat_age_s
        self._open_position_count = open_position_count
        self._flatten = flatten
        self._alert = alert
        self._stale_after_s = stale_after_s

    def check_once(self) -> str:
        age = self._heartbeat_age_s()
        if age is not None and age <= self._stale_after_s:
            return "ok"
        positions = self._open_position_count()
        if positions == 0:
            self._alert(f"watchdog: heartbeat stale (age={age}), no open positions")
            return "stale-flat"
        self._flatten()
        self._alert(
            f"WATCHDOG FLATTENED {positions} position(s): main app heartbeat stale (age={age})"
        )
        return "flattened"

    def run_forever(self, interval_s: float = CHECK_INTERVAL_S) -> None:  # pragma: no cover
        while True:
            try:
                self.check_once()
            except Exception:
                log.exception("watchdog check failed")
            time.sleep(interval_s)


def _redis_heartbeat_age(redis_url: str) -> Callable[[], float | None]:  # pragma: no cover
    import redis

    client = redis.Redis.from_url(redis_url)

    def age() -> float | None:
        raw = client.get("goldguard:heartbeat")
        if raw is None:
            return None
        return time.time() - float(raw)

    return age


def _webhook_alert(url: str) -> Callable[[str], None]:  # pragma: no cover
    def alert(message: str) -> None:
        log.critical(message)
        if not url:
            return
        req = urllib.request.Request(
            url, data=json.dumps({"text": message}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)

    return alert


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    from ib_insync import IB, MarketOrder  # own broker session, no app code

    ib = IB()
    ib.connect(
        os.environ.get("GOLDGUARD_IB_HOST", "127.0.0.1"),
        int(os.environ.get("GOLDGUARD_IB_PORT", "7497")),
        clientId=int(os.environ.get("GOLDGUARD_WATCHDOG_CLIENT_ID", "99")),
    )

    def open_position_count() -> int:
        return sum(1 for p in ib.positions() if p.position != 0)

    def flatten() -> None:
        ib.reqGlobalCancel()
        for p in ib.positions():
            if p.position != 0:
                action = "SELL" if p.position > 0 else "BUY"
                ib.placeOrder(p.contract, MarketOrder(action, abs(int(p.position))))

    watchdog = Watchdog(
        heartbeat_age_s=_redis_heartbeat_age(os.environ.get("GOLDGUARD_REDIS_URL", "redis://redis:6379/0")),
        open_position_count=open_position_count,
        flatten=flatten,
        alert=_webhook_alert(os.environ.get("GOLDGUARD_ALERT_WEBHOOK_URL", "")),
        stale_after_s=float(os.environ.get("GOLDGUARD_WATCHDOG_STALE_AFTER_S", "60")),
    )
    watchdog.run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
