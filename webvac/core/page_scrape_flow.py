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

from webvac.utils.network_listener import NetworkListener

if TYPE_CHECKING:
    from webvac.core.crawler import Crawler


def _network_debug_enabled(crawler: "Crawler") -> bool:
    return bool(crawler.session_config.get("network_debug", True))


def _attach_network(crawler: "Crawler", page, url: str) -> Optional[NetworkListener]:
    """Attach network listener for scrape diagnosis."""
    if not _network_debug_enabled(crawler):
        return None
    nc = NetworkListener()
    nc.attach(page, page_url=url)
    return nc


async def _page_is_auth_wall(crawler: "Crawler", page) -> bool:
    """True when the live page is a login/register wall (not a bot/WAF block)."""
    from webvac.auth.wall import is_auth_wall_page

    if crawler.auth_manager:
        return await crawler.auth_manager.is_auth_wall(page)
    return await is_auth_wall_page(page)


async def _handle_auth_wall(
    crawler: "Crawler",
    page,
    url: str,
    *,
    network_collector: Optional[NetworkListener],
    response=None,
) -> tuple[str, dict]:
    """
    Apply on_auth_wall policy. Does not mark proxies failed or start bot retries.

    Returns:
        (outcome, record) where outcome is abort|skip|relogin and record is an
        auth_wall page dict (for skip/abort) or empty dict (for relogin retry).
    """
    from webvac.auth.wall import apply_wall_policy, make_auth_wall_record

    policy = apply_wall_policy(crawler.session_config.get("on_auth_wall", "skip"))
    tqdm.write(f"[Auth] Auth wall at {url} — policy={policy}")
    await _flush_network(
        crawler, network_collector, url,
        reason=f"auth_wall_{policy}", response=response, page=page, force=True,
    )
    try:
        await page.close()
    except Exception:
        pass
    record = make_auth_wall_record(url, policy=policy)
    if policy == "abort":
        return "abort", record
    if policy == "relogin" and crawler.auth_manager:
        ok = await crawler.auth_manager.login(seed_url=crawler._seed_url or url)
        if ok:
            return "relogin", {}
        return "skip", record
    return "skip", record


async def _flush_network(
    crawler: "Crawler",
    nc: Optional[NetworkListener],
    url: str,
    *,
    reason: str,
    response=None,
    page=None,
    force: bool = False,
) -> None:
    """Dump network debug JSON on failure (or always when configured)."""
    if nc is None or not _network_debug_enabled(crawler):
        return
    always = bool(crawler.session_config.get("network_debug_always", False))
    if not force and not always and reason in ("ok", "success", "ok_evasion", "ok_after_captcha"):
        return
    try:
        entries = await nc.snapshot()
    except Exception:
        entries = []
    doc_status = None
    final_url = url
    try:
        if response is not None:
            doc_status = getattr(response, "status", None)
        if page is not None:
            final_url = getattr(page, "url", None) or url
    except Exception:
        pass
    from webvac.utils.network_debug import dump_network_debug, summarize_entries

    path = dump_network_debug(
        output_dir=crawler.output_dir or "scraped_data",
        debug_dir=getattr(crawler, "network_debug_dir", None),
        page_url=url,
        reason=reason,
        entries=entries,
        doc_status=doc_status,
        final_url=final_url,
    )
    if path:
        hints = ",".join(summarize_entries(entries).get("root_cause_hints") or [])
        msg = f"[Network] Debug dump → {path}"
        if hints:
            msg += f"  hints=[{hints}]"
        tqdm.write(msg)


async def _post_load_humanize(crawler: "Crawler", page) -> None:
    if bool(crawler.session_config.get("humanize_after_goto", True)):
        try:
            await crawler.browser.settle_page(page)
        except Exception:
            pass


async def _try_auto_captcha(
    crawler: "Crawler",
    page,
    url: str,
    proxy_entry=None,
) -> bool:
    """
    Detect CAPTCHA on *page*, solve via CapSolver (if configured), inject, re-check.

    Returns True when the page no longer looks bot-blocked after inject.
    """
    from webvac.captcha import solver_from_config

    mgr = solver_from_config(crawler.session_config)
    if not mgr.enabled:
        return False

    # Ensure network fingerprints were collected (attach may already have run pre-goto)
    try:
        mgr.attach_network_watcher(page)
    except Exception:
        pass

    proxy = None
    if proxy_entry is not None:
        from webvac.utils.proxy import proxy_entry_to_url
        proxy = proxy_entry_to_url(proxy_entry)
    ua = getattr(crawler.browser, "_session_ua", "") or ""

    result = await mgr.try_solve_on_page(
        page, url=url, proxy=proxy, user_agent=ua,
    )
    if not result.success:
        tqdm.write(f"[Captcha] Auto-solve failed: {result.error}")
        return False

    needs_reload = getattr(result, "_needs_reload", True)
    if needs_reload:
        try:
            await page.wait_for_timeout(2000)
            await page.reload(wait_until=crawler.wait_until, timeout=crawler.timeout)
        except Exception:
            pass
    else:
        try:
            await page.wait_for_timeout(3000)
        except Exception:
            pass

    still = await crawler._after_goto(page, None)
    if still:
        tqdm.write("[Captcha] Token injected but page still looks blocked.")
        return False
    tqdm.write("[Captcha] Auto-solve succeeded — continuing scrape.")
    return True


def _maybe_attach_captcha_watcher(crawler: "Crawler", page) -> None:
    """Start captcha network fingerprinting before navigation when CapSolver is on."""
    try:
        from webvac.captcha import solver_from_config

        mgr = solver_from_config(crawler.session_config)
        if mgr.enabled:
            mgr.attach_network_watcher(page)
    except Exception:
        pass


async def run_page_scrape(
    crawler: "Crawler", url: str, depth: int = 0, slot: int = 0,
) -> dict | None:
    """Load *url* in a per-slot browser context and extract page data."""
    from webvac.utils.consent import apply_known_consent_bypass, inject_known_consent_cookies
    from webvac.auth.wall import apply_wall_policy, is_auth_wall, make_auth_wall_record

    rewritten, bypass_note = apply_known_consent_bypass(url)
    if bypass_note:
        tqdm.write(f"[Consent] Known-site bypass applied → ?{bypass_note}")
        url = rewritten

    # Skip known login/register URLs before opening a browser (not a scrape failure).
    if is_auth_wall(url=url):
        policy = apply_wall_policy(crawler.session_config.get("on_auth_wall", "skip"))
        tqdm.write(f"[Auth] Skipping auth URL (policy={policy}) — {url}")
        if policy == "abort":
            raise RuntimeError(f"Auth wall abort at {url}")
        if policy == "relogin" and crawler.auth_manager:
            ok = await crawler.auth_manager.login(seed_url=crawler._seed_url or url)
            if ok:
                # Still an auth URL — do not scrape it as content after login.
                pass
        return make_auth_wall_record(url, policy=policy)

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
        network_collector: Optional[NetworkListener] = None
        try:
            page = await crawler.browser.new_page(slot=slot)
            network_collector = _attach_network(crawler, page, url)
            _maybe_attach_captcha_watcher(crawler, page)

            cookie_note = await inject_known_consent_cookies(page, url)
            if cookie_note:
                tqdm.write(f"[Consent] Injected known consent cookie(s): {cookie_note}")

            page_start = time.monotonic()
            # Once per host: root visit + human skim (cookies / history)
            if bool(crawler.session_config.get("humanize_warmup", True)):
                try:
                    await crawler.browser.ensure_host_warmup(url)
                except Exception as warm_exc:
                    tqdm.write(f"[Crawler] Warmup skipped (non-fatal): {warm_exc}")

            tqdm.write(f"[Crawler] Fetching  {url}")
            response = await page.goto(
                url, wait_until=crawler.wait_until, timeout=crawler.timeout,
            )
            status = response.status if response else 200
            final = getattr(page, "url", None) or url
            if final.rstrip("/") != url.rstrip("/"):
                tqdm.write(f"[Crawler] Redirected  {status}  →  {final}")
            else:
                tqdm.write(f"[Crawler] Loaded  HTTP {status}  {url}")

            # Auth walls first — never treat login/register pages as bot blocks
            # (covers soft walls / redirects onto login paths).
            try:
                if await _page_is_auth_wall(crawler, page):
                    outcome, record = await _handle_auth_wall(
                        crawler, page, url,
                        network_collector=network_collector, response=response,
                    )
                    network_collector = None
                    if outcome == "abort":
                        raise RuntimeError(f"Auth wall abort at {url}")
                    if outcome == "relogin":
                        continue
                    return record
            except RuntimeError:
                raise
            except Exception as wall_exc:
                tqdm.write(f"[Auth] Auth-wall check error: {wall_exc}")

            bot_detected = await crawler._after_goto(page, response)

            if bot_detected:
                # CapSolver (or configured provider) before closing / proxy failure marks
                if await _try_auto_captcha(crawler, page, url, proxy_entry):
                    await crawler._handle_consent(page, url)
                    await _post_load_humanize(crawler, page)
                    await page.wait_for_timeout(crawler.spa_delay)
                    await crawler._scroll_page(page)
                    data = await crawler._collect_page(
                        page, url, response, depth,
                        screenshot_path=None,
                    )
                    await _flush_network(
                        crawler, network_collector, url,
                        reason="ok_after_captcha", response=response, page=page,
                    )
                    await page.close()
                    if crawler.proxy_manager and proxy_entry:
                        crawler.proxy_manager.mark_success(proxy_entry)
                    return data

                screenshot_path = None
                if crawler.screenshot_module:
                    screenshot_path = await crawler.screenshot_module.capture_forced(
                        page, url,
                    )
                await _flush_network(
                    crawler, network_collector, url,
                    reason="bot_detected", response=response, page=page, force=True,
                )
                await page.close()
                network_collector = None

                if not stealth_switched:
                    stealth_switched = True
                    tqdm.write(f"[Crawler] Retrying {url} after challenge wait...")
                    page2 = await crawler.browser.new_page(slot=slot)
                    _maybe_attach_captcha_watcher(crawler, page2)
                    net2 = _attach_network(crawler, page2, url)
                    try:
                        await inject_known_consent_cookies(page2, url)
                        response2 = await page2.goto(
                            url, wait_until=crawler.wait_until, timeout=crawler.timeout,
                        )
                        status2 = response2.status if response2 else 200
                        if status2 >= 400:
                            tqdm.write(f"[Crawler] HTTP {status2} → {url} (after retry)")
                            await _flush_network(
                                crawler, net2, url,
                                reason=f"http_{status2}_retry", response=response2,
                                page=page2, force=True,
                            )
                            await page2.close()
                            return None
                        if await _page_is_auth_wall(crawler, page2):
                            outcome, record = await _handle_auth_wall(
                                crawler, page2, url,
                                network_collector=net2, response=response2,
                            )
                            if outcome == "abort":
                                raise RuntimeError(f"Auth wall abort at {url}")
                            return record
                        if await crawler._after_goto(page2, response2):
                            if await _try_auto_captcha(crawler, page2, url, proxy_entry):
                                await crawler._handle_consent(page2, url)
                                await _post_load_humanize(crawler, page2)
                                await page2.wait_for_timeout(crawler.spa_delay)
                                await crawler._scroll_page(page2)
                                data = await crawler._collect_page(
                                    page2, url, response2, depth,
                                    screenshot_path=screenshot_path,
                                )
                                await _flush_network(
                                    crawler, net2, url,
                                    reason="ok_after_captcha", response=response2, page=page2,
                                )
                                await page2.close()
                                if crawler.proxy_manager and proxy_entry:
                                    crawler.proxy_manager.mark_success(proxy_entry)
                                return data
                            await _flush_network(
                                crawler, net2, url,
                                reason="bot_detected_retry", response=response2,
                                page=page2, force=True,
                            )
                            await page2.close()
                            tqdm.write(f"[Crawler] Still blocked after retry → {url}")
                            return None
                        await crawler._handle_consent(page2, url)
                        await _post_load_humanize(crawler, page2)
                        await page2.wait_for_timeout(crawler.spa_delay)
                        await crawler._scroll_page(page2)
                        data = await crawler._collect_page(
                            page2, url, response2, depth,
                            screenshot_path=screenshot_path,
                        )
                        await _flush_network(
                            crawler, net2, url,
                            reason="ok", response=response2, page=page2,
                        )
                        await page2.close()
                        if crawler.proxy_manager and proxy_entry:
                            crawler.proxy_manager.mark_success(proxy_entry)
                        return data
                    except Exception as exc2:
                        await _flush_network(
                            crawler, net2, url,
                            reason=f"retry_error:{type(exc2).__name__}",
                            page=page2, force=True,
                        )
                        await page2.close()
                        tqdm.write(f"[Crawler] Stealth retry failed on {url}: {exc2}")
                        return None

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
                _maybe_attach_captcha_watcher(crawler, page3)
                net3 = _attach_network(crawler, page3, url)
                try:
                    domain = urlparse(url).netloc
                    google_referrer = f"https://www.google.com/search?q={quote(domain)}"
                    await inject_known_consent_cookies(page3, url)
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
                        await _flush_network(
                            crawler, net3, url,
                            reason=f"http_{status3}_evasion", response=response3,
                            page=page3, force=True,
                        )
                        await page3.close()
                        return None

                    if await _page_is_auth_wall(crawler, page3):
                        outcome, record = await _handle_auth_wall(
                            crawler, page3, url,
                            network_collector=net3, response=response3,
                        )
                        if outcome == "abort":
                            raise RuntimeError(f"Auth wall abort at {url}")
                        return record

                    still_blocked = await crawler._after_goto(page3, response3)
                    if still_blocked:
                        if await _try_auto_captcha(crawler, page3, url, proxy_entry):
                            tqdm.write(f"[Crawler] [Evasion] CapSolver cleared block: {url}")
                            await crawler._handle_consent(page3, url)
                            await _post_load_humanize(crawler, page3)
                            await page3.wait_for_timeout(crawler.spa_delay)
                            await crawler._scroll_page(page3)
                            data = await crawler._collect_page(
                                page3, url, response3, depth,
                                screenshot_path=screenshot_path,
                            )
                            await _flush_network(
                                crawler, net3, url,
                                reason="ok_after_captcha", response=response3, page=page3,
                            )
                            await page3.close()
                            if crawler.proxy_manager and proxy_entry:
                                crawler.proxy_manager.mark_success(proxy_entry)
                            return data

                        tqdm.write(
                            f"[Crawler] [Evasion] All automated evasion exhausted for {url}. Skipping."
                        )
                        await _flush_network(
                            crawler, net3, url,
                            reason="bot_detected_evasion", response=response3,
                            page=page3, force=True,
                        )
                        await page3.close()
                        return None

                    tqdm.write(f"[Crawler] [Evasion] Success: {url}")
                    await crawler._handle_consent(page3, url)
                    await _post_load_humanize(crawler, page3)
                    await page3.wait_for_timeout(crawler.spa_delay)
                    await crawler._scroll_page(page3)
                    data = await crawler._collect_page(
                        page3, url, response3, depth,
                        screenshot_path=screenshot_path,
                    )
                    await _flush_network(
                        crawler, net3, url,
                        reason="ok_evasion", response=response3, page=page3,
                    )
                    await page3.close()
                    return data
                except Exception as evasion_err:
                    await _flush_network(
                        crawler, net3, url,
                        reason=f"evasion_error:{type(evasion_err).__name__}",
                        page=page3, force=True,
                    )
                    tqdm.write(
                        f"[Crawler] [Evasion] Final retry failed for {url}: {evasion_err}"
                    )
                    try:
                        await page3.close()
                    except Exception:
                        pass
                    return None

            if status == 429:
                await _flush_network(
                    crawler, network_collector, url,
                    reason="http_429", response=response, page=page, force=True,
                )
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
                await _flush_network(
                    crawler, network_collector, url,
                    reason=f"http_{status}", response=response, page=page, force=True,
                )
                await page.close()
                return None

            screenshot_path = None
            if crawler.screenshot_module:
                screenshot_path = await crawler.screenshot_module.capture_if_blocked(
                    page, url, response,
                )

            await crawler._handle_consent(page, url)
            await _post_load_humanize(crawler, page)
            await page.wait_for_timeout(crawler.spa_delay)
            await crawler._scroll_page(page)
            tqdm.write(f"[Crawler] Extracting  {url}")
            data = await crawler._collect_page(
                page, url, response, depth,
                screenshot_path=screenshot_path,
            )
            await _flush_network(
                crawler, network_collector, url,
                reason="ok", response=response, page=page,
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

            elapsed = time.monotonic() - page_start
            title = ""
            if isinstance(data, dict):
                title = (data.get("title") or "").replace("\n", " ").strip()
                if len(title) > 50:
                    title = title[:47] + "..."
            tqdm.write(
                f"[Crawler] Done in {elapsed:.1f}s  "
                f"HTTP {status}  {title or '(no title)'}"
            )
            return data

        except Exception as exc:
            await _flush_network(
                crawler, network_collector, url,
                reason=f"error:{type(exc).__name__}", page=page, force=True,
            )
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            tqdm.write(
                f"[Crawler] Error on {url} "
                f"(attempt {attempt + 1}/{crawler.max_retries + 1}): {exc}"
            )
            from webvac.utils.proxy import classify_proxy_error

            kind = classify_proxy_error(exc)
            if crawler.proxy_manager and kind:
                await crawler._rotate_proxy(transient=(kind == "transient"), slot=slot)
                proxy_entry = crawler._proxy_for_slot(slot)
            if attempt < crawler.max_retries:
                await asyncio.sleep(1.5 ** attempt)
                continue
            return None

    return None
