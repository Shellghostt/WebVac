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
import re
from typing import Optional

from patchright.async_api import Page, BrowserContext
from webvac.config.config import DEFAULT_CONFIG
from webvac.auth.popups import dismiss_popups_patchright


# ── Common selector patterns ──────────────────────────────────────────────────

USERNAME_SELECTORS = [
    '#login-username',  # common visible alias (e.g. Vue dual-field forms)
    'input[name="_username"]',  # Symfony / dual-field forms
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[name="user"]',
    'input[name="login"]',
    'input[name="log"]',
    'input[name="identifier"]',
    'input[id="email"]',
    'input[id="username"]',
    'input[id="login_field"]',  # GitHub
    'input[id="ap_email"]',  # Amazon
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
    '#login-password',  # chess.com visible field
    'input[name="_password"]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
    'input[name="password"]',
    'input[id="password"]',
    'input[id="ap_password"]',
]

# First-step "Continue / Next" when password is not yet on the page
CONTINUE_SELECTORS = [
    'button:has-text("Continue")',
    'button:has-text("Next")',
    'button:has-text("Weiter")',
    '[role="button"]:has-text("Continue")',
    '[role="button"]:has-text("Next")',
    'form button[type="submit"]',
    'button[type="submit"]',
    'input[type="submit"]',
]

SUBMIT_SELECTORS = [
    'button#login',  # chess.com
    '#authentication-login-form button[type="submit"]',
    'form button[type="submit"]',
    'form input[type="submit"]',
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Log In")',
    'button:has-text("Log in")',
    'button:has-text("Login")',
    'button:has-text("Sign in")',
    'button:has-text("Sign In")',
    'button:has-text("Continue")',
    '[role="button"]:has-text("Log in")',
    '[role="button"]:has-text("Sign in")',
]

# Never treat these as the site's password-login submit button
_SSO_TEXT_RE = re.compile(
    r"google|gmail|facebook|github|apple|microsoft|linkedin|"
    r"sso|oauth|continue with|sign in with",
    re.I,
)

# Solvable CAPTCHA widgets + invisible/embed signals (chess.com Turnstile has no visible box)
CAPTCHA_WIDGET_SELECTORS = [
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    'iframe[src*="challenges.cloudflare.com"]',
    '.g-recaptcha',
    '.h-captcha',
    '.cf-turnstile',
    '[data-sitekey]',
    '#turnstile-login-form',
    '#turnstile_token',
    'input[name="cf-turnstile-response"]',
    'input[name="turnstile_token"]',
]

# Legacy alias
CAPTCHA_SELECTORS = CAPTCHA_WIDGET_SELECTORS

# Login failure — only match elements with actual credential-failure text,
# not generic [class*="error"] / [role="alert"] which fire on many valid pages.
ERROR_SELECTORS = [
    '[class*="alert-danger"]:visible',
    '[class*="alert-error"]:visible',
    ':is(p, span, div):has-text("incorrect password")',
    ':is(p, span, div):has-text("invalid password")',
    ':is(p, span, div):has-text("wrong password")',
    ':is(p, span, div):has-text("account not found")',
    ':is(p, span, div):has-text("invalid credentials")',
    ':is(p, span, div):has-text("invalid username")',
    ':is(p, span, div):has-text("login failed")',
    ':is(p, span, div):has-text("authentication failed")',
    ':is(p, span, div):has-text("incorrect email")',
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
        *,
        already_on_page: bool = False,
    ) -> bool:
        """
        Navigate to login_url (unless already_on_page) and fill credentials using
        auto-detected selectors. Supports email→Continue→password wizards.
        """
        if not already_on_page:
            print(f"[Auth] Navigating to login page: {login_url}")
            if not await self._goto_safe(page, login_url, timeout, wait_until):
                return False
            n = await dismiss_popups_patchright(page, rounds=4)
            if n:
                print(f"[Auth] Dismissed {n} cookie/privacy popup control(s)")
        else:
            print(f"[Auth] Filling credentials on current page: {page.url}")

        return await self._auto_fill_and_submit(
            page, login_url, username, password, timeout, wait_until
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
        *,
        already_on_page: bool = False,
    ) -> bool:
        """Login using explicitly provided CSS selectors."""
        if not already_on_page:
            print(f"[Auth] Logging in with custom selectors at: {login_url}")
            if not await self._goto_safe(page, login_url, timeout, wait_until):
                return False
            n = await dismiss_popups_patchright(page, rounds=4)
            if n:
                print(f"[Auth] Dismissed {n} cookie/privacy popup control(s)")
        else:
            print(f"[Auth] Filling custom selectors on: {page.url}")

        try:
            user_loc = page.locator(username_selector).first
            await user_loc.wait_for(state="visible", timeout=min(timeout, 15000))
            await self._fill_locator(user_loc, username, "username")
            await asyncio.sleep(self.field_delay)

            pass_loc = page.locator(password_selector).first
            # Multi-step: password may appear after Continue
            try:
                await pass_loc.wait_for(state="visible", timeout=4000)
            except Exception:
                print("[Auth] Password field not visible yet — clicking Continue/Next…")
                cont = await self._find_element(page, CONTINUE_SELECTORS, timeout=2000)
                if cont:
                    await cont.click()
                    await asyncio.sleep(1.0)
                await pass_loc.wait_for(state="visible", timeout=min(timeout, 15000))

            await self._fill_locator(pass_loc, password, "password")
            await asyncio.sleep(self.field_delay)
        except Exception as e:
            print(f"[Auth] Error filling in login fields: {e}")
            return False

        await self._sync_hidden_credential_fields(page)

        # Solve any CAPTCHA on the login form BEFORE submitting
        await self._solve_pre_submit_captcha(page)

        if submit_selector:
            try:
                await page.click(submit_selector)
            except Exception as e:
                print(f"[Auth] Error clicking submit ({submit_selector}): {e}")
                try:
                    await page.press(password_selector, "Enter")
                except Exception:
                    return False
        else:
            try:
                # Prefer the real login button over Enter (chess.com rejects Enter).
                submit = await self._find_element(page, SUBMIT_SELECTORS, timeout=2000)
                if submit:
                    await submit.click()
                else:
                    await page.press(password_selector, "Enter")
            except Exception as e:
                print(f"[Auth] Could not submit form: {e}")
                return False

        await asyncio.sleep(1.2)
        if self._path_looks_like_login(page.url, login_url):
            if await self._force_native_form_submit(page):
                print("[Auth] Client-side submit gate detected — forced native form submit.")
                await asyncio.sleep(1.5)

        return await self._verify_login(page, login_url, timeout, wait_until)

    async def _auto_fill_and_submit(
        self,
        page: Page,
        login_url: str,
        username: str,
        password: str,
        timeout: int,
        wait_until: str,
    ) -> bool:
        """Auto-detect fields, handle email→Continue→password, submit, verify."""
        if not await self._wait_for_login_form(page, timeout_ms=min(timeout, 20000)):
            print("[Auth] Login form did not appear in time (SPA / iframe / wrong URL?).")
            return False

        username_field = await self._find_element(page, USERNAME_SELECTORS, timeout=5000)
        if not username_field:
            print("[Auth] Could not find username/email field.")
            print(
                "[Auth] Tip: pass --login-url to the real login page, or set "
                "--username-selector / --password-selector."
            )
            return False

        if not await self._fill_locator(username_field, username, "username"):
            return False

        password_field = await self._find_element(page, PASSWORD_SELECTORS, timeout=2500)
        if not password_field:
            print("[Auth] Password not on this step — advancing with Continue/Next…")
            cont = await self._find_element(page, CONTINUE_SELECTORS, timeout=3000)
            if not cont:
                print("[Auth] Could not find password field or Continue button.")
                return False
            try:
                await cont.click()
            except Exception as e:
                print(f"[Auth] Failed to click Continue: {e}")
                return False
            await asyncio.sleep(1.2)
            n = await dismiss_popups_patchright(page, rounds=2)
            if n:
                print(f"[Auth] Dismissed {n} popup(s) after Continue")
            password_field = await self._find_element(page, PASSWORD_SELECTORS, timeout=8000)
            if not password_field:
                print("[Auth] Could not find password field after Continue.")
                return False

        if not await self._fill_locator(password_field, password, "password"):
            return False

        await self._sync_hidden_credential_fields(page)

        # Solve any CAPTCHA on the login form BEFORE submitting
        await self._solve_pre_submit_captcha(page)

        return await self._submit_and_verify(
            page, password_field, login_url, timeout, wait_until
        )

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
        """Back-compat alias — prefers locator.fill so focus cannot be lost."""
        return await self._fill_locator(locator, value, label)

    async def _fill_locator(self, locator, value: str, label: str) -> bool:
        """Focus, clear, and set the field value (fill first; typed fallback)."""
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=5000)
            await asyncio.sleep(0.15)
            # fill() is reliable; keyboard.type often types into the wrong target
            # if focus was stolen by a cookie banner / overlay.
            try:
                await locator.fill(value, timeout=5000)
            except Exception:
                await locator.fill("")
                await asyncio.sleep(0.05)
                await locator.type(value, delay=max(20, int(self.typing_delay or 40)))
            # Verify something landed
            try:
                current = await locator.input_value(timeout=1000)
                if not current:
                    await locator.fill(value, timeout=5000)
            except Exception:
                pass
            await asyncio.sleep(self.field_delay)
            print(f"[Auth] Filled {label} field.")
            return True
        except Exception as e:
            print(f"[Auth] Error filling {label} field: {e}")
            return False

    async def _solve_pre_submit_captcha(self, page: Page) -> bool:
        """
        If a CAPTCHA is present on the login form (visible widget OR invisible
        Turnstile fields / scripts), solve via CapSolver before submitting.

        While CapSolver runs (often 10–40s), also watch for the page leaving the
        login URL — headed users may complete Turnstile + Log In manually.
        """
        from webvac.captcha.detect import detect_captcha_raw

        raw = await detect_captcha_raw(page)
        if not raw:
            if not await self._any_present(page, CAPTCHA_WIDGET_SELECTORS):
                return False

        print("[Auth] CAPTCHA detected on login form — solving before submit...")
        try:
            from webvac.captcha import solver_from_config
            from webvac.captcha.config import CaptchaSolverConfig

            cfg = CaptchaSolverConfig.from_mapping()
            if not cfg.api_key or not cfg.enabled:
                print("[Auth] No CapSolver API key — cannot auto-solve login CAPTCHA.")
                return False

            mgr = solver_from_config()
            try:
                mgr.attach_network_watcher(page)
            except Exception:
                pass
            url = getattr(page, "url", "") or ""
            login_url = url
            ua = ""
            try:
                ua = await page.evaluate("navigator.userAgent") or ""
            except Exception:
                pass

            solve_task = asyncio.create_task(
                mgr.try_solve_on_page(page, url=url, user_agent=ua)
            )
            while not solve_task.done():
                await asyncio.sleep(0.6)
                try:
                    cur = page.url
                except Exception:
                    cur = ""
                if cur and not self._path_looks_like_login(cur, login_url):
                    print(f"[Auth] Page left login URL during CAPTCHA solve → {cur}")
                    solve_task.cancel()
                    try:
                        await solve_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    return True

            result = solve_task.result()
            if result.success:
                print("[Auth] CAPTCHA solved — proceeding to submit.")
                await self._sync_hidden_credential_fields(page)
                await asyncio.sleep(0.5)
                return True

            # Inject can fail if the page already navigated (manual login)
            try:
                cur = page.url
            except Exception:
                cur = ""
            if cur and not self._path_looks_like_login(cur, login_url):
                print(f"[Auth] Login already completed during CAPTCHA solve → {cur}")
                return True

            print(f"[Auth] CAPTCHA auto-solve failed: {result.error}")
            return False
        except Exception as exc:
            try:
                cur = getattr(page, "url", "") or ""
                if cur and "login" not in cur.lower():
                    print(f"[Auth] Login already completed (CAPTCHA error ignored) → {cur}")
                    return True
            except Exception:
                pass
            print(f"[Auth] CAPTCHA solve error: {exc}")
            return False

    async def _sync_hidden_credential_fields(self, page: Page) -> None:
        """Copy visible login fields into hidden submit fields (chess.com Vue form)."""
        try:
            await page.evaluate(
                """() => {
                  const pairs = [
                    ['#login-username', '#username, input[name="_username"]'],
                    ['#login-password', '#password, input[name="_password"]'],
                  ];
                  for (const [visSel, hidSel] of pairs) {
                    const vis = document.querySelector(visSel);
                    const hid = document.querySelector(hidSel);
                    if (vis && hid && vis.value) {
                      hid.value = vis.value;
                      hid.dispatchEvent(new Event('input', { bubbles: true }));
                      hid.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                  }
                }"""
            )
        except Exception:
            pass

    async def _submit_and_verify(
        self,
        page: Page,
        password_field,
        login_url: str,
        timeout: int,
        wait_until: str,
    ) -> bool:
        """Click the submit button (or press Enter) then verify login success."""
        # Already logged in (manual captcha / late navigation during CapSolver)
        try:
            if not self._path_looks_like_login(page.url, login_url):
                print(f"[Auth] Login successful. Now at: {page.url}")
                return True
        except Exception:
            pass

        await self._sync_hidden_credential_fields(page)
        pre_url = page.url
        clicked = await self._click_login_submit(page, password_field)
        if not clicked:
            # Page may have navigated during the click attempt
            try:
                if not self._path_looks_like_login(page.url, login_url):
                    print(f"[Auth] Login successful. Now at: {page.url}")
                    return True
            except Exception:
                pass
            print("[Auth] Could not click login submit control.")
            return False

        await asyncio.sleep(1.2)
        try:
            still_here = page.url == pre_url or self._path_looks_like_login(page.url, login_url)
        except Exception:
            still_here = True
        if still_here:
            forced = await self._force_native_form_submit(page)
            if forced:
                print("[Auth] Client-side submit gate detected — forced native form submit.")
                await asyncio.sleep(1.5)

        return await self._verify_login(page, login_url, timeout, wait_until)

    async def _click_login_submit(self, page: Page, password_field) -> bool:
        """Click the primary login button; fall back to Enter only as last resort."""
        # Direct, high-signal selectors first (chess.com uses button#login)
        preferred = [
            "button#login",
            "#login",
            "#authentication-login-form button[type='submit']",
            "button:has-text('Log In')",
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
            "button[type='submit']",
        ]
        for sel in preferred:
            try:
                loc = page.locator(sel).first
                await loc.wait_for(state="visible", timeout=2500)
                if await loc.is_enabled(timeout=500):
                    await loc.click(timeout=5000)
                    print(f"[Auth] Clicked submit ({sel}).")
                    return True
            except Exception:
                continue

        submit = await self._find_element(page, SUBMIT_SELECTORS, timeout=3000)
        if submit:
            try:
                await submit.click(timeout=5000)
                print("[Auth] Clicked submit (auto-detected).")
                return True
            except Exception as e:
                print(f"[Auth] Submit click failed: {e}")

        try:
            print("[Auth] No submit button found; pressing Enter in password field.")
            await password_field.press("Enter")
            return True
        except Exception as e:
            print(f"[Auth] Error submitting login form: {e}")
            return False

    def _path_looks_like_login(self, current_url: str, login_url: str) -> bool:
        from urllib.parse import urlparse
        try:
            return (
                urlparse(current_url).path.lower().rstrip("/")
                == urlparse(login_url).path.lower().rstrip("/")
            )
        except Exception:
            return False

    async def _force_native_form_submit(self, page: Page) -> bool:
        """
        Call HTMLFormElement.prototype.submit() to bypass page submit listeners
        that block when Turnstile is mid-challenge (chess.com) or require a
        specific submitter id.
        """
        try:
            return bool(
                await page.evaluate(
                    """() => {
                      const form = document.querySelector(
                        '#authentication-login-form, form.authentication-login-form, form.login-form, form'
                      );
                      if (!form) return false;
                      const user = form.querySelector('#username, input[name="_username"], input[type="email"]');
                      const pass = form.querySelector('#password, input[name="_password"], input[type="password"]');
                      const tok = form.querySelector(
                        '#turnstile_token, [name="turnstile_token"], [name="cf-turnstile-response"]'
                      );
                      // Only force when credentials look filled (and token if present).
                      if (user && !(user.value || '').trim()) return false;
                      if (pass && !(pass.value || '').trim()) return false;
                      if (tok && !(tok.value || '').trim()) return false;
                      HTMLFormElement.prototype.submit.call(form);
                      return true;
                    }"""
                )
            )
        except Exception:
            return False

    async def _verify_login(
        self, page: Page, login_url: str, timeout: int, wait_until: str
    ) -> bool:
        """
        Wait for the page to change after submit, then decide if login succeeded.

        Strategy:
        1. Wait for navigation / load state.
        2. If an OTP/MFA field appeared → return False (caller handles MFA).
        3. If a CAPTCHA widget appeared → return False (caller tries CapSolver).
        4. If we're still on the login page path with error text → failed.
        5. If we navigated away → success.
        """
        try:
            await page.wait_for_load_state(wait_until, timeout=timeout)
        except Exception:
            pass

        await asyncio.sleep(1.2)

        try:
            current_url = page.url
        except Exception:
            current_url = ""

        from urllib.parse import urlparse
        current_path = urlparse(current_url).path.lower().rstrip("/")
        login_path = urlparse(login_url).path.lower().rstrip("/")

        # Already away from login — success (even if CAPTCHA nodes briefly linger)
        if current_path and current_path != login_path:
            if await self._any_visible(page, ERROR_SELECTORS, timeout=400):
                print(f"[Auth] Login failed — credential error visible at {current_url}.")
                return False
            print(f"[Auth] Login successful. Now at: {current_url}")
            return True

        # Still on login page: CAPTCHA present → caller may retry CapSolver
        from webvac.captcha.detect import detect_captcha_raw

        if await detect_captcha_raw(page) or await self._any_present(page, CAPTCHA_WIDGET_SELECTORS):
            # Interactive checkbox visible without a token often means solve incomplete
            print("[Auth] CAPTCHA detected after submit — will attempt auto-solve.")
            return False

        if await self._any_visible(page, ERROR_SELECTORS, timeout=800):
            print("[Auth] Login failed — credential error visible on page.")
        else:
            print("[Auth] Login may have failed — still on the login page after submit.")
        return False

    async def _wait_for_login_form(self, page: Page, *, timeout_ms: int = 15000) -> bool:
        """Wait until a username or password field is visible (main page or iframe)."""
        probes = USERNAME_SELECTORS[:6] + PASSWORD_SELECTORS
        per_try = max(1500, timeout_ms // max(len(probes), 1))
        roots = [page] + [f for f in page.frames if f != page.main_frame]
        for root in roots:
            for sel in probes:
                try:
                    loc = root.locator(sel).first
                    await loc.wait_for(state="visible", timeout=per_try)
                    if root is not page:
                        print(f"[Auth] Login form detected in iframe.")
                    return True
                except Exception:
                    continue
        await asyncio.sleep(1.0)
        return bool(await self._find_element(page, USERNAME_SELECTORS + PASSWORD_SELECTORS, timeout=2000))

    async def _find_element(self, page: Page, selectors: list, timeout: int = 2000):
        """Try each selector on the main page, then inside child iframes."""
        el = await self._find_element_in_root(page, selectors, timeout)
        if el:
            return el
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                el = await self._find_element_in_root(frame, selectors, min(timeout, 4000))
                if el:
                    print(f"[Auth] Matched login control inside iframe.")
                    return el
            except Exception:
                continue
        return None

    async def _find_element_in_root(self, root, selectors: list, timeout: int = 2000):
        """Try each selector and return the first visible, enabled, non-SSO element."""
        # Per-candidate visibility probe stays short so we can try many selectors.
        probe = min(800, max(250, timeout // 4))
        for sel in selectors:
            try:
                loc = root.locator(sel)
                count = await loc.count()
                for i in range(min(count, 8)):
                    el = loc.nth(i)
                    try:
                        if not await el.is_visible(timeout=probe):
                            continue
                        if not await el.is_enabled(timeout=probe):
                            continue
                    except Exception:
                        continue
                    try:
                        text = (await el.inner_text(timeout=400) or "").strip()
                    except Exception:
                        text = ""
                    try:
                        aria = (await el.get_attribute("aria-label")) or ""
                    except Exception:
                        aria = ""
                    blob = f"{text} {aria} {sel}"
                    if _SSO_TEXT_RE.search(blob):
                        continue
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

    async def _any_present(self, page: Page, selectors: list) -> bool:
        """Return True if any selector matches in the DOM (including hidden inputs)."""
        for sel in selectors:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                continue
        return False
