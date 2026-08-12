"""
robots.py — robots.txt fetching, parsing, and per-domain rate limiting.

Responsibilities:
  - Fetch and cache robots.txt for each unique domain (lazy, async-safe)
  - Check whether a URL is allowed to be crawled (can_fetch)
  - Enforce crawl-delay from robots.txt, falling back to the caller's delay

Important: many CDNs return HTTP 403 to Python's default User-Agent for
/robots.txt. urllib.robotparser treats 401/403 as \"disallow entire site\",
which falsely blocks crawls (e.g. spacex.com). We always fetch with a
browser-like User-Agent and map 404 → allow-all.
"""

from __future__ import annotations

import asyncio
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

# Browser-like UA so CDNs don't 403 the robots.txt fetch itself.
_DEFAULT_FETCH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class RobotsHandler:
    """
    Fetches robots.txt for each domain on first contact and answers:
      - is_allowed(url)      → should we scrape this URL?
      - wait_if_needed(url)  → async sleep to honour crawl-delay
    """

    def __init__(
        self,
        user_agent: str = "*",
        respect_robots: bool = True,
        respect_crawl_delay: bool = True,
        fetch_user_agent: str | None = None,
    ):
        """
        Args:
            user_agent:           UA string passed to can_fetch() (rule matching).
                                  Use "*" to match the wildcard catch-all.
            respect_robots:       If False, is_allowed() always returns True.
            respect_crawl_delay:  If False, wait_if_needed() is a no-op.
            fetch_user_agent:     UA used only when downloading robots.txt.
                                  Defaults to a Chrome-like string so CDNs don't
                                  403 the fetch (which robotparser treats as
                                  disallow-all).
        """
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.respect_crawl_delay = respect_crawl_delay
        self.fetch_user_agent = (fetch_user_agent or _DEFAULT_FETCH_UA).strip() or _DEFAULT_FETCH_UA

        self._parsers: dict[str, RobotFileParser] = {}
        self._crawl_delays: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._allow_all: set[str] = set()  # origins whose robots.txt was missing/unusable

    async def fetch(self, url: str) -> None:
        """Fetch and cache robots.txt for the domain of *url*."""
        origin = self._origin(url)
        if origin in self._parsers or origin in self._allow_all:
            return

        robots_url = f"{origin}/robots.txt"
        loop = asyncio.get_running_loop()
        try:
            status, body = await asyncio.wait_for(
                loop.run_in_executor(None, self._download_robots, robots_url),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            print(f"[Robots] Timeout fetching {robots_url} -- assuming allowed")
            self._allow_all.add(origin)
            self._crawl_delays[origin] = 0.0
            return
        except Exception as exc:
            print(f"[Robots] Could not fetch {robots_url}: {exc} -- assuming allowed")
            self._allow_all.add(origin)
            self._crawl_delays[origin] = 0.0
            return

        parser = RobotFileParser()
        parser.set_url(robots_url)

        if status == 404:
            # No robots.txt → allow everything (RFC / common practice)
            parser.allow_all = True
            self._allow_all.add(origin)
            self._parsers[origin] = parser
            self._crawl_delays[origin] = 0.0
            print(f"[Robots] {origin} -> no robots.txt (404) — allowing all")
            return

        if status in (401, 403):
            # RFC: authenticate/forbidden robots.txt ⇒ disallow all.
            # In practice CDNs often 403 bot UAs; we already used a browser UA.
            # Still honour RFC when we truly get 403 with that UA.
            parser.disallow_all = True
            self._parsers[origin] = parser
            self._crawl_delays[origin] = 0.0
            print(
                f"[Robots] {origin} -> HTTP {status} on robots.txt — "
                f"treating site as disallowed (use --no-robots to override)"
            )
            return

        if status >= 400 or body is None:
            print(f"[Robots] {origin} -> HTTP {status} on robots.txt — assuming allowed")
            self._allow_all.add(origin)
            self._crawl_delays[origin] = 0.0
            return

        try:
            lines = body.decode("utf-8", "replace").splitlines()
            parser.parse(lines)
        except Exception as exc:
            print(f"[Robots] Failed to parse {robots_url}: {exc} — assuming allowed")
            self._allow_all.add(origin)
            self._crawl_delays[origin] = 0.0
            return

        delay = (
            parser.crawl_delay(self.user_agent)
            or parser.crawl_delay("*")
            or 0.0
        )
        delay = float(delay or 0.0)
        status_msg = f"crawl-delay={delay}s" if delay else "no crawl-delay"
        print(f"[Robots] {origin} -> {status_msg}")

        self._parsers[origin] = parser
        self._crawl_delays[origin] = delay

    def _download_robots(self, robots_url: str) -> tuple[int, bytes | None]:
        """Blocking download of robots.txt with a browser-like User-Agent."""
        req = Request(
            robots_url,
            headers={
                "User-Agent": self.fetch_user_agent,
                "Accept": "text/plain,*/*",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=12) as resp:
                return int(getattr(resp, "status", 200) or 200), resp.read()
        except HTTPError as err:
            # Include body for debugging; callers key off status
            try:
                body = err.read()
            except Exception:
                body = None
            return int(err.code), body
        except URLError:
            raise

    def is_allowed(self, url: str) -> bool:
        """
        Return True if the URL is allowed by robots.txt.
        Returns True when robots.txt was missing or respect_robots=False.
        """
        if not self.respect_robots:
            return True
        origin = self._origin(url)
        if origin in self._allow_all:
            return True
        parser = self._parsers.get(origin)
        if parser is None:
            return True  # Not yet fetched → optimistic default
        if getattr(parser, "allow_all", False):
            return True
        if getattr(parser, "disallow_all", False):
            return False
        return bool(parser.can_fetch(self.user_agent, url))

    async def wait_if_needed(self, url: str, fallback_delay: float = 0.0) -> None:
        """Sleep to honour crawl-delay / politeness floor."""
        if not self.respect_crawl_delay:
            return

        origin = self._origin(url)
        if origin not in self._domain_locks:
            self._domain_locks[origin] = asyncio.Lock()

        async with self._domain_locks[origin]:
            robots_delay = self._crawl_delays.get(origin, 0.0)
            effective_delay = max(robots_delay, fallback_delay)

            if effective_delay > 0:
                last = self._last_request.get(origin, 0.0)
                elapsed = time.monotonic() - last
                wait = effective_delay - elapsed
                if wait > 0:
                    src = "robots.txt" if robots_delay >= fallback_delay else "politeness"
                    print(f"[Robots] Waiting {wait:.1f}s for {origin} ({src})")
                    await asyncio.sleep(wait)

            self._last_request[origin] = time.monotonic()

    @staticmethod
    def _origin(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
