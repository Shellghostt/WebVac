"""
nodriver_auth.py — Optional login helper using nodriver for auth only.

This module is intentionally isolated from the main crawler engine so WebVac can:
1) perform login with nodriver, then
2) export cookies to a JSON session file, then
3) continue crawling with Patchright.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional
from urllib.parse import urlparse

from config.config import DEFAULT_CONFIG
from auth.popups import dismiss_popups_nodriver

USERNAME_SELECTORS = [
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[name="user"]',
    'input[type="text"][name*="user"]',
    'input[type="text"][name*="email"]',
    'input[type="text"][name*="login"]',
    'input[id*="user"]',
    'input[id*="email"]',
    'input[id*="login"]',
    'input[placeholder*="email" i]',
    'input[placeholder*="username" i]',
    'input[autocomplete="username"]',
    'input[autocomplete="email"]',
]

PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[autocomplete="current-password"]',
]

# Prefer real form submit buttons first
SUBMIT_SELECTORS = [
    'form button[type="submit"]',
    'form input[type="submit"]',
    'button[type="submit"]',
    'input[type="submit"]',
    '[role="button"][type="submit"]',
]

# Text labels for the site's own Sign In button (NOT Google/SSO)
SUBMIT_TEXT_CANDIDATES = [
    "sign in",
    "log in",
    "login",
    "log-in",
    "signin",
    "submit",
    "continue",
]

# Never click these — they open Google / social OAuth
_SSO_BLOCKLIST = re.compile(
    r"google|gmail|facebook|github|apple|microsoft|linkedin|"
    r"sso|oauth|openid|okta|auth0|continue with|sign in with",
    re.I,
)

_GOOGLE_HOST_RE = re.compile(
    r"(?:^|\.)(?:accounts\.google\.com|google\.com|googleapis\.com)$",
    re.I,
)


class NodriverAuthHandler:
    def __init__(
        self,
        typing_delay: int = DEFAULT_CONFIG["typing_delay"],
        field_delay: float = DEFAULT_CONFIG["field_delay"],
    ) -> None:
        self.typing_delay = typing_delay
        self.field_delay = field_delay

    async def login(
        self,
        login_url: str,
        username: str,
        password: str,
        *,
        session_file: str,
        headless: bool = True,
        timeout: int = DEFAULT_CONFIG["timeout"],
        username_selector: Optional[str] = None,
        password_selector: Optional[str] = None,
        submit_selector: Optional[str] = None,
        dismiss_selectors: Optional[list[str]] = None,
    ) -> bool:
        """Run nodriver login and write cookies to session_file."""
        try:
            import nodriver as uc
        except Exception as exc:
            print(f"[Auth/Nodriver] nodriver import failed: {exc}")
            print("[Auth/Nodriver] Install dependency: pip install nodriver")
            return False

        print(f"[Auth/Nodriver] Starting login flow at: {login_url}")
        browser = await uc.start(headless=headless)
        try:
            tab = await browser.get(login_url)
            await tab.sleep(1.0)

            if self._is_google_auth_url(getattr(tab, "url", "") or ""):
                print(
                    "[Auth/Nodriver] Page redirected to Google sign-in. "
                    "Use the site's email/password login URL (not Google SSO)."
                )
                return False

            # Cookie banners + privacy/consent modals (may appear in layers)
            n = await dismiss_popups_nodriver(tab, extra_selectors=dismiss_selectors, rounds=4)
            if n:
                print(f"[Auth/Nodriver] Dismissed {n} cookie/privacy popup control(s)")
            await tab.sleep(0.5)

            user_sel = username_selector or await self._first_selector(tab, USERNAME_SELECTORS)
            pass_sel = password_selector or await self._first_selector(tab, PASSWORD_SELECTORS)
            if not user_sel or not pass_sel:
                print("[Auth/Nodriver] Could not detect login fields.")
                print(
                    "[Auth/Nodriver] Tip: set username_selector / password_selector "
                    "in auth_creds.json"
                )
                return False

            await self._type_selector(tab, user_sel, username)
            await asyncio.sleep(self.field_delay)
            await self._type_selector(tab, pass_sel, password)
            await asyncio.sleep(self.field_delay)

            submitted = await self._submit_login(
                tab,
                password_selector=pass_sel,
                submit_selector=submit_selector,
            )
            if not submitted:
                print("[Auth/Nodriver] Could not click / submit the Sign In button.")
                return False

            # Wait for navigation / SPA redirect after submit
            wait_secs = max(2.0, min(15.0, timeout / 1000.0 * 0.25))
            await tab.sleep(wait_secs)
            await tab

            current_url = getattr(tab, "url", "") or ""
            if self._is_google_auth_url(current_url):
                print(
                    "[Auth/Nodriver] Ended on Google sign-in after submit. "
                    "The automation likely hit a 'Sign in with Google' button, "
                    "or the site forced Google SSO. Aborting."
                )
                return False

            if self._same_login_path(login_url, current_url):
                # Still on login URL — might be SPA that doesn't change path.
                # Treat as failure only if password field is still visible.
                still_login = await self._first_selector(tab, PASSWORD_SELECTORS)
                if still_login:
                    print("[Auth/Nodriver] Still on login page after submit.")
                    return False

            cookies = await self._get_cookies_dicts(browser, tab)
            if not cookies:
                print("[Auth/Nodriver] Login may have failed (no cookies found).")
                return False

            os.makedirs(os.path.dirname(session_file) or ".", exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)

            print(f"[Auth/Nodriver] Login successful → {current_url}")
            print(f"[Auth/Nodriver] Session saved -> {session_file} ({len(cookies)} cookies)")
            return True
        except Exception as exc:
            print(f"[Auth/Nodriver] Login failed: {exc}")
            return False
        finally:
            try:
                await browser.stop()
            except Exception:
                pass

    # ── Submit strategies ─────────────────────────────────────────────────────

    async def _submit_login(
        self,
        tab,
        *,
        password_selector: str,
        submit_selector: Optional[str],
    ) -> bool:
        """
        Try multiple ways to submit the email/password form.
        Explicitly avoids Google / social SSO buttons.
        """
        # 1) Explicit selector from user / JSON
        if submit_selector:
            if await self._click_selector(tab, submit_selector):
                print(f"[Auth/Nodriver] Clicked submit selector: {submit_selector}")
                return True
            print(f"[Auth/Nodriver] submit_selector failed: {submit_selector}")

        # 2) CSS submit buttons (skip SSO-looking ones)
        for sel in SUBMIT_SELECTORS:
            if await self._click_safe_submit(tab, sel):
                print(f"[Auth/Nodriver] Clicked submit via CSS: {sel}")
                return True

        # 3) Text-based Sign In / Log In (nodriver find), skip SSO labels
        if await self._click_submit_by_text(tab):
            return True

        # 4) JS: submit the <form> that owns the password field
        if await self._js_submit_password_form(tab, password_selector):
            print("[Auth/Nodriver] Submitted via form.requestSubmit()/form.submit()")
            return True

        # 5) Last resort: Enter in password field
        try:
            pass_el = await tab.select(password_selector, timeout=2)
            if pass_el:
                await pass_el.send_keys("\n")
                print("[Auth/Nodriver] Submitted via Enter key on password field")
                return True
        except Exception:
            pass

        return False

    async def _click_safe_submit(self, tab, selector: str) -> bool:
        """Click first matching submit-like element that is NOT an SSO button."""
        try:
            els = await tab.select_all(selector, timeout=2)
        except Exception:
            els = None
            try:
                el = await tab.select(selector, timeout=2)
                els = [el] if el else []
            except Exception:
                return False

        for el in els or []:
            if await self._is_sso_element(el):
                continue
            try:
                await el.click()
                return True
            except Exception:
                continue
        return False

    async def _click_submit_by_text(self, tab) -> bool:
        """Use nodriver text find for Sign In / Log In, never Google SSO."""
        for label in SUBMIT_TEXT_CANDIDATES:
            try:
                el = await tab.find(label, best_match=True)
            except Exception:
                el = None
            if not el:
                continue
            if await self._is_sso_element(el):
                print(f"[Auth/Nodriver] Skipping SSO-looking control: '{label}'")
                continue
            try:
                await el.click()
                print(f"[Auth/Nodriver] Clicked submit by text: '{label}'")
                return True
            except Exception:
                continue
        return False

    async def _js_submit_password_form(self, tab, password_selector: str) -> bool:
        """Submit the form containing the password field via JS (avoids wrong buttons)."""
        # Escape for JS string
        sel = password_selector.replace("\\", "\\\\").replace("'", "\\'")
        script = f"""
(() => {{
  const pass = document.querySelector('{sel}');
  if (!pass) return false;
  const form = pass.closest('form');
  if (!form) return false;
  if (typeof form.requestSubmit === 'function') {{
    form.requestSubmit();
  }} else {{
    form.submit();
  }}
  return true;
}})()
"""
        try:
            result = await tab.evaluate(script)
            return bool(result)
        except Exception:
            return False

    async def _is_sso_element(self, el) -> bool:
        """True if element looks like Google / social OAuth, not site password login."""
        parts: list[str] = []
        for attr in ("text", "text_all", "aria_label", "title", "id", "class_", "href", "name"):
            try:
                val = getattr(el, attr, None)
                if val:
                    parts.append(str(val))
            except Exception:
                pass
        try:
            # nodriver Element often exposes .attributes or similar
            attrs = getattr(el, "attrs", None) or getattr(el, "attributes", None) or {}
            if isinstance(attrs, dict):
                parts.extend(str(v) for v in attrs.values())
        except Exception:
            pass
        try:
            html = getattr(el, "html", None) or ""
            if html:
                parts.append(str(html)[:500])
        except Exception:
            pass

        blob = " ".join(parts)
        return bool(_SSO_BLOCKLIST.search(blob))

    # ── Field helpers ─────────────────────────────────────────────────────────

    async def _first_selector(self, tab, selectors: list[str]) -> Optional[str]:
        for sel in selectors:
            try:
                el = await tab.select(sel, timeout=2)
                if el:
                    return sel
            except Exception:
                continue
        return None

    async def _type_selector(self, tab, selector: str, value: str) -> None:
        el = await tab.select(selector, timeout=5)
        if not el:
            raise RuntimeError(f"selector not found: {selector}")
        try:
            await el.clear_input()
        except Exception:
            pass
        await el.send_keys(value)

    async def _click_selector(self, tab, selector: str, quiet: bool = False) -> bool:
        try:
            el = await tab.select(selector, timeout=2)
            if not el:
                return False
            if await self._is_sso_element(el):
                if not quiet:
                    print(f"[Auth/Nodriver] Refusing to click SSO control: {selector}")
                return False
            await el.click()
            return True
        except Exception:
            if not quiet:
                print(f"[Auth/Nodriver] Could not click selector: {selector}")
            return False

    async def _get_cookies_dicts(self, browser, tab) -> list[dict]:
        """Export tab cookies into a Playwright-compatible JSON list."""
        raw = []
        try:
            raw = await tab.get_all_cookies()
        except Exception:
            pass
        if not raw:
            try:
                raw = await browser.cookies.get_all()
            except Exception:
                pass
        if not raw:
            try:
                raw = await browser.cookies.get_all(requests_cookie_format=False)
            except Exception:
                pass

        out: list[dict] = []
        for c in raw or []:
            # nodriver may return objects or dicts
            if not isinstance(c, dict):
                c = {
                    "name": getattr(c, "name", None),
                    "value": getattr(c, "value", None),
                    "domain": getattr(c, "domain", None),
                    "path": getattr(c, "path", "/"),
                    "expires": getattr(c, "expires", -1),
                    "httpOnly": getattr(c, "httpOnly", False),
                    "secure": getattr(c, "secure", False),
                    "sameSite": getattr(c, "sameSite", "Lax"),
                }
            name = c.get("name")
            value = c.get("value")
            domain = c.get("domain")
            path = c.get("path", "/")
            if not (name and value and domain):
                continue
            out.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path,
                    "expires": c.get("expires", -1),
                    "httpOnly": bool(c.get("httpOnly", False)),
                    "secure": bool(c.get("secure", False)),
                    "sameSite": c.get("sameSite", "Lax"),
                }
            )
        return out

    def _same_login_path(self, login_url: str, current_url: str) -> bool:
        login_path = urlparse(login_url).path.lower().rstrip("/")
        current_path = urlparse(current_url).path.lower().rstrip("/")
        return login_path == current_path

    def _is_google_auth_url(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        if not host:
            return False
        if "accounts.google." in host:
            return True
        # oauth redirect pages that clearly are Google
        if "google.com" in host and any(
            x in url.lower() for x in ("/o/oauth", "/signin", "accounts.google")
        ):
            return True
        return bool(_GOOGLE_HOST_RE.search(host) and "accounts" in host)
