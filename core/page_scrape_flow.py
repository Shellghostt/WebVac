"""
Dynamic page scrape flow — extracted from Crawler for maintainability.

Each concurrent worker uses its own browser context slot so proxy rotation
never invalidates pages owned by another worker.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Optional
from urllib.parse import quote, urlparse

from tqdm import tqdm

from collectors.network.collector import NetworkCollector

if TYPE_CHECKING:
    from core.crawler import Crawler


async def run_page_scrape(
    crawler: "Crawler", url: str, depth: int = 0, slot: int = 0,
) -> dict | None:
    """Load *url* in a per-slot browser context and extract page data."""
    fallback = random.uniform(crawler.delay_min, crawler.delay_max)
    if crawler.robots:
        await crawler.robots.wait_if_needed(url, fallback_delay=fallback)
    else:
        await asyncio.sleep(fallback)

    if getattr(crawler, "engine", "dynamic") == "lightweight":
        data = await crawler._scrape_page_lightweight(url, depth=depth, slot=slot)
        if data is not None and data.get("status") != "bot_blocked":
            return data
        if data and data.get("status") == "bot_blocked":
            tqdm.write(
                f"[Crawler] Bot block on {url} (lightweight) — falling back to dynamic."
            )
        else:
            return None

    stealth_switched = False
    proxy_entry = crawler._proxy_for_slot(slot)

    for attempt in range(crawler.max_retries + 1):
        page = None
        try:
            page = await crawler.browser.new_page(slot=slot)
            network_collector: Optional[NetworkCollector] = None
            if crawler._vapt and crawler.session_config.get("collectors", {}).get("network"):
                network_collector = NetworkCollector()
                network_collector.attach(page, page_url=url)

            page_start = time.monotonic()
            response = await page.goto(
                url, wait_until=crawler.wait_until, timeout=crawler.timeout,
            )
            status = response.status if response else 200

            bot_detected = await crawler._after_goto(page, response)
            if bot_detected:
                if crawler.proxy_manager and proxy_entry:
                    crawler.proxy_manager.mark_failure(proxy_entry, transient=True)

                screenshot_path = None
                if crawler.screenshot_module:
                    screenshot_path = await crawler.screenshot_module.capture_forced(
                        page, url,
                    )
                await page.close()

                if not stealth_switched:
                    stealth_switched = True
                    tqdm.write(f"[Crawler] Retrying {url} after challenge wait...")
                    page2 = await crawler.browser.new_page(slot=slot)
                    net2: Optional[NetworkCollector] = None
                    if crawler._vapt and crawler.session_config.get("collectors", {}).get("network"):
                        net2 = NetworkCollector()
                        net2.attach(page2, page_url=url)
                    try:
                        response2 = await page2.goto(
                            url, wait_until=crawler.wait_until, timeout=crawler.timeout,
                        )
                        status2 = response2.status if response2 else 200
                        if status2 >= 400:
                            tqdm.write(f"[Crawler] HTTP {status2} → {url} (after retry)")
                            await page2.close()
                            return None
                        if await crawler._after_goto(page2, response2):
                            await page2.close()
                            if await crawler._try_cf_hero_fallback(url):
                                continue
                            tqdm.write(f"[Crawler] Still blocked after retry → {url}")
                            return None
                        await page2.wait_for_timeout(crawler.spa_delay)
                        await crawler._scroll_page(page2)
                        data = await crawler._collect_page(
                            page2, url, response2, depth, net2,
                            screenshot_path=screenshot_path,
                        )
                        await page2.close()
                        if crawler.proxy_manager and proxy_entry:
                            crawler.proxy_manager.mark_success(proxy_entry)
                        return data
                    except Exception as exc2:
                        await page2.close()
                        tqdm.write(f"[Crawler] Stealth retry failed on {url}: {exc2}")
                        return None

                if await crawler._try_cf_hero_fallback(url):
                    continue

                tqdm.write(
                    f"[Crawler] Bot block persists on {url}. Running evasion sequence..."
                )
                jitter = random.uniform(15.0, 60.0)
                tqdm.write(f"[Crawler] [Evasion] Backing off {jitter:.0f}s...")
                await asyncio.sleep(jitter)

                if crawler.proxy_manager:
                    rotated = await crawler._rotate_proxy(slot=slot)
                    proxy_entry = crawler._proxy_for_slot(slot)
                    if rotated:
                        tqdm.write("[Crawler] [Evasion] Proxy rotated.")
                    else:
                        tqdm.write("[Crawler] [Evasion] No more proxies to rotate.")

                try:
                    await crawler.browser.human_warmup(url)
                except Exception as warmup_err:
                    tqdm.write(f"[Crawler] [Evasion] Warmup error (non-fatal): {warmup_err}")

                await asyncio.sleep(random.uniform(2.0, 5.0))

                page3 = await crawler.browser.new_page(slot=slot)
                try:
                    domain = urlparse(url).netloc
                    google_referrer = f"https://www.google.com/search?q={quote(domain)}"
                    response3 = await page3.goto(
                        url,
                        wait_until=crawler.wait_until,
                        timeout=crawler.timeout,
                        referer=google_referrer,
                    )
                    status3 = response3.status if response3 else 200
                    if status3 >= 400:
                        tqdm.write(
                            f"[Crawler] [Evasion] HTTP {status3} on final attempt → {url}"
                        )
                        await page3.close()
                        return None

                    still_blocked = await crawler._after_goto(page3, response3)
                    if still_blocked:
                        tqdm.write(
                            f"[Crawler] [Evasion] Automated evasion exhausted for {url}."
                        )
                        await page3.close()

                        if not crawler.captcha_prompt_enabled:
                            tqdm.write(
                                f"[Crawler] Skipping {url} (--no-captcha-prompt is set)."
                            )
                            return None

                        proxy_dict = proxy_entry.to_patchright() if proxy_entry else None
                        solved = await crawler.browser.prompt_captcha_solve(url, proxy=proxy_dict)
                        if not solved:
                            tqdm.write(
                                f"[Crawler] Manual CAPTCHA session failed for {url}. Skipping."
                            )
                            return None

                        page4 = await crawler.browser.new_page(slot=slot)
                        try:
                            response4 = await page4.goto(
                                url,
                                wait_until=crawler.wait_until,
                                timeout=crawler.timeout,
                            )
                            if await crawler._after_goto(page4, response4):
                                tqdm.write(
                                    f"[Crawler] Still blocked after manual CAPTCHA on {url}."
                                )
                                await page4.close()
                                return None
                            await page4.wait_for_timeout(crawler.spa_delay)
                            await crawler._scroll_page(page4)
                            data = await crawler._collect_page(
                                page4, url, response4, depth, None,
                                screenshot_path=screenshot_path,
                            )
                            await page4.close()
                            tqdm.write(
                                f"[Crawler] Scraped {url} after manual CAPTCHA solve."
                            )
                            return data
                        except Exception as post_err:
                            tqdm.write(
                                f"[Crawler] Post-solve retry failed for {url}: {post_err}"
                            )
                            try:
                                await page4.close()
                            except Exception:
                                pass
                            return None

                    tqdm.write(f"[Crawler] [Evasion] Success: {url}")
                    await page3.wait_for_timeout(crawler.spa_delay)
                    await crawler._scroll_page(page3)
                    data = await crawler._collect_page(
                        page3, url, response3, depth, None,
                        screenshot_path=screenshot_path,
                    )
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

            if status == 429:
                await page.close()
                tqdm.write(
                    f"[Crawler] HTTP 429 on {url} "
                    f"(attempt {attempt + 1}/{crawler.max_retries + 1})"
                )
                if crawler.proxy_manager:
                    if not await crawler._rotate_proxy(slot=slot):
                        return None
                    proxy_entry = crawler._proxy_for_slot(slot)
                else:
                    backoff = min(60.0, 5.0 * (2 ** attempt))
                    tqdm.write(f"[Crawler] Backing off {backoff:.0f}s (no proxy pool)...")
                    await asyncio.sleep(backoff)
                if attempt < crawler.max_retries:
                    continue
                return None

            if status >= 400:
                tqdm.write(f"[Crawler] HTTP {status} → {url}")
                await page.close()
                return None

            screenshot_path = None
            if crawler.screenshot_module:
                screenshot_path = await crawler.screenshot_module.capture_if_blocked(
                    page, url, response,
                )

            await page.wait_for_timeout(crawler.spa_delay)
            await crawler._scroll_page(page)
            data = await crawler._collect_page(
                page, url, response, depth, network_collector,
                screenshot_path=screenshot_path,
            )
            await page.close()

            if crawler.proxy_manager and proxy_entry:
                crawler.proxy_manager.mark_success(proxy_entry)
                elapsed_ms = (time.monotonic() - page_start) * 1000
                crawler.proxy_manager.update_latency(proxy_entry, elapsed_ms)
                if crawler.sticky_requests > 0:
                    count = crawler.proxy_manager.increment_request_count(proxy_entry)
                    if count >= crawler.sticky_requests:
                        tqdm.write(
                            f"[Proxy] [Sticky] {proxy_entry.server} reached "
                            f"{count} request(s). Rotating..."
                        )
                        await crawler._voluntary_rotate(slot=slot)
                        proxy_entry = crawler._proxy_for_slot(slot)

            return data

        except Exception as exc:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            tqdm.write(
                f"[Crawler] Error on {url} "
                f"(attempt {attempt + 1}/{crawler.max_retries + 1}): {exc}"
            )
            exc_name = type(exc).__name__.lower()
            if crawler.proxy_manager and (
                "timeout" in exc_name or "timeout" in str(exc).lower()
            ):
                await crawler._rotate_proxy(transient=True, slot=slot)
                proxy_entry = crawler._proxy_for_slot(slot)
            if attempt < crawler.max_retries:
                await asyncio.sleep(1.5 ** attempt)
                continue
            return None

    return None
