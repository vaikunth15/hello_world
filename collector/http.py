"""Polite HTTP: robots.txt, per-host delay, retries, and block detection."""
from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "CoimbatoreRealEstateIndex/1.0 (+https://github.com/vaikunth15/hello_world; weekly research crawl)"
)


class Blocked(Exception):
    """The site refused us (robots.txt, 403/429, captcha). Not a parser bug."""


class Fetcher:
    def __init__(self, delay_seconds: float = 4.0, timeout: int = 30, respect_robots: bool = True,
                 user_agent: str = USER_AGENT):
        self.delay = delay_seconds
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        })
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.pages_fetched = 0

    def _robots_ok(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(root + "/robots.txt", timeout=self.timeout)
                if r.status_code >= 400:
                    rp = None  # no robots.txt -> allowed
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots[root] = rp
        rp = self._robots[root]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def _throttle(self, host: str):
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.delay + random.uniform(0, self.delay / 2) - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, retries: int = 3, **kw) -> requests.Response:
        if not self._robots_ok(url):
            raise Blocked(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        for attempt in range(retries):
            self._throttle(host)
            try:
                r = self.session.get(url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                log.warning("GET %s failed (%s), attempt %d", url, e, attempt + 1)
                time.sleep(2 ** (attempt + 1))
                continue
            self.pages_fetched += 1
            if r.status_code in (403, 401, 451):
                raise Blocked(f"HTTP {r.status_code} from {host}")
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(int(r.headers.get("Retry-After", 2 ** (attempt + 2))))
                continue
            body_head = r.text[:4000].lower() if "text" in r.headers.get("content-type", "") else ""
            if any(s in body_head for s in ("cf-challenge", "cf_chl_", "challenge-platform", "px-captcha",
                                            "<title>access denied", "are you a robot", "verify you are human")):
                raise Blocked(f"bot challenge from {host}")
            r.raise_for_status()
            return r
        raise Blocked(f"gave up on {url} after {retries} attempts")
