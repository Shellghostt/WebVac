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
from typing import Optional
from urllib.parse import urlparse

from tqdm import tqdm
from patchright.async_api import Page
from utils.browser import BrowserManager
from extractors.extractor import Extractor
from config.config import DEFAULT_CONFIG
from utils.robots import RobotsHandler
from utils.proxy import ProxyManager, ProxyEntry
from utils.screenshot import ScreenshotModule
from core.pipeline import PipelineManager


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
    ):
        self.browser = browser
        self.extractor = Extractor(extract_css=extract_css, extract_xpath=extract_xpath)
        self.allow_regex = re.compile(allow_url_regex) if allow_url_regex else None
        self.deny_regex = re.compile(deny_url_regex) if deny_url_regex else None
        self.pipeline_manager = pipeline_manager
        self.engine = engine
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

        # Tracks the proxy currently wired into the browser context
        self._current_proxy: Optional[ProxyEntry] = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def scrape_single(self, url: str) -> list[dict]:
        """Scrape a single page and return its data as a one-element list."""
        print(f"\n[Crawler] Single-page mode -> {url}")
        await self._prefetch_robots(url)

        if self.robots and not self.robots.is_allowed(url):
            tqdm.write(f"[Crawler] Blocked by robots.txt -> {url}")
            data = self._create_failed_page(url, "Blocked by robots.txt")
            return [data]

        with tqdm(total=1, desc="Scraping", unit="page",
                  dynamic_ncols=True, colour="cyan") as pbar:
            data = await self._scrape_page(url)
            pbar.update(1)

        if not data:
            data = self._create_failed_page(url, "Failed to scrape page (WAF block or exception)")
        elif self.pipeline_manager:
            data = self.pipeline_manager.process_item(data)
            
        if not data:
            return []

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
        print(
            f"[Crawler] Limits: max_depth={self.max_depth}, "
            f"max_pages={limit_label}, concurrency={self.concurrency}"
        )
        if unlimited:
            print("[Crawler] ♾  Unlimited mode — crawling until every reachable page is visited.")

        origin = urlparse(start_url).netloc
        visited: set[str] = set()
        queued: set[str] = {start_url}   # pre-dedup: tracks what's already in queue
        results: list[dict] = []

        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
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

                # ── Build a batch of up to `concurrency` valid URLs ───────────
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
                        pbar.update(1)
                        continue

                    visited.add(url)
                    batch.append((url, depth))

                if not batch:
                    break

                # ── Scrape batch concurrently ─────────────────────────────────
                label = (
                    f"Scraping {len(batch)} pages"
                    if len(batch) > 1
                    else f"depth={batch[0][1]}"
                )
                pbar.set_description(label)

                batch_start = time.monotonic()
                page_data_list = await asyncio.gather(
                    *[self._scrape_page(url) for url, _ in batch],
                    return_exceptions=True,
                )
                batch_elapsed = time.monotonic() - batch_start
                per_page = batch_elapsed / max(len(batch), 1)
                page_times.extend([per_page] * len(batch))

                # ── Process results & enqueue new links ───────────────────────
                for (url, depth), data in zip(batch, page_data_list):
                    if isinstance(data, Exception):
                        tqdm.write(f"[Crawler] Exception on {url}: {data}")
                        failed_data = self._create_failed_page(url, f"Exception: {data}")
                        results.append(failed_data)
                        pbar.update(1)
                        continue
                    if not data:
                        failed_data = self._create_failed_page(url, "Scrape failed (WAF block or timeout)")
                        results.append(failed_data)
                        pbar.update(1)
                        continue

                    if self.pipeline_manager:
                        data = self.pipeline_manager.process_item(data)
                        if not data:
                            pbar.update(1)
                            pbar.set_postfix_str(_fmt_eta(len(queue)))
                            continue

                    results.append(data)
                    pbar.update(1)
                    pbar.set_postfix_str(_fmt_eta(len(queue)))

                    if depth < self.max_depth:
                        for link in data.get("links", []):
                            href = link["url"]
                            if (
                                link["type"] == "internal"
                                and href not in visited
                                and href not in queued
                                and (
                                    not self.same_domain_only
                                    or urlparse(href).netloc == origin
                                )
                            ):
                                if self.allow_regex and not self.allow_regex.search(href):
                                    continue
                                if self.deny_regex and self.deny_regex.search(href):
                                    continue

                                queued.add(href)
                                queue.append((href, depth + 1))
                                await self._prefetch_robots(href)

        total_elapsed = time.monotonic() - crawl_start
        mins, secs = divmod(int(total_elapsed), 60)
        hrs, mins = divmod(mins, 60)
        elapsed_str = f"{hrs}h {mins}m {secs}s" if hrs else (f"{mins}m {secs}s" if mins else f"{secs}s")
        print(f"\n[Crawler] Crawl complete. Scraped {len(results)} pages in {elapsed_str}.")
        return results

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _prefetch_robots(self, url: str) -> None:
        """Fetch robots.txt for url's domain if not already cached."""
        if self.robots:
            await self.robots.fetch(url)

    async def _scrape_page_lightweight(self, url: str) -> dict | None:
        proxy = self._current_proxy.server if self._current_proxy else None
        
        timeout_obj = aiohttp.ClientTimeout(total=self.timeout / 1000.0)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, proxy=proxy, timeout=timeout_obj) as response:
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
                    server_hdr = response.headers.get("server", "")
                    
                    data = await self.extractor.extract(mock_page, url, server_header=server_hdr)
                    return data
                    
        except Exception as exc:
            tqdm.write(f"[Crawler] Lightweight error on {url}: {exc}")
            return {"status": "bot_blocked"}

    async def _scrape_page(self, url: str) -> dict | None:
        """
        Load *url* in a fresh Playwright/Patchright page, extract all data.

        Each call owns its Page so proxy rotation (which recreates the context)
        never invalidates a shared object.

        Retry logic:
          - Bot/CAPTCHA detected + primary engine   → switch to Patchright stealth,
            screenshot the blocked page, retry URL once for free.
          - Bot/CAPTCHA detected + Patchright engine → last-resort evasion sequence:
              a. Exponential jitter backoff (15–60 s).
              b. Proxy rotation (if pool available) → fresh browser context + identity.
              c. Human warmup on root domain (visits homepage, moves mouse, scrolls).
              d. Final retry with Google referrer header injected.
          - HTTP 429  → rotate proxy (if pool available) + exponential back-off,
                        retry up to max_retries.
          - HTTP 4xx  → give up immediately (not a transient error).
          - Exception → retry with same proxy up to max_retries (flaky pages).
        """
        # Polite delay before first attempt (robots crawl-delay or random floor)
        fallback = random.uniform(self.delay_min, self.delay_max)
        if self.robots:
            await self.robots.wait_if_needed(url, fallback_delay=fallback)
        else:
            await asyncio.sleep(fallback)

        if getattr(self, "engine", "dynamic") == "lightweight":
            data = await self._scrape_page_lightweight(url)
            if data is not None and data.get("status") != "bot_blocked":
                return data
            elif data and data.get("status") == "bot_blocked":
                tqdm.write(f"[Crawler] Bot block detected on {url} with lightweight engine. Falling back to dynamic.")
            else:
                return None

        # One free stealth-switch retry (doesn't count against max_retries)
        _stealth_switched = False

        for attempt in range(self.max_retries + 1):
            page = await self.browser.new_page()
            try:
                response = await page.goto(
                    url, wait_until=self.wait_until, timeout=self.timeout
                )
                status = response.status if response else 200

                # ── Bot / CAPTCHA detection ───────────────────────────────────
                bot_detected = await self.browser.check_and_maybe_switch(
                    page, response
                )
                if bot_detected:
                    # Capture a screenshot of the blocked page
                    screenshot_path = None
                    if self.screenshot_module:
                        screenshot_path = await self.screenshot_module.capture_forced(
                            page, url
                        )

                    await page.close()

                    if not _stealth_switched and self.browser.engine == "patchright":
                        # We just switched engines — retry this URL once for free
                        _stealth_switched = True
                        tqdm.write(
                            f"[Crawler] 🔄 Retrying {url} with Patchright stealth..."
                        )
                        page2 = await self.browser.new_page()
                        try:
                            response2 = await page2.goto(
                                url, wait_until=self.wait_until, timeout=self.timeout
                            )
                            status2 = response2.status if response2 else 200
                            if status2 >= 400:
                                tqdm.write(f"[Crawler] HTTP {status2} → {url} (after stealth retry)")
                                await page2.close()
                                return None
                            await page2.wait_for_timeout(self.spa_delay)
                            await self._scroll_page(page2)
                            server_hdr = ""
                            if response2:
                                server_hdr = (response2.headers or {}).get("server", "")
                            data = await self.extractor.extract(page2, url, server_header=server_hdr)
                            if screenshot_path:
                                data["screenshot"] = screenshot_path
                            await page2.close()
                            if self.proxy_manager and self._current_proxy:
                                self.proxy_manager.mark_success(self._current_proxy)
                            return data
                        except Exception as exc2:
                            await page2.close()
                            tqdm.write(f"[Crawler] ✗ Stealth retry failed on {url}: {exc2}")
                            return None
                    else:
                        # ── Last-resort evasion sequence ─────────────────────
                        # Even Patchright is detected. Try progressively harder
                        # evasion before giving up entirely.
                        tqdm.write(
                            f"[Crawler] Bot block persists on {url} with Patchright. "
                            f"Running last-resort evasion sequence..."
                        )

                        # Step 1: Jitter backoff — random long sleep so we don't
                        #         hammer the server and look like a retry bot.
                        jitter = random.uniform(15.0, 60.0)
                        tqdm.write(f"[Crawler] [Evasion] Backing off {jitter:.0f}s...")
                        await asyncio.sleep(jitter)

                        # Step 2: Rotate proxy (if available) — fresh IP + identity
                        if self.proxy_manager:
                            rotated = await self._rotate_proxy()
                            if rotated:
                                tqdm.write("[Crawler] [Evasion] Proxy rotated.")
                            else:
                                tqdm.write("[Crawler] [Evasion] No more proxies to rotate.")

                        # Step 3: Human warmup — visit root domain first to build
                        #         cookies and navigation history before the target.
                        try:
                            await self.browser.human_warmup(url)
                        except Exception as warmup_err:
                            tqdm.write(f"[Crawler] [Evasion] Warmup error (non-fatal): {warmup_err}")

                        # Short breathe after warmup
                        await asyncio.sleep(random.uniform(2.0, 5.0))

                        # Step 4: Final retry — inject a Google referrer so the
                        #         server thinks we arrived from a search result.
                        page3 = await self.browser.new_page()
                        try:
                            from urllib.parse import urlparse, quote
                            domain = urlparse(url).netloc
                            google_referrer = (
                                f"https://www.google.com/search?q={quote(domain)}"
                            )
                            # Set referrer via route interception on the first request
                            async def _inject_referrer(route, request):
                                headers = {**request.headers, "referer": google_referrer}
                                await route.continue_(headers=headers)

                            await page3.route("**/*", _inject_referrer)
                            response3 = await page3.goto(
                                url, wait_until=self.wait_until, timeout=self.timeout
                            )
                            # Unroute immediately after load
                            await page3.unroute("**/*")

                            status3 = response3.status if response3 else 200
                            if status3 >= 400:
                                tqdm.write(
                                    f"[Crawler] [Evasion] HTTP {status3} on final attempt → {url}"
                                )
                                await page3.close()
                                return None

                            # Check once more for bot-block after evasion
                            still_blocked = await self.browser.check_and_maybe_switch(
                                page3, response3
                            )
                            if still_blocked:
                                tqdm.write(
                                    f"[Crawler] [Evasion] All evasion steps exhausted for {url}. "
                                    f"Skipping."
                                )
                                await page3.close()
                                return None

                            # Evasion succeeded!
                            tqdm.write(f"[Crawler] [Evasion] Success after evasion sequence: {url}")
                            await page3.wait_for_timeout(self.spa_delay)
                            await self._scroll_page(page3)
                            server_hdr3 = ""
                            if response3:
                                server_hdr3 = (response3.headers or {}).get("server", "")
                            data = await self.extractor.extract(
                                page3, url, server_header=server_hdr3
                            )
                            if screenshot_path:
                                data["screenshot"] = screenshot_path
                            await page3.close()
                            return data

                        except Exception as evasion_err:
                            tqdm.write(
                                f"[Crawler] [Evasion] Final retry failed for {url}: {evasion_err}"
                            )
                            try:
                                await page3.close()
                            except Exception:
                                pass
                            return None

                # ── Rate-limited ──────────────────────────────────────────────
                if status == 429:
                    await page.close()
                    tqdm.write(
                        f"[Crawler] ⚠  HTTP 429 on {url} "
                        f"(attempt {attempt+1}/{self.max_retries+1})"
                    )
                    if self.proxy_manager:
                        if not await self._rotate_proxy():
                            return None
                    else:
                        backoff = min(60.0, 5.0 * (2 ** attempt))
                        tqdm.write(f"[Crawler] Backing off {backoff:.0f}s (no proxy pool)...")
                        await asyncio.sleep(backoff)

                    if attempt < self.max_retries:
                        continue
                    return None

                # ── Permanent client errors ───────────────────────────────────
                if status >= 400:
                    tqdm.write(f"[Crawler] HTTP {status} → {url}")
                    await page.close()
                    return None

                # ── CAPTCHA screenshot on clean page (edge case) ──────────────
                screenshot_path = None
                if self.screenshot_module:
                    screenshot_path = await self.screenshot_module.capture_if_blocked(
                        page, url, response
                    )

                # ── Success ───────────────────────────────────────────────────
                await page.wait_for_timeout(self.spa_delay)   # let JS-heavy SPAs settle
                await self._scroll_page(page)

                # Extract server header for default creds check
                server_hdr = ""
                if response:
                    server_hdr = (response.headers or {}).get("server", "")

                data = await self.extractor.extract(page, url, server_header=server_hdr)
                if screenshot_path:
                    data["screenshot"] = screenshot_path

                await page.close()

                if self.proxy_manager and self._current_proxy:
                    self.proxy_manager.mark_success(self._current_proxy)

                return data

            except Exception as exc:
                await page.close()
                tqdm.write(
                    f"[Crawler] ✗ Error on {url} "
                    f"(attempt {attempt+1}/{self.max_retries+1}): {exc}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 ** attempt)   # gentle back-off
                    continue
                return None

        return None  # exhausted all attempts

    async def _rotate_proxy(self) -> bool:
        """
        Mark the current proxy as failed, pick the next one, and recreate the
        browser context. Returns False if the pool is exhausted.
        """
        if not self.proxy_manager:
            return False

        if self._current_proxy:
            self.proxy_manager.mark_failure(self._current_proxy)

        next_proxy = self.proxy_manager.get_next()
        if not next_proxy:
            return False

        self._current_proxy = next_proxy
        await self.browser.rotate_proxy(next_proxy.to_playwright())
        tqdm.write(
            f"[Proxy] Active: {next_proxy.server}  ({self.proxy_manager.status()})"
        )
        return True

    async def _scroll_page(self, page: Page) -> None:
        """Scroll the page in steps to trigger lazy-loaded content."""
        try:
            scroll_height = await page.evaluate("document.body.scrollHeight")
            viewport_height = self.scroll_viewport
            current = 0
            while current < scroll_height:
                current += viewport_height
                await page.evaluate(f"window.scrollTo(0, {current})")
                await asyncio.sleep(self.scroll_delay)
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
