"""
CapSolver headed captcha demo — used by ``examples/captcha_watch_demo.py``.

Solves captcha test pages with CapSolver on the backend (API key never enters the
page), then finds and clicks Check / Verify / Submit / Test so you can watch.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Optional, Sequence

from webvac.captcha.config import CaptchaSolverConfig
from webvac.captcha.manager import CaptchaSolverManager
from webvac.utils.browser import BrowserManager

# CapSolver-friendly public demos (2captcha / Cloudflare dummy keys often fail).
DEMO_URLS: dict[str, str] = {
    "v2": "https://www.google.com/recaptcha/api2/demo",
    "invisible": "https://www.google.com/recaptcha/api2/demo?invisible=true",
    "v3": "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php",
}

# Ordered: specific IDs first, then label text, then generic submits.
SUBMIT_SELECTORS: tuple[str, ...] = (
    "#recaptcha-demo-submit",
    'button#submit',
    'input#submit',
    'button[name="submit"]',
    'input[name="submit"]',
    'button:has-text("Submit")',
    'button:has-text("Check")',
    'button:has-text("Verify")',
    'button:has-text("Test")',
    'button:has-text("Continue")',
    'button:has-text("Send")',
    'button:has-text("Log in")',
    'button:has-text("Login")',
    'input[value="Submit"]',
    'input[value="Check"]',
    'input[value="Verify"]',
    'input[value="Test"]',
    'input[type="submit"]',
    'button[type="submit"]',
    '[role="button"]:has-text("Submit")',
    '[role="button"]:has-text("Verify")',
    '[role="button"]:has-text("Check")',
    '[role="button"]:has-text("Test")',
)


@dataclass
class StepResult:
    url: str
    ok: bool
    detail: str
    clicked: str = ""


def _banner(msg: str) -> None:
    print(f"\n{'=' * 64}\n  {msg}\n{'=' * 64}")


def resolve_demo_urls(
    *,
    url: Optional[str] = None,
    extra_urls: Optional[Sequence[str]] = None,
    only: Optional[str] = None,
) -> list[str]:
    """Build ordered unique URL list from CLI / interactive choices."""
    urls: list[str] = []
    if url and str(url).strip():
        urls.append(str(url).strip())
    for u in extra_urls or []:
        if u and str(u).strip():
            urls.append(str(u).strip())
    if only:
        for name in only.split(","):
            key = name.strip().lower()
            if not key:
                continue
            if key not in DEMO_URLS:
                raise SystemExit(
                    f"Unknown demo {key!r}. Choose: {', '.join(DEMO_URLS)}"
                )
            urls.append(DEMO_URLS[key])
    if not urls:
        urls = [DEMO_URLS["v2"], DEMO_URLS["invisible"], DEMO_URLS["v3"]]

    seen: set[str] = set()
    ordered: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def load_manager(
    *,
    timeout: float = 120.0,
    api_key: str = "",
) -> CaptchaSolverManager:
    data: dict = {
        "captcha_solver": "capsolver",
        "captcha_solver_enabled": True,
        "captcha_solver_retries": 1,
        "captcha_solver_timeout_sec": timeout,
    }
    if api_key:
        data["captcha_api_key"] = api_key
    cfg = CaptchaSolverConfig.from_mapping(data, load_files=True)
    if not cfg.api_key:
        raise SystemExit(
            "No CapSolver API key.\n"
            "  Put it in repo-root capsolver.key (see examples/capsolver.example.key),\n"
            "  or pass --captcha-api-key / set CAPSOLVER_API_KEY.\n"
            "  The key stays on the backend — never injected into the page."
        )
    mgr = CaptchaSolverManager(cfg)
    if not mgr.enabled:
        raise SystemExit("Captcha solver failed to enable. Run: pip install capsolver")
    print(f"[CaptchaDemo] CapSolver backend ready (key ...{cfg.api_key[-4:]})")
    return mgr


async def _pause(seconds: float, label: str) -> None:
    if seconds <= 0:
        return
    print(f"[CaptchaDemo] Pause ({label}) — {seconds:.0f}s ...")
    await asyncio.sleep(seconds)


async def _outline(page, handle) -> None:
    try:
        await page.evaluate(
            """(el) => {
              el.style.outline = '3px solid #e11d48';
              el.style.outlineOffset = '4px';
              try { el.scrollIntoView({behavior: 'smooth', block: 'center'}); } catch (e) {}
            }""",
            handle,
        )
    except Exception:
        pass


async def _highlight_click(page, selector: str) -> bool:
    loc = page.locator(selector).first
    try:
        if await loc.count() == 0:
            return False
        if not await loc.is_visible():
            return False
    except Exception:
        return False
    try:
        await loc.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        handle = await loc.element_handle()
        if handle:
            await _outline(page, handle)
    except Exception:
        pass
    await asyncio.sleep(0.85)
    await loc.click(timeout=8000)
    return True


async def find_and_click_verify(page) -> str:
    """
    Find Check / Verify / Submit / Test (and similar) and click it visibly.

    Tries CSS / text selectors first, then a DOM heuristic scan, then form.submit().
    """
    for sel in SUBMIT_SELECTORS:
        try:
            if await _highlight_click(page, sel):
                return sel
        except Exception:
            continue

    for name in ("Submit", "Check", "Verify", "Test", "Continue", "Send", "Log in", "Login"):
        try:
            loc = page.get_by_role("button", name=name)
            if await loc.count() == 0:
                loc = page.get_by_role("link", name=name)
            if await loc.count() == 0:
                continue
            first = loc.first
            if not await first.is_visible():
                continue
            await first.scroll_into_view_if_needed(timeout=5000)
            handle = await first.element_handle()
            if handle:
                await _outline(page, handle)
            await asyncio.sleep(0.85)
            await first.click(timeout=8000)
            return f'role=button name="{name}"'
        except Exception:
            continue

    try:
        clicked = await page.evaluate(
            """() => {
              const labels = /\\b(check|verify|submit|test|continue|send|login|log\\s*in|confirm)\\b/i;
              const nodes = [
                ...document.querySelectorAll(
                  'button, input[type=submit], input[type=button], [role=button], a.btn, a.button'
                ),
              ];
              const scored = [];
              for (const el of nodes) {
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                if (el.disabled) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 4 || rect.height < 4) continue;
                const t = (
                  el.innerText || el.value || el.getAttribute('aria-label')
                  || el.getAttribute('title') || el.id || el.name || ''
                ).trim();
                if (!labels.test(t)) continue;
                scored.push({ el, t, y: rect.top });
              }
              scored.sort((a, b) => a.y - b.y);
              if (!scored.length) {
                const form = document.querySelector('form');
                if (form) {
                  if (form.requestSubmit) form.requestSubmit();
                  else form.submit();
                  return 'form.submit()';
                }
                return '';
              }
              const pick = scored[0];
              pick.el.style.outline = '3px solid #e11d48';
              pick.el.style.outlineOffset = '4px';
              pick.el.click();
              return pick.t || pick.el.tagName;
            }"""
        )
        return str(clicked or "")
    except Exception:
        return ""


async def _page_looks_successful(page) -> bool:
    try:
        text = await page.evaluate(
            """() => (document.body && (document.body.innerText || '')) || ''"""
        )
    except Exception:
        return False
    lower = (text or "").lower()
    return any(
        s in lower
        for s in (
            "verification success",
            "captcha is passed",
            "captcha solved",
            "thank you",
            "success!",
            "you are verified",
        )
    )


async def run_one(
    browser: BrowserManager,
    mgr: CaptchaSolverManager,
    url: str,
    *,
    pause: float,
    settle_ms: int,
) -> StepResult:
    _banner(f"Navigate -> {url}")
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(settle_ms)
        await _pause(min(pause, 3), "page loaded — look at the captcha widget")

        print("[CaptchaDemo] Detecting captcha ...")
        print("[CaptchaDemo] Solving via CapSolver backend (key stays local) ...")
        result = await mgr.try_solve_on_page(page, url=url)
        if not result.success:
            await _pause(pause, "solve failed — inspect the page")
            return StepResult(url=url, ok=False, detail=result.error or "solve failed")

        print(
            f"[CaptchaDemo] Token injected (len={len(result.token or '')}, "
            f"task={result.task_id or '-'})"
        )
        await _pause(min(pause, 4), "token in DOM — finding Verify/Check/Submit")

        if getattr(result, "_needs_reload", False):
            print("[CaptchaDemo] Reloading after Turnstile-style inject ...")
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

        clicked = await find_and_click_verify(page)
        if clicked:
            print(f"[CaptchaDemo] Clicked: {clicked}")
        else:
            print("[CaptchaDemo] No Check/Verify/Submit/Test control found")

        await page.wait_for_timeout(2200)
        site_ok = await _page_looks_successful(page)
        if site_ok:
            print("[CaptchaDemo] Site shows SUCCESS — watch the page")
        else:
            print("[CaptchaDemo] No clear success banner; check the window")

        await _pause(pause, "result on screen")
        ok = bool(result.token) and (site_ok or bool(clicked))
        detail = (
            "passed (site success)"
            if site_ok
            else f"token injected; click={clicked or 'none'}"
        )
        return StepResult(url=url, ok=ok, detail=detail, clicked=clicked)
    except Exception as exc:
        return StepResult(url=url, ok=False, detail=f"exception: {exc}")
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def run_captcha_demo(
    *,
    urls: Sequence[str],
    pause: float = 5.0,
    settle_ms: int = 2500,
    timeout: float = 120.0,
    api_key: str = "",
    keep_open: bool = False,
    headless: bool = False,
) -> int:
    """Run CapSolver demo against ``urls`` (headed or headless). Returns exit code."""
    mode = "headless" if headless else "headed"
    mgr = load_manager(timeout=timeout, api_key=api_key)
    _banner(f"Opening Chromium ({mode})")
    print("[CaptchaDemo] CapSolver API key is backend-only (never written into the page).")
    if headless:
        print("[CaptchaDemo] Headless mode — solve + inject still run; no visible window.")

    browser = BrowserManager(headless=headless, humanize=False)
    browser.configure_humanize({"humanize": False, "humanize_warmup": False})
    await browser.start()

    results: list[StepResult] = []
    try:
        for i, url in enumerate(urls, 1):
            print(f"\n[CaptchaDemo] Case {i}/{len(urls)}")
            results.append(
                await run_one(
                    browser,
                    mgr,
                    url,
                    pause=0.0 if headless else pause,
                    settle_ms=settle_ms,
                )
            )
    finally:
        if keep_open and not headless:
            _banner("Done — browser stays open. Press Enter in this terminal to close.")
            await asyncio.to_thread(input)
        elif keep_open and headless:
            print("[CaptchaDemo] --keep-open ignored in headless mode.")
        await browser.stop()

    _banner("Summary")
    ok_n = 0
    for r in results:
        flag = "PASS" if r.ok else "FAIL"
        if r.ok:
            ok_n += 1
        print(f"  [{flag}] {r.url}\n         {r.detail}")
    print(f"\n{ok_n}/{len(results)} ok")
    return 0 if results and ok_n == len(results) else 1


async def run_captcha_demo_from_args(args: argparse.Namespace) -> int:
    """Adapter for example scripts."""
    only = getattr(args, "captcha_demo_only", None) or getattr(args, "only", None)
    extra = getattr(args, "captcha_demo_url", None) or []
    if isinstance(extra, str):
        extra = [extra]
    primary = getattr(args, "url", None)
    if isinstance(primary, list):
        extra = list(primary) + list(extra)
        primary = None

    urls = resolve_demo_urls(url=primary, extra_urls=extra, only=only)
    pause = float(
        getattr(args, "captcha_demo_pause", None)
        or getattr(args, "pause", None)
        or 5.0
    )
    settle_ms = int(
        getattr(args, "captcha_demo_settle_ms", None)
        or getattr(args, "settle_ms", None)
        or 2500
    )
    captcha_timeout = getattr(args, "captcha_timeout", None)
    if captcha_timeout is not None:
        timeout = float(captcha_timeout)
    else:
        timeout = 120.0

    api_key = str(getattr(args, "captcha_api_key", None) or "")
    keep_open = bool(
        getattr(args, "captcha_demo_keep_open", False)
        or getattr(args, "keep_open", False)
    )
    # Prefer explicit --headless; else headed when --no-headless / keep-open / default watch
    if getattr(args, "headless", None) is True:
        headless = True
    elif getattr(args, "no_headless", None) is True:
        headless = False
    elif getattr(args, "headless", None) is False:
        headless = False
    else:
        headless = False  # watch-demo default: visible window

    return await run_captcha_demo(
        urls=urls,
        pause=pause,
        settle_ms=settle_ms,
        timeout=timeout,
        api_key=api_key,
        keep_open=keep_open,
        headless=headless,
    )
