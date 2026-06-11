"""
detection.py — Shared bot/CAPTCHA detection heuristics.

Used by both browser.py (to decide engine fallback) and screenshot.py
(to decide whether to capture a screenshot). Centralised here so both
modules stay in sync without code duplication.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page, Response

# ── Keyword databases ─────────────────────────────────────────────────────────

# Page <title> patterns (case-insensitive substring match)
BLOCKED_TITLES: list[str] = [
    "access denied",
    "403 forbidden",
    "403 error",
    "captcha",
    "bot check",
    "bot detection",
    "security check",
    "attention required",
    "just a moment",           # Cloudflare
    "verify you are human",    # Cloudflare / hCaptcha
    "ddos protection",
    "robot check",
    "are you a robot",
    "human verification",
    "blocked",
    "too many requests",
    "rate limited",
    "unusual traffic",         # Google
    "our systems have detected unusual traffic",
]

# URL substring patterns (case-insensitive)
BLOCKED_URL_KEYWORDS: list[str] = [
    "captcha",
    "/challenge",
    "/blocked",
    "recaptcha",
    "/verify",
    "bot-check",
    "bot_check",
    "security-check",
    "ddos",
]

# HTML body patterns (case-insensitive substring match)
BLOCKED_BODY_PATTERNS: list[str] = [
    "cf-challenge",             # Cloudflare challenge form id
    "__cf_chl",                 # Cloudflare challenge hidden field
    "challenge-form",           # Cloudflare
    "hcaptcha",                 # hCaptcha
    "g-recaptcha",              # Google reCAPTCHA
    "recaptcha/api.js",
    "datadome",                 # DataDome bot manager
    "datadome.co",
    "akamai bot",
    "perimeterx",               # PerimeterX
    "px-captcha",
    "shape security",
    "kasada",
    "are you human",
    "bot protection",
    "ddos-guard",
    "please enable javascript",
    "enable javascript and cookies",
    "checking your browser",    # Cloudflare "Checking your browser…"
]

# HTTP status codes that indicate blocking / rate-limiting
BLOCKED_STATUS_CODES: set[int] = {403, 429, 503}


# ── Detection function ────────────────────────────────────────────────────────

async def is_bot_detected(page, response=None) -> bool:
    """
    Return True if the current page looks like a CAPTCHA / bot-block page.

    Checks (in order of cost):
      1. HTTP response status code   (cheapest — from response object)
      2. Current URL                 (cheap — already in memory)
      3. Page <title>                (cheap — JS evaluate)
      4. Raw HTML body               (most expensive — full page content)

    Args:
        page:     A Playwright/Patchright ``Page`` object.
        response: The ``Response`` object returned by ``page.goto()``, or None.

    Returns:
        bool — True if bot-blocking is detected, False otherwise.
    """
    # 1. Status code check
    if response is not None:
        try:
            if response.status in BLOCKED_STATUS_CODES:
                return True
        except Exception:
            pass

    # 2. URL check
    try:
        current_url = page.url.lower()
        for kw in BLOCKED_URL_KEYWORDS:
            if kw in current_url:
                return True
    except Exception:
        pass

    # 3. Title check
    try:
        title = (await page.title()).lower()
        for pattern in BLOCKED_TITLES:
            if pattern in title:
                return True
    except Exception:
        pass

    # 4. Body check (only if cheaper checks passed)
    try:
        body = (await page.content()).lower()
        for pattern in BLOCKED_BODY_PATTERNS:
            if pattern in body:
                return True
    except Exception:
        pass

    return False


def is_bot_detected_sync(url: str, title: str, body: str, status: int | None = None) -> bool:
    """
    Synchronous variant for use in non-async contexts (e.g. post-extraction checks).

    Args:
        url:    The page URL string.
        title:  The page title string.
        body:   The full HTML body string.
        status: Optional HTTP status code integer.

    Returns:
        bool — True if bot-blocking is detected.
    """
    if status is not None and status in BLOCKED_STATUS_CODES:
        return True

    url_lower = url.lower()
    for kw in BLOCKED_URL_KEYWORDS:
        if kw in url_lower:
            return True

    title_lower = title.lower()
    for pattern in BLOCKED_TITLES:
        if pattern in title_lower:
            return True

    body_lower = body.lower()
    for pattern in BLOCKED_BODY_PATTERNS:
        if pattern in body_lower:
            return True

    return False
