"""
auth.py — Login handler for username/password protected sites.

Features
--------
- Auto-detects common username / password / submit selectors.
- Explicit-selector override via login_with_selectors().
- Human-like typing delays to avoid bot detection.
- Smart post-login success/failure detection:
    * Avoids false-negatives caused by login-related words in redirect URLs.
    * Detects CAPTCHA / 2FA challenges and warns the user.
    * Waits for an actual navigation away from the login page, not just networkidle.
- Session persistence: save_session() / restore_session() dump and reload cookies
  so a crawl can resume without re-authenticating.
- Full error handling in both auto and manual selector paths.
"""

import asyncio
import json
import os
from typing import Optional

from patchright.async_api import Page, BrowserContext
from config.config import DEFAULT_CONFIG


# ── Common selector patterns ──────────────────────────────────────────────────

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

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Log in")',
    'button:has-text("Login")',
    'button:has-text("Sign in")',
    'button:has-text("Sign In")',
    'button:has-text("Continue")',
    '[role="button"]:has-text("Log in")',
    '[role="button"]:has-text("Sign in")',
]

# Selectors that suggest a CAPTCHA or 2FA challenge appeared
CAPTCHA_SELECTORS = [
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    '.g-recaptcha',
    '[data-sitekey]',
    'input[name="otp"]',
    'input[name="totp"]',
    'input[name="mfa"]',
    'input[name="two_factor"]',
    'input[placeholder*="verification" i]',
    'input[placeholder*="authenticator" i]',
    'input[placeholder*="one-time" i]',
]

# Error-message selectors that indicate login failed
ERROR_SELECTORS = [
    '[class*="error"]:not(script)',
    '[class*="alert-danger"]',
    '[class*="alert-error"]',
    '[id*="error"]',
    '[role="alert"]',
    'p:has-text("incorrect")',
    'p:has-text("invalid")',
    'p:has-text("failed")',
    'p:has-text("wrong password")',
    'p:has-text("account not found")',
    'span:has-text("incorrect")',
    'span:has-text("invalid")',
]

# Words in the *path component* (not query/fragment) that suggest we're still on
# a login page. We only check the path so /account/settings?from=signin doesn't
# trigger a false negative.
LOGIN_PATH_KEYWORDS = ["login", "signin", "sign-in", "log-in", "auth/login"]


class AuthHandler:
    def __init__(
        self,
        typing_delay: int = DEFAULT_CONFIG["typing_delay"],
        field_delay: float = DEFAULT_CONFIG["field_delay"],
    ):
        self.typing_delay = typing_delay
        self.field_delay = field_delay

    # ── Public API ────────────────────────────────────────────────────────────

    async def login(
        self,
        page: Page,
        login_url: str,
        username: str,
        password: str,
        timeout: int = DEFAULT_CONFIG["timeout"],
        wait_until: str = DEFAULT_CONFIG["wait_until"],
    ) -> bool:
        """
        Navigate to login_url and attempt to fill credentials using auto-detected
        selectors. Returns True if login appears successful.
        """
        print(f"[Auth] Navigating to login page: {login_url}")
        if not await self._goto_safe(page, login_url, timeout, wait_until):
            return False

        username_field = await self._find_element(page, USERNAME_SELECTORS, timeout=3000)
        if not username_field:
            print("[Auth] Could not find username/email field.")
            print("[Auth] Tip: use --username-selector and --password-selector to specify fields manually.")
            return False

        password_field = await self._find_element(page, PASSWORD_SELECTORS, timeout=3000)
        if not password_field:
            print("[Auth] Could not find password field.")
            return False

        if not await self._fill_field(page, username_field, username, "username"):
            return False
        if not await self._fill_field(page, password_field, password, "password"):
            return False

        return await self._submit_and_verify(
            page, password_field, login_url, timeout, wait_until
        )

    async def login_with_selectors(
        self,
        page: Page,
        login_url: str,
        username: str,
        password: str,
        username_selector: str,
        password_selector: str,
        submit_selector: Optional[str] = None,
        timeout: int = DEFAULT_CONFIG["timeout"],
        wait_until: str = DEFAULT_CONFIG["wait_until"],
    ) -> bool:
        """Login using explicitly provided CSS selectors."""
        print(f"[Auth] Logging in with custom selectors at: {login_url}")
        if not await self._goto_safe(page, login_url, timeout, wait_until):
            return False

        try:
            await page.fill(username_selector, username)
            await asyncio.sleep(self.field_delay)
            await page.fill(password_selector, password)
            await asyncio.sleep(self.field_delay)
        except Exception as e:
            print(f"[Auth] Error filling in login fields: {e}")
            return False

        if submit_selector:
            try:
                await page.click(submit_selector)
            except Exception as e:
                print(f"[Auth] Error clicking submit ({submit_selector}): {e}")
                # Fallback: press Enter in password field
                try:
                    await page.press(password_selector, "Enter")
                except Exception:
                    return False
        else:
            try:
                await page.press(password_selector, "Enter")
            except Exception as e:
                print(f"[Auth] Could not submit form via Enter: {e}")
                return False

        return await self._verify_login(page, login_url, timeout, wait_until)

    async def save_session(self, context: BrowserContext, path: str) -> None:
        """
        Persist cookies from the browser context to a JSON file so the session
        can be restored later without re-authenticating.
        """
        try:
            cookies = await context.cookies()
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            print(f"[Auth] Session saved -> {path} ({len(cookies)} cookies)")
        except Exception as e:
            print(f"[Auth] Warning: could not save session: {e}")

    async def restore_session(self, context: BrowserContext, path: str) -> bool:
        """
        Load cookies from a previously saved session file back into the context.
        Returns True if cookies were loaded successfully.
        """
        if not os.path.isfile(path):
            print(f"[Auth] No session file found at {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            print(f"[Auth] Session restored <- {path} ({len(cookies)} cookies)")
            return True
        except Exception as e:
            print(f"[Auth] Warning: could not restore session: {e}")
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _goto_safe(
        self, page: Page, url: str, timeout: int, wait_until: str
    ) -> bool:
        """Navigate to url, returning False on failure instead of raising."""
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
            return True                                                                                                                   
        except Exception as e:
            print(f"[Auth] Failed to load page ({url}): {e}")
            return False

    async def _fill_field(self, page: Page, locator, value: str, label: str) -> bool:
        """Click a field, clear it, and type the value with human-like delays."""
        try:
            await locator.click()
            await locator.fill("")          # clear any pre-filled value
            await asyncio.sleep(0.1)
            await page.keyboard.type(value, delay=self.typing_delay)
            await asyncio.sleep(self.field_delay)
            return True
        except Exception as e:
            print(f"[Auth] Error filling {label} field: {e}")
            return False

    async def _submit_and_verify(
        self,
        page: Page,
        password_field,
        login_url: str,
        timeout: int,
        wait_until: str,
    ) -> bool:
        """Click the submit button (or press Enter) then verify login success."""
        submit = await self._find_element(page, SUBMIT_SELECTORS, timeout=2000)
        try:
            if submit:
                await submit.click()
            else:
                print("[Auth] No submit button found; pressing Enter in password field.")
                await password_field.press("Enter")
        except Exception as e:
            print(f"[Auth] Error submitting login form: {e}")
            return False

        return await self._verify_login(page, login_url, timeout, wait_until)

    async def _verify_login(
        self, page: Page, login_url: str, timeout: int, wait_until: str
    ) -> bool:
        """
        Wait for the page to change after submit, then decide if login succeeded.

        Strategy:
        1. Wait for navigation / load state.
        2. If we're still on a URL that *exactly* matches the login page path → failed.
        3. If a CAPTCHA / 2FA widget is visible → warn and return False.
        4. If a visible error message is present → failed.
        5. Otherwise → success.
        """
        # Give the page time to react (navigation or JS redirect)
        try:
            await page.wait_for_load_state(wait_until, timeout=timeout)
        except Exception:
            pass  # timeout here is non-fatal; we still check the URL

        # Small extra wait for JS-driven redirects that fire after networkidle
        await asyncio.sleep(1.0)

        current_url = page.url

        # ── CAPTCHA / 2FA detection ───────────────────────────────────────────
        captcha_found = await self._any_visible(page, CAPTCHA_SELECTORS, timeout=500)
        if captcha_found:
            print(
                "[Auth] CAPTCHA or 2FA challenge detected! "
                "Run with --no-headless so you can solve it manually, "
                "or supply a session file with --session-file."
            )
            return False

        # ── Still on login page? ──────────────────────────────────────────────
        from urllib.parse import urlparse
        current_path = urlparse(current_url).path.lower().rstrip("/")
        login_path   = urlparse(login_url).path.lower().rstrip("/")

        if current_path == login_path:
            # Check if an error message is now visible
            if await self._any_visible(page, ERROR_SELECTORS, timeout=1000):
                print("[Auth] Login failed — error message visible on page.")
            else:
                print("[Auth] Login failed — still on the login page after submit.")
            return False

        # ── Visible error message on the redirect target ──────────────────────
        if await self._any_visible(page, ERROR_SELECTORS, timeout=500):
            print(f"[Auth] Login failed — error message visible at {current_url}.")
            return False

        print(f"[Auth] Login successful. Now at: {current_url}")
        return True

    async def _find_element(self, page: Page, selectors: list, timeout: int = 2000):
        """Try each selector and return the first visible, enabled element."""
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=timeout) and await el.is_enabled(timeout=timeout):
                    return el
            except Exception:
                continue
        return None

    async def _any_visible(self, page: Page, selectors: list, timeout: int = 500) -> bool:
        """Return True if any selector in the list matches a visible element."""
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue
        return False
