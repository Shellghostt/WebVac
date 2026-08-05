"""
wall.py — Detect login/auth walls mid-crawl and apply abort|skip|relogin policy.

Auth walls are distinct from bot/WAF blocks: they must not trigger bot retries
or proxy rotation.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Strong login/register URL shapes (Amazon /ap/signin, /login, /register, …)
LOGIN_PATH_RE = re.compile(
    r"/(?:"
    r"ap/(?:signin|sign-in|login|register|signup|sign-up)|"
    r"login|signin|sign-in|log-in|"
    r"signup|sign-up|register|registration|"
    r"auth/(?:login|signin|sign-in|signup|register)|"
    r"account/(?:login|signin|sign-in|register)|"
    r"session/new"
    r")(?:/|$|\?)",
    re.I,
)
LOGIN_TITLE_RE = re.compile(
    r"\b(sign\s*in|log\s*in|login|sign\s*up|register|create\s*account|"
    r"authenticate|authentication)\b",
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
    Heuristic: page looks like a login/register wall rather than content.

    Known login URL paths are always treated as walls (even when the page
    embeds CAPTCHA widgets that would otherwise look like a bot block).
    """
    path = (urlparse(url).path or "/").lower()
    if seed_login_path and path.rstrip("/") == seed_login_path.rstrip("/"):
        return True
    # Strong path match — do not require password/title confirmation.
    if LOGIN_PATH_RE.search(path):
        return True
    # Soft match: password form + login-ish title on any path (e.g. modal walls)
    if html and PASSWORD_FIELD_RE.search(html) and LOGIN_TITLE_RE.search(title or ""):
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
    # Only fetch HTML when path is ambiguous (soft match needs it).
    path = (urlparse(url).path or "/").lower()
    seed_path = ""
    if seed_login_url:
        seed_path = urlparse(seed_login_url).path.lower().rstrip("/")
    if seed_path and path.rstrip("/") == seed_path:
        return True
    if LOGIN_PATH_RE.search(path):
        return True
    try:
        html = await page.content()
    except Exception:
        pass
    return is_auth_wall(
        url=url, title=title or "", html=html or "", seed_login_path=seed_path,
    )


def apply_wall_policy(policy: str) -> str:
    p = (policy or "skip").lower().strip()
    if p not in ("abort", "skip", "relogin"):
        return "skip"
    return p


def make_auth_wall_record(url: str, *, policy: str = "skip") -> dict:
    """
    Lightweight page record for a skipped login/register URL.

    Distinct from status=failed so reports and crawl stats do not treat
    auth walls as scrape failures.
    """
    from datetime import datetime, timezone

    policy = apply_wall_policy(policy)
    return {
        "url": url,
        "status": "auth_wall",
        "error": f"Auth wall skipped (policy={policy})",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "title": "Auth wall (skipped)",
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
