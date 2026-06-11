"""
proxy.py — Proxy pool manager with rotation, failure tracking, and Playwright integration.

Proxy file format (one per line):
    server                         # e.g.  http://1.2.3.4:8080
    server|username|password       # e.g.  socks5://host:1080|alice|secret
    # lines starting with # are ignored

Inline (CLI --proxies flag), comma-separated, same format per token.
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProxyEntry:
    """A single proxy server with optional credentials."""

    server: str       # e.g. "http://1.2.3.4:8080" or "socks5://host:1080"
    username: str = ""
    password: str = ""
    failures: int = field(default=0, repr=False)

    def to_playwright(self) -> dict:
        """Return a dict suitable for Playwright's `proxy=` context option."""
        d: dict = {"server": self.server}
        if self.username:
            d["username"] = self.username
        if self.password:
            d["password"] = self.password
        return d

    def __str__(self) -> str:
        return self.server


class ProxyManager:
    """
    Manages a pool of proxies with round-robin or random rotation.

    A proxy is considered *retired* once its failure count reaches
    `max_failures`. Retired proxies are skipped by get_next().
    mark_success() resets a proxy's failure count (positive reinforcement).
    """

    def __init__(
        self,
        proxies: list[ProxyEntry],
        strategy: str = "random",    # "random" | "round_robin"
        max_failures: int = 3,
    ):
        if not proxies:
            raise ValueError("[Proxy] Proxy list is empty.")
        self.proxies = list(proxies)
        self.strategy = strategy
        self.max_failures = max_failures
        self._rr_index = 0           # cursor for round-robin

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str, **kwargs) -> "ProxyManager":
        """Load proxies from a text file (one per line)."""
        entries: list[ProxyEntry] = []
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                entries.append(cls._parse_line(line))

        if not entries:
            raise ValueError(f"[Proxy] No valid proxies found in {path}")
        print(f"[Proxy] Loaded {len(entries)} proxies from {path}")
        return cls(entries, **kwargs)

    @classmethod
    def from_strings(cls, proxy_strings: list[str], **kwargs) -> "ProxyManager":
        """Load proxies from a list of raw strings (same format as file lines)."""
        entries = [cls._parse_line(s) for s in proxy_strings if s.strip()]
        if not entries:
            raise ValueError("[Proxy] No valid proxies found in the provided list.")
        print(f"[Proxy] Loaded {len(entries)} proxies from CLI argument")
        return cls(entries, **kwargs)

    @staticmethod
    def _parse_line(line: str) -> ProxyEntry:
        """Parse 'server' or 'server|user|pass' into a ProxyEntry."""
        parts = [p.strip() for p in line.split("|")]
        server   = parts[0]
        username = parts[1] if len(parts) > 1 else ""
        password = parts[2] if len(parts) > 2 else ""
        return ProxyEntry(server=server, username=username, password=password)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_next(self) -> Optional[ProxyEntry]:
        """
        Return the next non-retired proxy from the pool.
        Returns None if all proxies have been retired.
        """
        active = [p for p in self.proxies if p.failures < self.max_failures]
        if not active:
            print("[Proxy] [Warning] All proxies are exhausted -- no more proxies available.")
            return None

        if self.strategy == "round_robin":
            proxy = active[self._rr_index % len(active)]
            self._rr_index += 1
        else:
            proxy = random.choice(active)

        return proxy

    def mark_failure(self, proxy: ProxyEntry) -> None:
        """Increment the failure counter. Prints a warning when the proxy is retired."""
        proxy.failures += 1
        if proxy.failures >= self.max_failures:
            print(f"[Proxy] [Retired] {proxy.server} retired after {proxy.failures} failure(s).")
        else:
            remaining = self.max_failures - proxy.failures
            print(f"[Proxy] [Warning] {proxy.server} -- failure {proxy.failures}/{self.max_failures} "
                  f"({remaining} left before retirement).")

    def mark_success(self, proxy: ProxyEntry) -> None:
        """Reset failure count on a successful request (positive reinforcement)."""
        if proxy.failures > 0:
            proxy.failures = 0

    def status(self) -> str:
        """Human-readable pool status string."""
        active = sum(1 for p in self.proxies if p.failures < self.max_failures)
        return f"{active}/{len(self.proxies)} proxies active"
