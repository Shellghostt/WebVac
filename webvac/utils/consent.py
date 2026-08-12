"""
consent.py — CMP / cookie-banner handling for crawl + scrape pages.

- Known-site URL bypasses (host-allowlisted only — never applied globally)
- Known-site consent cookies injected before navigation
- Auto-dismiss Accept buttons via popups.py on every dynamic page load
- Optional headed pause (``--pause-for-consent``) so a human can click before the page closes
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from webvac.auth.mfa import prompt_manual_challenge
from webvac.auth.popups import dismiss_popups_patchright

# Host-suffix → (query_key, query_value). Matched against netloc (case-insensitive).
# Only sites known to honor these params — do NOT invent generic bypasses.
KNOWN_CONSENT_BYPASS: tuple[tuple[str, str, str], ...] = (
    ("deloitte.com", "hidebanner", "true"),
    ("deloitte.co.uk", "hidebanner", "true"),
    ("deloitte.ca", "hidebanner", "true"),
    ("deloitte.com.au", "hidebanner", "true"),
    ("deloitte.de", "hidebanner", "true"),
    ("deloitte.fr", "hidebanner", "true"),
    ("deloitte.nl", "hidebanner", "true"),
    ("deloitte.be", "hidebanner", "true"),
    ("deloitte.ch", "hidebanner", "true"),
    ("deloitte.ie", "hidebanner", "true"),
    ("deloitte.co.za", "hidebanner", "true"),
    ("deloitte.co.jp", "hidebanner", "true"),
    ("deloitte.com.br", "hidebanner", "true"),
    ("deloitte.com.mx", "hidebanner", "true"),
    ("deloitte.com.sg", "hidebanner", "true"),
    # Stack Overflow / community: cookie notice dismissed via query on some WP installs
    # (host-scoped copies only when confirmed — skip generic cookie_notice)
)

# Host-suffix → cookie name/value. Injected before navigation when host matches.
# Google EU consent interstitial honors CONSENT=YES+ (community-verified).
_GOOGLE_CONSENT = ("CONSENT", "YES+")
_GOOGLE_HOSTS = (
    "google.com",
    "google.co.uk",
    "google.co.in",
    "google.com.au",
    "google.de",
    "google.fr",
    "google.ca",
    "google.es",
    "google.it",
    "google.nl",
    "google.be",
    "google.ch",
    "google.at",
    "google.ie",
    "google.pt",
    "google.pl",
    "google.se",
    "google.no",
    "google.dk",
    "google.fi",
    "google.br",
    "google.com.br",
    "google.com.mx",
    "google.com.ar",
    "google.co.jp",
    "google.co.kr",
    "google.com.tw",
    "google.com.hk",
    "google.com.sg",
    "google.co.nz",
    "google.co.za",
    "google.com.tr",
    "google.ru",
    "google.com.ua",
)

_YOUTUBE_HOSTS = (
    "youtube.com",
    "youtube.co.uk",
    "youtube.de",
    "youtube.fr",
    "youtube.nl",
    "youtube.es",
    "youtube.it",
    "youtube.com.br",
    "youtube.co.jp",
    "youtu.be",
    "youtube-nocookie.com",
)

KNOWN_CONSENT_COOKIES: tuple[tuple[str, str, str], ...] = (
    *[(h, *_GOOGLE_CONSENT) for h in _GOOGLE_HOSTS],
    *[(h, *_GOOGLE_CONSENT) for h in _YOUTUBE_HOSTS],
    ("blogger.com", "CONSENT", "YES+"),
    ("blogspot.com", "CONSENT", "YES+"),
    # Microsoft / Bing privacy interstitial (legacy ENFORCE_PRIVACY flag)
    ("bing.com", "ENFORCE_PRIVACY", "1"),
    ("msn.com", "ENFORCE_PRIVACY", "1"),
    # Yahoo EU consent cookie presence (GUCS often set alongside)
    ("yahoo.com", "GUCS", "1"),
    ("yahoo.co.uk", "GUCS", "1"),
    # DuckDuckGo: preference cookie to suppress some interstitial UX
    ("duckduckgo.com", "ah", "www-1"),
)


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().split("@")[-1].split(":")[0]
    except Exception:
        return ""


def _host_matches(host: str, suffix: str) -> bool:
    return bool(host) and (host == suffix or host.endswith("." + suffix))


def apply_known_consent_bypass(url: str) -> tuple[str, Optional[str]]:
    """
    If *url*'s host matches a known CMP bypass, append the query param.

    Returns ``(possibly_rewritten_url, note_or_None)``.
    Idempotent when the param is already present.
    """
    if not url:
        return url, None
    try:
        parsed = urlparse(url)
    except Exception:
        return url, None
    host = _host_of(url)
    if not host:
        return url, None

    for suffix, key, value in KNOWN_CONSENT_BYPASS:
        if not _host_matches(host, suffix):
            continue
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if q.get(key) == value:
            return url, None
        q[key] = value
        new_query = urlencode(list(q.items()))
        rewritten = urlunparse(parsed._replace(query=new_query))
        return rewritten, f"{key}={value} ({suffix})"
    return url, None


def known_consent_cookies_for_url(url: str) -> list[dict]:
    """Playwright-compatible cookie dicts to inject before navigating *url*."""
    host = _host_of(url)
    if not host:
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for suffix, name, value in KNOWN_CONSENT_COOKIES:
        if not _host_matches(host, suffix):
            continue
        key = (suffix, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "value": value,
                "domain": f".{suffix}",
                "path": "/",
            }
        )
    return out


async def inject_known_consent_cookies(page, url: str) -> Optional[str]:
    """Inject known consent cookies into the page context. Returns a short note or None."""
    cookies = known_consent_cookies_for_url(url)
    if not cookies:
        return None
    try:
        ctx = page.context
        await ctx.add_cookies(cookies)
        names = ", ".join(f"{c['name']}={c['value']}" for c in cookies)
        return names
    except Exception as exc:
        print(f"[Consent] Cookie inject failed (non-fatal): {exc}")
        return None


async def handle_page_consent(
    page,
    *,
    url: str = "",
    extra_selectors: Optional[list[str]] = None,
    dismiss: bool = True,
    pause_for_consent: bool = False,
    headless: bool = True,
    already_paused: bool = False,
) -> dict:
    """
    After navigation: auto-dismiss CMP, optionally pause in headed mode.

    Returns a small status dict:
      clicked, paused, skipped_pause_headless
    """
    result = {
        "clicked": 0,
        "paused": False,
        "skipped_pause_headless": False,
    }

    if dismiss:
        try:
            result["clicked"] = await dismiss_popups_patchright(
                page,
                extra_selectors=extra_selectors,
                rounds=3,
            )
        except Exception as exc:
            print(f"[Consent] Auto-dismiss error (non-fatal): {exc}")

    if not pause_for_consent or already_paused:
        return result

    if headless:
        print(
            "[Consent] --pause-for-consent ignored in headless mode. "
            "Re-run with --no-headless to wait for a manual Accept click."
        )
        result["skipped_pause_headless"] = True
        return result

    host = ""
    try:
        host = urlparse(url or getattr(page, "url", "") or "").netloc
    except Exception:
        host = ""
    msg = (
        f"Consent / cookie banner on {host or 'page'} — "
        "Accept it in the browser window (or confirm auto-dismiss worked), then press ENTER."
    )
    ok = await prompt_manual_challenge(message=msg)
    result["paused"] = bool(ok)
    return result
