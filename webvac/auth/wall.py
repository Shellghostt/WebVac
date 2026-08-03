"""
wall.py — Detect login/auth walls mid-crawl and apply abort|skip|relogin policy.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

LOGIN_PATH_RE = re.compile(
    r"/(login|signin|sign-in|log-in|auth/login|account/login|session/new)(/|$|\?)",
    re.I,
)
LOGIN_TITLE_RE = re.compile(
    r"\b(sign\s*in|log\s*in|login|authenticate|authentication)\b",
    re.I,
)
PASSWORD_FIELD_RE = re.compile(
    r'<input[^>]+type=["\']password["\']',
    re.I,
)
LOGOUT_PATH_RE = re.compile(
    r"/(logout|signout|sign-out|log-out|auth/logout)(/|$|\?)",
    re.I,
)


def is_logout_url(url: str) -> bool:
    path = urlparse(url).path or "/"
    return bool(LOGOUT_PATH_RE.search(path))


def is_auth_wall(
    *,
    url: str = "",
    title: str = "",
    html: str = "",
    seed_login_path: str = "",
) -> bool:
    """
    Heuristic: page looks like a login wall rather than authenticated content.
    """
    path = (urlparse(url).path or "/").lower()
    if seed_login_path and path.rstrip("/") == seed_login_path.rstrip("/"):
        return True
    if LOGIN_PATH_RE.search(path):
        # Confirm with password field or title when possible
        if html and PASSWORD_FIELD_RE.search(html):
            return True
        if title and LOGIN_TITLE_RE.search(title):
            return True
        if not html and not title:
            return True
    if html and PASSWORD_FIELD_RE.search(html) and LOGIN_TITLE_RE.search(title or ""):
        return True
    if title and LOGIN_TITLE_RE.search(title) and html and PASSWORD_FIELD_RE.search(html):
        return True
    return False


async def is_auth_wall_page(page, *, seed_login_url: str = "") -> bool:
    """Async check against a live Patchright page."""
    url = getattr(page, "url", "") or ""
    title = ""
    html = ""
    try:
        title = await page.title()
    except Exception:
        try:
            title = await page.evaluate("document.title")
        except Exception:
            pass
    try:
        html = await page.content()
    except Exception:
        pass
    seed_path = ""
    if seed_login_url:
        seed_path = urlparse(seed_login_url).path.lower().rstrip("/")
    return is_auth_wall(url=url, title=title or "", html=html or "", seed_login_path=seed_path)


def apply_wall_policy(policy: str) -> str:
    p = (policy or "skip").lower().strip()
    if p not in ("abort", "skip", "relogin"):
        return "skip"
    return p
