"""
crawler.py — BFS site crawler + single-page mode.

Changes over v1:
  - `concurrency` parameter: scrape N pages in parallel with asyncio.gather.
    Defaults to 1 (sequential, backward-compatible).
  - tqdm progress bars for both single-page and crawl modes.
  - HTTP 429 → proxy rotation + exponential back-off.
  - robots.txt fetched lazily per domain; disallowed URLs skipped.
  - Per-URL page lifecycle (no shared Page object) enables safe proxy rotation.
  - BFS `queued` set prevents duplicate enqueues; `visited` prevents re-scraping.
  - _scroll_page uses actual viewport height (1080px).
"""

import asyncio
import re
import random
import time
import aiohttp
from collections import deque
from typing import Any, Optional
from urllib.parse import urlparse

from tqdm import tqdm
from patchright.async_api import Page
from utils.browser import BrowserManager
from data.page_record import PageRecordBuilder
from config.config import DEFAULT_CONFIG
from utils.robots import RobotsHandler
from utils.proxy import ProxyManager, ProxyEntry
from utils.screenshot import ScreenshotModule
from utils.detection import wait_for_challenge_resolution
from utils.browser_pool import SlotIdentity
from utils.cf_hero import discover_origin, find_cf_hero_bin

from core.pipeline import PipelineManager
from core.page_scrape_flow import run_page_scrape
from collectors.engine import CollectorEngine
from collectors.network.collector import NetworkCollector
from collectors.base import CollectorContext
from store.artifact_store import ArtifactStore
from scope.scope_manager import CrawlScope, ScopeManager
from models.scan import ScanMetadata, TargetMetadata
from models.origin import OriginTarget
from graph.endpoint_graph import EndpointGraph


class Crawler:

    def __init__(
        self,
        browser: BrowserManager,
        max_depth: int = DEFAULT_CONFIG["max_depth"],
        max_pages: Optional[int] = None,
        delay_min: float = DEFAULT_CONFIG["delay_min"],
        delay_max: float = DEFAULT_CONFIG["delay_max"],
        timeout: int = DEFAULT_CONFIG["timeout"],
        same_domain_only: bool = True,
        robots_handler: Optional[RobotsHandler] = None,
        proxy_manager: Optional[ProxyManager] = None,
        max_retries: int = DEFAULT_CONFIG["max_retries"],
        concurrency: int = DEFAULT_CONFIG["concurrency"],
        wait_until: str = DEFAULT_CONFIG["wait_until"],
        spa_delay: int = DEFAULT_CONFIG["spa_delay"],
        scroll_viewport: int = DEFAULT_CONFIG["scroll_viewport"],
        scroll_delay: float = DEFAULT_CONFIG["scroll_delay"],
        screenshot_module: Optional[ScreenshotModule] = None,
        output_dir: str = DEFAULT_CONFIG["output_dir"],
        extract_css: Optional[list[str]] = None,
        extract_xpath: Optional[list[str]] = None,
        allow_url_regex: Optional[str] = None,
        deny_url_regex: Optional[str] = None,
        pipeline_manager: Optional[PipelineManager] = None,
        engine: str = "dynamic",
        captcha_prompt_enabled: bool = True,
        sticky_requests: int = DEFAULT_CONFIG["sticky_requests"],
        recon_config: Optional[dict[str, Any]] = None,
        auth_manager=None,
    ):
        self.browser = browser
        self.page_builder = PageRecordBuilder(
            extract_css=extract_css, extract_xpath=extract_xpath
        )
        self.allow_regex = re.compile(allow_url_regex) if allow_url_regex else None
        self.deny_regex = re.compile(deny_url_regex) if deny_url_regex else None
        self.pipeline_manager = pipeline_manager
        self.engine = engine
        self.captcha_prompt_enabled = captcha_prompt_enabled
        self.sticky_requests = sticky_requests
        self.auth_manager = auth_manager

        self.max_depth = max_depth
        self.max_pages = max_pages
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.same_domain_only = same_domain_only
        self.robots = robots_handler
        self.proxy_manager = proxy_manager
        self.max_retries = max_retries
        self.concurrency = max(1, concurrency)
        self.wait_until = wait_until
        self.spa_delay = spa_delay
        self.scroll_viewport = scroll_viewport
        self.scroll_delay = scroll_delay
        self.screenshot_module = screenshot_module
        self.output_dir = output_dir

        # Tracks slot-0 proxy (backward compat); use _proxy_for_slot() per worker.
        self._slot_proxies: list[Optional[ProxyEntry]] = [None] * self.concurrency

        # VAPT pipeline — optional; disabled in scraper until re-enabled
        self.session_config = recon_config or dict(DEFAULT_CONFIG)
        self._vapt = bool(self.session_config.get("vapt_enabled"))
        self.artifact_store: Optional[ArtifactStore] = None
        self.scope_manager: Optional[ScopeManager] = None
        self.collector_engine = CollectorEngine() if self._vapt else None
        self.endpoint_graph: Optional[EndpointGraph] = None
        self._scan: Optional[ScanMetadata] = None
        self._seed_url: Optional[str] = None
        self._partial_results: list[dict] = []
        self._proxy_lock = asyncio.Lock()
        self._challenge_wait_ms = int(
            self.session_config.get("challenge_wait_ms", DEFAULT_CONFIG["challenge_wait_ms"])
        )
        self._scroll_max_steps = int(
            self.session_config.get("scroll_max_steps", DEFAULT_CONFIG["scroll_max_steps"])
        )
        self._origin: Optional[OriginTarget] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._cf_hero_hosts_attempted: set[str] = set()
        raw_origin = self.session_config.get("origin_access")
        if raw_origin:
            self._origin = (
                raw_origin
                if isinstance(raw_origin, OriginTarget)
                else OriginTarget.from_dict(raw_origin)
            )

    def init_slot_proxies(self, entries: list[Optional[ProxyEntry]]) -> None:
        """Assign one proxy per concurrent worker slot."""
        for i in range(self.concurrency):
            self._slot_proxies[i] = entries[i] if i < len(entries) else None

    def _proxy_for_slot(self, slot: int) -> Optional[ProxyEntry]:
        return self._slot_proxies[slot % self.concurrency]

    def _build_slot_identities(self) -> list[SlotIdentity]:
        default_sec = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
        identities: list[SlotIdentity] = []
        for i in range(self.concurrency):
            entry = self._slot_proxies[i]
            if entry:
                identities.append(SlotIdentity(
                    proxy=entry.to_patchright(),
                    ua=entry.pinned_ua or "",
                    platform=entry.pinned_platform or "Windows",
                    sec_ch_ua=entry.pinned_sec_ch_ua or default_sec,
                ))
            else:
                identities.append(SlotIdentity())
        return identities

    async def _ensure_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout / 1000.0),
            )
        return self._http_session

    async def _close_http_session(self) -> None:
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

    async def _try_cf_hero_fallback(self, url: str) -> bool:
        """On bot block, discover origin via CF-Hero and reconfigure the browser."""
        if self._origin:
            return False
        if not self.session_config.get("cf_hero_auto_fallback", True):
            return False

        hostname = urlparse(url).netloc.split(":")[0].lower()
        if not hostname or hostname in self._cf_hero_hosts_attempted:
            return False
        if not find_cf_hero_bin(self.session_config.get("cf_hero_bin")):
            return False

        self._cf_hero_hosts_attempted.add(hostname)
        seed = self._seed_url or url
        proxy_url = None
        slot0 = self._proxy_for_slot(0)
        if slot0:
            proxy_url = slot0.server

        extra_raw = self.session_config.get("cf_hero_args") or ""
        extra = [a for a in extra_raw.split() if a] if extra_raw else None

        tqdm.write(f"[CF-Hero] Auto-fallback: discovering origin for {hostname}...")
        try:
            origin = await discover_origin(
                seed,
                hostname,
                bin_path=self.session_config.get("cf_hero_bin"),
                extra_args=extra,
                expected_title=self.session_config.get("origin_title") or "",
                proxy=proxy_url,
            )
        except Exception as exc:
            tqdm.write(f"[CF-Hero] Auto-fallback failed: {exc}")
            return False

        if not origin:
            return False

        self._origin = origin
        self.session_config["origin_access"] = origin.to_dict()
        if self.scope_manager:
            self.scope_manager.scope.origin_access = origin

        await self.browser.reconfigure_host_resolver(
            origin.host_resolver_rule(),
            slot_identities=self._build_slot_identities(),
        )
        tqdm.write(
            f"[CF-Hero] Origin bypass active: {origin.origin_ip} "
            f"(Host: {origin.hostname})"
        )
        return True


    @property
    def _current_proxy(self) -> Optional[ProxyEntry]:
        return self._proxy_for_slot(0)

    @_current_proxy.setter
    def _current_proxy(self, value: Optional[ProxyEntry]) -> None:
        self._slot_proxies[0] = value

    @property
    def origin_target(self) -> Optional[OriginTarget]:
        return self._origin

    @property
    def partial_results(self) -> list[dict]:
        """Pages scraped so far — used when the run is interrupted mid-crawl."""
        return list(self._partial_results)

    # ── Public API ────────────────────────────────────────────────────────────

    async def scrape_single(self, url: str) -> list[dict]:
        """Scrape a single page and return its data as a one-element list."""
        print(f"\n[Crawler] Single-page mode -> {url}")
        self._partial_results = []
        await self._init_session(url)
        await self._ensure_http_session()
        await self._prefetch_robots(url)

        if self.robots and not self.robots.is_allowed(url):
            tqdm.write(f"[Crawler] Blocked by robots.txt -> {url}")
            data = self._create_failed_page(url, "Blocked by robots.txt")
            return [data]

        with tqdm(total=1, desc="Scraping", unit="page",
                  dynamic_ncols=True, colour="cyan") as pbar:
            data = await self._scrape_page(url, depth=0)
            pbar.update(1)

        if not data:
            data = self._create_failed_page(url, "Failed to scrape page (WAF block or exception)")
        elif self.pipeline_manager:
            data = self.pipeline_manager.process_item(data)
            
        if not data:
            return []

        self._partial_results = [data]
        await self._close_http_session()
        await self.finalize_session()
        print("[Crawler] Done. Extracted data from 1 page.")
        return [data]

    async def scrape_site(self, start_url: str) -> list[dict]:
        """
        BFS crawl from start_url, respecting depth and page-count limits.

        When max_pages is None the crawler runs until the BFS queue is fully
        exhausted (unlimited mode — crawls the entire reachable site).
        When concurrency > 1, up to N pages are scraped simultaneously using
        asyncio.gather. The per-domain asyncio.Lock in RobotsHandler ensures
        crawl-delay is still respected even for concurrent same-domain requests.
        """
        unlimited = self.max_pages is None
        page_limit = self.max_pages if not unlimited else float("inf")

        limit_label = "∞ (full site)" if unlimited else str(self.max_pages)
        print(f"\n[Crawler] Site crawl mode -> {start_url}")
        self._partial_results = []
        await self._init_session(start_url)
        await self._ensure_http_session()
        print(
            f"[Crawler] Limits: max_depth={self.max_depth}, "
            f"max_pages={limit_label}, concurrency={self.concurrency}"
        )
        if unlimited:
            print("[Crawler] ♾  Unlimited mode — crawling until every reachable page is visited.")

        origin = urlparse(start_url).netloc
        visited: set[str] = set()
        queued: set[str] = {start_url}
        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        results: list[dict] = []

        await self._prefetch_robots(start_url)

        # ETA tracking
        crawl_start = time.monotonic()
        page_times: list[float] = []   # seconds per page (rolling)

        def _fmt_eta(queued_count: int) -> str:
            """Return a human-readable ETA string based on recent page timings."""
            if not page_times:
                return "ETA: calculating..."
            avg = sum(page_times[-20:]) / len(page_times[-20:])  # last 20 pages
            remaining = queued_count
            if unlimited:
                # In unlimited mode we can't know total; show per-page rate instead
                rate = len(results) / (time.monotonic() - crawl_start) if results else 0
                return f"{rate:.2f} pg/s | {queued_count} queued"
            else:
                eta_secs = avg * remaining
                if eta_secs < 60:
                    return f"ETA: ~{eta_secs:.0f}s"
                elif eta_secs < 3600:
                    return f"ETA: ~{eta_secs/60:.1f}min"
                else:
                    return f"ETA: ~{eta_secs/3600:.1f}hr"

        with tqdm(
            total=None if unlimited else self.max_pages,
            desc="Crawling",
            unit="page",
            dynamic_ncols=True,
            colour="cyan",
        ) as pbar:
            while queue and len(results) < page_limit:

                batch: list[tuple[str, int]] = []

                while queue and len(batch) < self.concurrency:
                    if len(results) + len(batch) >= page_limit:
                        break

                    url, depth = queue.popleft()

                    if url in visited or depth > self.max_depth:
                        continue

                    if self.robots and not self.robots.is_allowed(url):
                        tqdm.write(f"[Crawler] Blocked by robots.txt -> {url}")
                        visited.add(url)
                        failed_data = self._create_failed_page(url, "Blocked by robots.txt")
                        results.append(failed_data)
                        self._partial_results = list(results)
                        pbar.update(1)
                        continue

                    visited.add(url)
                    batch.append((url, depth))

                if not batch:
                    break

                label = (
                    f"Scraping {len(batch)} pages"
                    if len(batch) > 1
                    else f"depth={batch[0][1]}"
                )
                pbar.set_description(label)

                batch_start = time.monotonic()
                page_data_list = await asyncio.gather(
                    *[
                        self._scrape_page(url, depth, slot=i)
                        for i, (url, depth) in enumerate(batch)
                    ],
                    return_exceptions=True,
                )
                batch_elapsed = time.monotonic() - batch_start
                per_page = batch_elapsed / max(len(batch), 1)
                page_times.extend([per_page] * len(batch))

                for (url, depth), data in zip(batch, page_data_list):
                    if isinstance(data, Exception):
                        tqdm.write(f"[Crawler] Exception on {url}: {data}")
                        failed_data = self._create_failed_page(url, f"Exception: {data}")
                        results.append(failed_data)
                        self._partial_results = list(results)
                        pbar.update(1)
                        continue
                    if not data:
                        failed_data = self._create_failed_page(url, "Scrape failed (WAF block or timeout)")
                        results.append(failed_data)
                        self._partial_results = list(results)
                        pbar.update(1)
                        continue

                    if self.pipeline_manager:
                        data = self.pipeline_manager.process_item(data)
                        if not data:
                            pbar.update(1)
                            pbar.set_postfix_str(_fmt_eta(len(queue)))
                            continue

                    results.append(data)
                    self._partial_results = list(results)
                    pbar.update(1)
                    pbar.set_postfix_str(_fmt_eta(len(queue)))

                    if depth < self.max_depth:
                        added = 0
                        for link in data.get("links", []):
                            href = link.get("url", "")
                            if (
                                link.get("type") == "internal"
                                and href
                                and href not in visited
                                and href not in queued
                                and self._url_ok_for_crawl(href, origin)
                            ):
                                queued.add(href)
                                queue.append((href, depth + 1))
                                added += 1
                                if self.endpoint_graph:
                                    self.endpoint_graph.add_edge(
                                        url, href, source="link", child_depth=depth + 1
                                    )
                                await self._prefetch_robots(href)
                        if added:
                            pbar.set_postfix_str(
                                f"{_fmt_eta(len(queue))} | +{added} urls"
                            )

        total_elapsed = time.monotonic() - crawl_start
        mins, secs = divmod(int(total_elapsed), 60)
        hrs, mins = divmod(mins, 60)
        elapsed_str = f"{hrs}h {mins}m {secs}s" if hrs else (f"{mins}m {secs}s" if mins else f"{secs}s")
        print(f"\n[Crawler] Crawl complete. Scraped {len(results)} pages in {elapsed_str}.")
        await self._close_http_session()
        await self.finalize_session()
        return results

    # ── Collectors / artifact store ───────────────────────────────────────────

    async def _init_session(self, seed_url: str) -> None:
        self._seed_url = seed_url
        target = TargetMetadata(
            seed_url=seed_url,
            allowed_domains=self.session_config.get("allowed_domains") or [],
        )
        if not target.allowed_domains:
            target.allowed_domains = [target.domain]
        self._scan = ScanMetadata(
            target=target,
            profile=self.session_config.get("profile", "scrape"),
            mode="active" if self.session_config.get("active_recon") else "scrape",
        )
        scope = CrawlScope(
            seed_url=seed_url,
            allowed_domains=target.allowed_domains,
            allow_subdomains=self.session_config.get("allow_subdomains", False),
            max_depth=self.max_depth,
            max_pages=self.max_pages,
            max_requests=self.session_config.get("max_requests"),
            exclude_patterns=self.session_config.get("exclude_patterns", []),
            include_patterns=self.session_config.get("include_patterns", []),
            origin_access=self._origin,
        )
        self.scope_manager = ScopeManager(scope)
        if self._vapt:
            self.artifact_store = ArtifactStore(self._scan)
            self.endpoint_graph = EndpointGraph(seed_url)
        else:
            self.artifact_store = None
            self.endpoint_graph = None

    def _url_ok_for_crawl(self, url: str, origin: str) -> bool:
        if self.session_config.get("deny_logout_urls") or (
            self.auth_manager and self.auth_manager.authenticated
        ):
            from auth.wall import is_logout_url
            if is_logout_url(url):
                return False
        if self.scope_manager and not self.scope_manager.scope.is_url_in_scope(url):
            return False
        if self._origin:
            parsed_host = urlparse(url).netloc.lower().split(":")[0]
            vanity = self._origin.hostname.lower()
            if parsed_host in (vanity, self._origin.origin_ip):
                if self.allow_regex and not self.allow_regex.search(url):
                    return False
                if self.deny_regex and self.deny_regex.search(url):
                    return False
                return True
        if self.same_domain_only:
            host = urlparse(url).netloc
            if host != origin:
                if not (
                    self.session_config.get("allow_subdomains")
                    and self.scope_manager
                    and self.scope_manager.scope.is_domain_allowed(url)
                ):
                    return False
        if self.allow_regex and not self.allow_regex.search(url):
            return False
        if self.deny_regex and self.deny_regex.search(url):
            return False
        return True

    async def _build_collector_ctx(self, url: str, depth: int = 0) -> CollectorContext:
        cookies: list[dict] = []
        try:
            cookies = await self.browser.get_cookies()
        except Exception:
            pass
        cfg = dict(self.session_config)
        if self._proxy_for_slot(0):
            cfg["_proxy_url"] = self._proxy_for_slot(0).server
        return CollectorContext(
            artifact_store=self.artifact_store,
            config=cfg,
            scan=self._scan,
            scope_manager=self.scope_manager,
            base_url=url,
            depth=depth,
            cookies=cookies,
        )

    async def _run_page_collectors(
        self,
        page: Page,
        response,
        url: str,
        depth: int,
        network_collector: Optional[NetworkCollector],
    ) -> None:
        if not self._vapt or not self.artifact_store or not self.collector_engine:
            return
        ctx = await self._build_collector_ctx(url, depth)
        if self.scope_manager:
            self.scope_manager.record_page_visit(url)
        await self.collector_engine.collect_page(
            ctx,
            page=page,
            response=response,
            network_collector=network_collector,
            endpoint_graph=self.endpoint_graph,
        )

    async def _collect_page(
        self,
        page: Page,
        url: str,
        response,
        depth: int,
        network_collector: Optional[NetworkCollector],
        screenshot_path: Optional[str] = None,
    ) -> dict:
        page_url = getattr(page, "url", None) or url
        fallback_html = ""
        try:
            fallback_html = await page.content()
        except Exception:
            pass
        server_hdr = ""
        if response:
            server_hdr = (response.headers or {}).get("server", "")

        if self._vapt and self.artifact_store:
            await self._run_page_collectors(page, response, url, depth, network_collector)
            return self.page_builder.from_artifacts(
                self.artifact_store,
                page_url,
                screenshot=screenshot_path,
                fallback_html=fallback_html,
                fallback_url=page_url,
            )

        return self.page_builder.from_html(
            fallback_html,
            page_url=page_url,
            base_url=url,
            server_header=server_hdr,
            screenshot=screenshot_path,
        )

    async def finalize_session(self) -> None:
        if not self._vapt or not self.artifact_store or not self._seed_url:
            return
        ctx = await self._build_collector_ctx(self._seed_url, 0)
        await self.collector_engine.collect_session(ctx)
        if self._scan:
            self._scan.pages_visited = len(self.artifact_store.page_urls())

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _prefetch_robots(self, url: str) -> None:
        """Fetch robots.txt for url's domain if not already cached."""
        if self.robots:
            await self.robots.fetch(url)

    async def _scrape_page_lightweight(
        self, url: str, depth: int = 0, slot: int = 0,
    ) -> dict | None:
        proxy_entry = self._proxy_for_slot(slot)
        proxy = proxy_entry.server if proxy_entry else None

        if self._origin:
            from utils.origin_probe import fetch_via_origin
            try:
                status, html, _title = await fetch_via_origin(
                    self._origin,
                    url,
                    timeout_sec=self.timeout / 1000.0,
                    proxy=proxy,
                    user_agent=DEFAULT_CONFIG.get("user_agent", ""),
                )
                if status in (403, 401, 503):
                    return {"status": "bot_blocked"}
                if status == 429:
                    tqdm.write(f"[Crawler] HTTP 429 on {url} (origin)")
                    return {"status": "bot_blocked"}
                if status >= 400:
                    tqdm.write(f"[Crawler] HTTP {status} → {url} (origin)")
                    return None
                return self.page_builder.from_html(
                    html, page_url=url, base_url=url,
                )
            except Exception as exc:
                tqdm.write(f"[Crawler] Origin fetch error on {url}: {exc}")
                return None

        try:
            session = await self._ensure_http_session()
            async with session.get(url, proxy=proxy) as response:
                status = response.status
                if status in (403, 401, 503):
                    return {"status": "bot_blocked"}

                if status == 429:
                    tqdm.write(f"[Crawler] HTTP 429 on {url} (lightweight)")
                    return {"status": "bot_blocked"}

                if status >= 400:
                    tqdm.write(f"[Crawler] HTTP {status} → {url} (lightweight)")
                    return None

                html = await response.text()

                class MockPage:
                    def __init__(self, url, html):
                        self.url = url
                        self._html = html

                    async def content(self):
                        return self._html

                mock_page = MockPage(url, html)
                if self._vapt and self.artifact_store:
                    await self._run_page_collectors(
                        mock_page, response, url, depth, None,
                    )
                    return self.page_builder.from_artifacts(
                        self.artifact_store,
                        url,
                        fallback_html=html,
                        fallback_url=url,
                    )
                return self.page_builder.from_html(
                    html, page_url=url, base_url=url,
                )

        except Exception as exc:
            tqdm.write(f"[Crawler] Lightweight error on {url}: {exc}")
            return None

    async def _after_goto(self, page: Page, response) -> bool:
        """Wait for JS challenges, then return True if bot/WAF is still detected."""
        await wait_for_challenge_resolution(
            page, timeout_ms=self._challenge_wait_ms,
        )
        return await self.browser.check_for_bot(page, response)

    async def _scrape_page(
        self, url: str, depth: int = 0, slot: int = 0,
    ) -> dict | None:
        """Load *url* in a per-slot browser context and extract page data."""
        return await run_page_scrape(self, url, depth, slot)

    async def _rotate_proxy(
        self, transient: bool = True, slot: int = 0,
    ) -> bool:
        """
        Mark the current proxy as failed, pick the next one, and recreate the
        browser context with the new proxy's pinned identity.

        Args:
            transient: True  → 429, timeout, soft block → cool-down queue.
                       False → hard error (connection refused) → hard failure counter.

        Returns False if the pool is exhausted AND Tor fallback is unavailable.
        """
        if not self.proxy_manager:
            return False

        async with self._proxy_lock:
            current = self._proxy_for_slot(slot)
            if current:
                self.proxy_manager.mark_failure(current, transient=transient)
                self.proxy_manager.reset_request_count(current)

            next_proxy = self.proxy_manager.get_next(exclude=current)

            if not next_proxy:
                tqdm.write("[Proxy]  ⚠  All proxies exhausted — no more proxies available.")
                return False

            self._slot_proxies[slot] = next_proxy
            await self.browser.rotate_proxy(
                next_proxy.to_patchright(),
                slot=slot,
                pinned_ua=next_proxy.pinned_ua or None,
                pinned_platform=next_proxy.pinned_platform or None,
                pinned_sec_ch_ua=next_proxy.pinned_sec_ch_ua or None,
            )
            # Re-verify auth after forced rotate when authenticated
            if self.auth_manager and self.auth_manager.authenticated:
                check = self.session_config.get("auth_check_url")
                if check:
                    ok = await self.auth_manager.verify(check)
                    if not ok:
                        tqdm.write("[Auth] Session lost after proxy rotate — attempting relogin...")
                        await self.auth_manager.login(seed_url=self._seed_url or check)
            tqdm.write(
                f"[Proxy]  Active: {next_proxy.server}  ({self.proxy_manager.status()})"
            )
            return True

    async def _voluntary_rotate(self, slot: int = 0) -> None:
        """
        Voluntarily rotate to a new proxy after the sticky session limit is hit.
        Does NOT mark the current proxy as failed (positive rotation, not a failure).
        """
        if not self.proxy_manager:
            return
        if self.session_config.get("auth_pin_proxy") or (
            self.auth_manager and self.auth_manager.authenticated
        ):
            tqdm.write("[Proxy] [Sticky] Skipped — auth session is pinned to current proxy.")
            return

        async with self._proxy_lock:
            current = self._proxy_for_slot(slot)
            if current:
                self.proxy_manager.reset_request_count(current)

            next_proxy = self.proxy_manager.get_next(exclude=current)
            if not next_proxy:
                tqdm.write("[Proxy] [Sticky]  No alternative proxy for voluntary rotation.")
                return

            self._slot_proxies[slot] = next_proxy
            await self.browser.rotate_proxy(
                next_proxy.to_patchright(),
                slot=slot,
                pinned_ua=next_proxy.pinned_ua or None,
                pinned_platform=next_proxy.pinned_platform or None,
                pinned_sec_ch_ua=next_proxy.pinned_sec_ch_ua or None,
            )
            tqdm.write(
                f"[Proxy] [Sticky]  Voluntarily rotated → {next_proxy.server}  "
                f"({self.proxy_manager.status()})"
            )

    async def _scroll_page(self, page: Page) -> None:
        """Scroll the page in steps to trigger lazy-loaded content."""
        try:
            scroll_height = await page.evaluate("document.body.scrollHeight")
            viewport_height = self.scroll_viewport
            current = 0
            steps = 0
            deadline = time.monotonic() + 30.0
            while current < scroll_height and steps < self._scroll_max_steps:
                if time.monotonic() > deadline:
                    break
                current += viewport_height
                await page.evaluate(f"window.scrollTo(0, {current})")
                await asyncio.sleep(self.scroll_delay)
                steps += 1
                scroll_height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass  # Non-fatal

    def _create_failed_page(self, url: str, error: str) -> dict:
        from datetime import datetime, timezone
        return {
            "url": url,
            "status": "failed",
            "error": error,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "title": "Failed to Scrape",
            "meta": {},
            "open_graph": {},
            "twitter_card": {},
            "structured_data": [],
            "headings": {},
            "paragraphs": [],
            "links": [],
            "images": [],
            "tables": [],
            "lists": [],
            "forms": [],
            "media": {"videos": [], "audios": [], "iframes": []},
            "code_blocks": [],
            "emails": [],
            "phone_numbers": [],
            "social_links": [],
            "word_count": 0,
        }
