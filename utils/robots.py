"""
robots.py — robots.txt fetching, parsing, and per-domain rate limiting.

Responsibilities:
  - Fetch and cache robots.txt for each unique domain (lazy, async-safe)
  - Check whether a URL is allowed to be crawled (can_fetch)
  - Enforce crawl-delay from robots.txt, falling back to the caller's delay
"""

import asyncio
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsHandler:
    """
    Fetches robots.txt for each domain on first contact and answers:
      - is_allowed(url)      → should we scrape this URL?
      - wait_if_needed(url)  → async sleep to honour crawl-delay

    All parsers and timestamps are cached in-memory for the session.
    """

    def __init__(
        self,
        user_agent: str = "*",
        respect_robots: bool = True,
        respect_crawl_delay: bool = True,
    ):
        """
        Args:
            user_agent:           User-agent string sent to can_fetch().
                                  Use "*" to match the wildcard catch-all.
            respect_robots:       If False, is_allowed() always returns True.
            respect_crawl_delay:  If False, wait_if_needed() is a no-op.
        """
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.respect_crawl_delay = respect_crawl_delay

        self._parsers: dict[str, RobotFileParser] = {}
        self._crawl_delays: dict[str, float] = {}   # seconds
        self._last_request: dict[str, float] = {}   # monotonic timestamp
        # Per-domain locks ensure concurrent requests to the same domain
        # are serialised correctly through wait_if_needed().
        self._domain_locks: dict[str, asyncio.Lock] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch(self, url: str) -> None:
        """
        Fetch and cache robots.txt for the domain of *url*.
        No-op if the domain is already cached. Safe to call repeatedly.
        """
        origin = self._origin(url)
        if origin in self._parsers:
            return

        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser(robots_url)

        try:
            loop = asyncio.get_running_loop()
            # RobotFileParser.read() is synchronous — run it off the event loop
            await loop.run_in_executor(None, parser.read)

            # Prefer our user-agent's delay, fall back to wildcard, then 0
            delay = (
                parser.crawl_delay(self.user_agent)
                or parser.crawl_delay("*")
                or 0.0
            )
            delay = float(delay)
            status = f"crawl-delay={delay}s" if delay else "no crawl-delay"
            print(f"[Robots] {origin} -> {status}")
        except Exception as exc:
            print(f"[Robots] Could not fetch {robots_url}: {exc} -- assuming allowed")
            delay = 0.0

        self._parsers[origin] = parser
        self._crawl_delays[origin] = delay

    def is_allowed(self, url: str) -> bool:
        """
        Return True if the URL is allowed by robots.txt.
        Returns True for any domain whose robots.txt has not yet been fetched
        (fetch() must be called first for accurate results).
        Always returns True when respect_robots=False.
        """
        if not self.respect_robots:
            return True
        parser = self._parsers.get(self._origin(url))
        if parser is None:
            return True  # Not yet fetched → optimistic default
        return parser.can_fetch(self.user_agent, url)

    async def wait_if_needed(self, url: str, fallback_delay: float = 0.0) -> None:
        """
        Sleep long enough so that at least max(crawl-delay, fallback_delay)
        seconds have elapsed since the last request to this domain.

        *fallback_delay* is the caller's random politeness delay and acts as
        a minimum floor when robots.txt specifies no crawl-delay.
        Is a no-op when respect_crawl_delay=False.

        Thread-safe for concurrent scrapers: uses a per-domain asyncio.Lock so
        only one coroutine at a time advances the timestamp for a given domain.
        """
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _origin(url: str) -> str:
        """Return 'scheme://netloc' from a full URL."""
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
