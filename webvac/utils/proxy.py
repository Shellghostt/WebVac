"""
proxy.py — Enhanced proxy pool manager.

New in v2:
  - Latency-based priority queue with EMA (Exponential Moving Average) tracking.
    Fastest proxies are always tried first; latency adapts in real-time.
  - Cool-down queue instead of immediate retirement.
    A 429 or timeout puts a proxy on a timed cool-down (default 300s). After
    cool-down it returns to the active pool. Only permanently retired after
    `max_cooldown_failures` consecutive cool-down failures.
  - Per-proxy pinned browser identity.
    Each proxy is assigned a locked UA + Sec-CH-UA + platform at init time,
    so every IP always appears as the same consistent device.
  - Async startup health-check + IP verification via httpbin.org/ip.
  - Sticky session request counter (used by crawler for voluntary rotation).

Proxy file format (one per line):
    server                         # e.g.  http://1.2.3.4:8080
    server|username|password       # e.g.  socks5://host:1080|alice|secret
    # lines starting with # are ignored
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp


# ── Curated browser identity pool ─────────────────────────────────────────────
# Each proxy is locked to one identity at startup so the same IP always presents
# the same consistent device fingerprint (not a rotating bot).
_IDENTITY_POOL: list[dict] = [
    {
        "ua":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "platform": "Windows",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    },
    {
        "ua":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
        "platform": "Windows",
        "sec_ch_ua": '"Chromium";v="123", "Google Chrome";v="123", "Not-A.Brand";v="99"',
    },
    {
        "ua":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "platform": "macOS",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    },
    {
        "ua":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "platform": "macOS",
        "sec_ch_ua": '"Chromium";v="123", "Google Chrome";v="123", "Not-A.Brand";v="99"',
    },
    {
        "ua":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Safari/537.36 Edg/124.0.0.0",
        "platform": "Windows",
        "sec_ch_ua": '"Chromium";v="124", "Microsoft Edge";v="124", "Not-A.Brand";v="99"',
    },
    {
        "ua":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "platform": "Windows",
        "sec_ch_ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
    },
    {
        "ua":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "platform": "macOS",
        "sec_ch_ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
    },
]


# ── ProxyEntry ────────────────────────────────────────────────────────────────

@dataclass
class ProxyEntry:
    """A single proxy server with credentials, latency tracking, and state."""

    server:   str
    username: str = ""
    password: str = ""

    # ── Latency tracking (EMA) ────────────────────────────────────────────────
    latency_ms: float = field(default=9999.0, repr=False)

    # ── Per-proxy locked browser identity ────────────────────────────────────
    pinned_ua:         str = field(default="", repr=False)
    pinned_platform:   str = field(default="", repr=False)
    pinned_sec_ch_ua:  str = field(default="", repr=False)

    # ── Failure / cool-down state ─────────────────────────────────────────────
    failures:                    int   = field(default=0,     repr=False)
    cooldown_until:              float = field(default=0.0,   repr=False)   # unix ts
    consecutive_cooldown_failures: int = field(default=0,     repr=False)
    is_dead:                     bool  = field(default=False, repr=False)

    # ── Sticky session counter ────────────────────────────────────────────────
    request_count: int = field(default=0, repr=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_patchright(self) -> dict:
        """Return a dict suitable for Patchright's ``proxy=`` context option."""
        d: dict = {"server": self.server}
        if self.username:
            d["username"] = self.username
        if self.password:
            d["password"] = self.password
        return d

    def is_on_cooldown(self) -> bool:
        return not self.is_dead and self.cooldown_until > time.time()

    def is_active(self) -> bool:
        return not self.is_dead and self.cooldown_until <= time.time()

    def __str__(self) -> str:
        return self.server


# ── ProxyManager ──────────────────────────────────────────────────────────────

class ProxyManager:
    """
    Manages a pool of proxies with smart rotation, cool-down, and latency ranking.

    Selection strategies:
      ``latency``    — Sort active proxies by EMA latency; pick randomly from
                       the top-third. Benchmarked at startup, updated per request.
      ``random``     — Uniform random selection from active pool.
      ``round_robin``— Sequential rotation through active pool.

    Failure modes:
      Transient (429, timeout, soft bot-block):
        → Cool-down queue for ``cooldown_seconds`` (default 300s).
          Returns to active pool automatically after timer expires.
          Permanently retired only after ``max_cooldown_failures`` consecutive
          cool-down failures.

      Hard (connection refused, unexpected 5xx):
        → Hard failure counter incremented. Retired after ``max_failures``.
    """

    def __init__(
        self,
        proxies:              list[ProxyEntry],
        strategy:             str   = "latency",
        max_failures:         int   = 3,
        cooldown_seconds:     float = 300.0,
        max_cooldown_failures: int  = 3,
    ):
        if not proxies:
            raise ValueError("[Proxy] Proxy list is empty.")
        self.proxies               = list(proxies)
        self.strategy              = strategy
        self.max_failures          = max_failures
        self.cooldown_seconds      = cooldown_seconds
        self.max_cooldown_failures = max_cooldown_failures
        self._rr_index             = 0

        # Assign a locked browser identity to every proxy at init time
        self._assign_identities()

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
        parts  = [p.strip() for p in line.split("|")]
        return ProxyEntry(
            server   = parts[0],
            username = parts[1] if len(parts) > 1 else "",
            password = parts[2] if len(parts) > 2 else "",
        )

    # ── Identity assignment ───────────────────────────────────────────────────

    def _assign_identities(self) -> None:
        """
        Assign a randomly selected, LOCKED browser identity to each proxy.
        Once assigned, this identity never changes for that proxy — the same
        IP always appears as the same device (consistent fingerprint per source IP).
        """
        for proxy in self.proxies:
            if not proxy.pinned_ua:
                identity = random.choice(_IDENTITY_POOL)
                proxy.pinned_ua        = identity["ua"]
                proxy.pinned_platform  = identity["platform"]
                proxy.pinned_sec_ch_ua = identity["sec_ch_ua"]

    # ── Async startup health-check ────────────────────────────────────────────

    async def benchmark_all(self, health_check_url: str = "http://httpbin.org/ip") -> None:
        """
        Concurrently benchmark all proxies against ``health_check_url``.

        For each proxy:
          - Measures response latency (ms).
          - Verifies the response includes an IP field (confirms traffic is routed).
          - Immediately retires unreachable / slow proxies.
          - Sets the initial ``latency_ms`` for EMA tracking.

        Prints a formatted summary table after all probes complete.
        """

        async def _bench_one(entry: ProxyEntry) -> None:
            timeout    = aiohttp.ClientTimeout(total=10)
            proxy_auth = (
                aiohttp.BasicAuth(entry.username, entry.password)
                if entry.username else None
            )
            start = time.monotonic()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        health_check_url,
                        proxy      = entry.server,
                        proxy_auth = proxy_auth,
                        timeout    = timeout,
                        ssl        = False,
                    ) as resp:
                        elapsed_ms = (time.monotonic() - start) * 1000
                        if resp.status == 200:
                            try:
                                data        = await resp.json(content_type=None)
                                reported_ip = data.get("origin", data.get("ip", "unknown"))
                            except Exception:
                                reported_ip = "unknown"
                            entry.latency_ms = elapsed_ms
                            print(
                                f"[Proxy] [Bench]  ✓  {entry.server:<42s}  "
                                f"{elapsed_ms:>6.0f}ms   IP={reported_ip}"
                            )
                        else:
                            entry.is_dead = True
                            print(
                                f"[Proxy] [Bench]  ✗  {entry.server:<42s}  "
                                f"HTTP {resp.status} → retired"
                            )
            except Exception as exc:
                entry.is_dead = True
                reason = str(exc)[:55]
                print(
                    f"[Proxy] [Bench]  ✗  {entry.server:<42s}  "
                    f"ERROR: {reason}"
                )

        print(f"\n[Proxy] {'─'*65}")
        print(f"[Proxy]  Benchmarking {len(self.proxies)} proxies  →  {health_check_url}")
        print(f"[Proxy] {'─'*65}")

        await asyncio.gather(*[_bench_one(p) for p in self.proxies])

        active = [p for p in self.proxies if not p.is_dead]
        print(f"[Proxy] {'─'*65}")
        if active:
            avg     = sum(p.latency_ms for p in active) / len(active)
            fastest = min(active, key=lambda p: p.latency_ms)
            print(
                f"[Proxy]  ✓  {len(active)}/{len(self.proxies)} healthy  |  "
                f"avg={avg:.0f}ms  |  fastest={fastest.server} ({fastest.latency_ms:.0f}ms)"
            )
        else:
            print("[Proxy]  ⚠  All proxies failed health-check. No proxies available.")
        print(f"[Proxy] {'─'*65}\n")

    # ── Cool-down reactivation ────────────────────────────────────────────────

    def _reactivate_cooled_down(self) -> None:
        """Move proxies whose cool-down period has expired back to active."""
        now = time.time()
        for p in self.proxies:
            if not p.is_dead and 0 < p.cooldown_until <= now:
                p.cooldown_until = 0.0
                print(
                    f"[Proxy] [Cooldown]  ↩  {p.server} reactivated after "
                    f"{self.cooldown_seconds:.0f}s cool-down."
                )

    # ── Core selection ────────────────────────────────────────────────────────

    def get_next(self, exclude: Optional[ProxyEntry] = None) -> Optional[ProxyEntry]:
        """
        Return the best available proxy, or None if all are exhausted.

        Always reactivates any expired cool-down proxies first.
        With strategy='latency', randomly samples from the top-third fastest
        active proxies (prevents hammering a single best proxy).
        """
        self._reactivate_cooled_down()
        now = time.time()

        active = [
            p for p in self.proxies
            if not p.is_dead
            and p.cooldown_until <= now
            and p is not exclude
        ]

        if not active:
            print("[Proxy]  ⚠  No active proxies available.")
            return None

        if self.strategy == "latency":
            active.sort(key=lambda p: p.latency_ms)
            top_n = max(1, len(active) // 3)
            return random.choice(active[:top_n])

        elif self.strategy == "round_robin":
            proxy = active[self._rr_index % len(active)]
            self._rr_index += 1
            return proxy

        else:  # "random"
            return random.choice(active)

    # ── Failure / success tracking ────────────────────────────────────────────

    def mark_failure(self, proxy: ProxyEntry, transient: bool = True) -> None:
        """
        Record a failure for the given proxy.

        Args:
            proxy:     The ProxyEntry that failed.
            transient: True  → 429, timeout, soft bot-block → cool-down queue.
                       False → hard error (connection refused) → hard failure counter.
        """
        if proxy.is_dead:
            return

        if transient:
            proxy.cooldown_until              = time.time() + self.cooldown_seconds
            proxy.consecutive_cooldown_failures += 1

            if proxy.consecutive_cooldown_failures >= self.max_cooldown_failures:
                proxy.is_dead = True
                print(
                    f"[Proxy] [Retired]   ✗  {proxy.server} permanently retired — "
                    f"failed {proxy.consecutive_cooldown_failures}× after cool-down."
                )
            else:
                remaining = self.max_cooldown_failures - proxy.consecutive_cooldown_failures
                print(
                    f"[Proxy] [Cooldown]  ⏳  {proxy.server} on cool-down for "
                    f"{self.cooldown_seconds:.0f}s  "
                    f"(strike {proxy.consecutive_cooldown_failures}/{self.max_cooldown_failures}, "
                    f"{remaining} before permanent retirement)."
                )
        else:
            proxy.failures += 1
            if proxy.failures >= self.max_failures:
                proxy.is_dead = True
                print(
                    f"[Proxy] [Retired]   ✗  {proxy.server} permanently retired after "
                    f"{proxy.failures} hard failure(s)."
                )
            else:
                remaining = self.max_failures - proxy.failures
                print(
                    f"[Proxy] [Warning]   ⚠  {proxy.server} — hard failure "
                    f"{proxy.failures}/{self.max_failures} "
                    f"({remaining} remaining before retirement)."
                )

    def mark_success(self, proxy: ProxyEntry) -> None:
        """Reset all failure counters on a successful request (positive reinforcement)."""
        proxy.failures                    = 0
        proxy.consecutive_cooldown_failures = 0

    def update_latency(self, proxy: ProxyEntry, measured_ms: float, alpha: float = 0.3) -> None:
        """
        Update proxy latency using Exponential Moving Average (EMA).

        EMA formula: new = α × measured + (1-α) × historical
        alpha=0.3 → 30% new measurement, 70% historical average.
        Lower alpha  → more stable, slower to adapt.
        Higher alpha → faster to reflect recent network conditions.
        """
        if proxy.latency_ms >= 9999.0:
            proxy.latency_ms = measured_ms          # first real measurement
        else:
            proxy.latency_ms = alpha * measured_ms + (1.0 - alpha) * proxy.latency_ms

    # ── Sticky session helpers ────────────────────────────────────────────────

    def increment_request_count(self, proxy: ProxyEntry) -> int:
        """Increment the per-proxy request counter and return the new count."""
        proxy.request_count += 1
        return proxy.request_count

    def reset_request_count(self, proxy: ProxyEntry) -> None:
        """Reset the request counter (called after any rotation, voluntary or forced)."""
        proxy.request_count = 0

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> str:
        """Human-readable pool status string."""
        now     = time.time()
        active  = sum(1 for p in self.proxies if p.is_active())
        cooling = sum(1 for p in self.proxies if not p.is_dead and p.cooldown_until > now)
        dead    = sum(1 for p in self.proxies if p.is_dead)
        return f"{active} active / {cooling} cooling / {dead} dead / {len(self.proxies)} total"
