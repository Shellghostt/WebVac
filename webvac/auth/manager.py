"""
manager.py — Unified AuthManager facade for WebVac login / session / verify / walls.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional
from urllib.parse import urlparse

from webvac.auth.auth import AuthHandler, CAPTCHA_SELECTORS
from webvac.auth.cookie_audit import audit_cookies, print_audit_warnings
from webvac.auth.credentials import resolve_credentials
from webvac.auth.mfa import generate_totp, prompt_manual_challenge, prompt_otp
from webvac.auth.profile import AuthProfile, load_auth_profile, merge_cli_into_profile
from webvac.auth.session_store import (
    cookies_from_state,
    is_expired,
    load_session,
    save_session,
    set_meta,
)
from webvac.auth.steps import run_steps_patchright
from webvac.auth.wall import apply_wall_policy, is_auth_wall, is_auth_wall_page, is_logout_url
from webvac.auth.popups import dismiss_popups_patchright
from webvac.config.config import DEFAULT_CONFIG


class AuthManager:
    def __init__(
        self,
        browser,
        *,
        profile: Optional[AuthProfile] = None,
        concurrency: int = 1,
        headless: bool = True,
        timeout: int = DEFAULT_CONFIG["timeout"],
        wait_until: str = DEFAULT_CONFIG["wait_until"],
    ) -> None:
        self.browser = browser
        self.profile = profile or AuthProfile()
        self.concurrency = max(1, concurrency)
        self.headless = headless
        self.timeout = timeout
        self.wait_until = wait_until
        self._handler = AuthHandler()
        self._authenticated = False
        self._login_url = self.profile.login_url or ""

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def on_auth_wall(self) -> str:
        return apply_wall_policy(self.profile.on_auth_wall)

    def is_logout_url(self, url: str) -> bool:
        return is_logout_url(url)

    async def is_auth_wall(self, page=None, *, url: str = "", title: str = "", html: str = "") -> bool:
        if page is not None:
            return await is_auth_wall_page(page, seed_login_url=self._login_url)
        return is_auth_wall(
            url=url,
            title=title,
            html=html,
            seed_login_path=urlparse(self._login_url).path.lower().rstrip("/") if self._login_url else "",
        )

    async def restore(self, session_file: Optional[str] = None) -> bool:
        path = session_file or self.profile.session_file
        if not path or not os.path.isfile(path):
            return False
        try:
            state = load_session(path)
        except Exception as exc:
            print(f"[Auth] Could not load session {path}: {exc}")
            return False

        ttl = self.profile.session_ttl or int((state.get("_webvac_session_meta") or {}).get("ttl_sec") or 0)
        if ttl and is_expired(state):
            print(f"[Auth] Session expired (ttl={ttl}s) — will re-login if credentials available.")
            return False

        self.browser.set_auth_session(
            cookies=cookies_from_state(state),
            storage_state=state,
        )
        await self.browser.broadcast_auth_session()
        self._authenticated = True
        print(f"[Auth] Session restored from {path}")

        check = self.profile.auth_check_url
        if check:
            ok = await self.verify(check)
            if not ok:
                print("[Auth] auth-check-url failed after restore — session invalid.")
                self._authenticated = False
                return False
            set_meta(state, last_verified_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(), ttl_sec=ttl)
            try:
                save_session(path, state, ttl_sec=ttl, mark_verified=True)
            except Exception:
                pass
        return True

    async def verify(self, check_url: str) -> bool:
        """Open check_url on slot 0; return True if not an auth wall."""
        if not check_url:
            return True
        page = None
        try:
            page = await self.browser.new_page(slot=0)
            await page.goto(check_url, wait_until=self.wait_until, timeout=self.timeout)
            await asyncio.sleep(0.5)
            if await self.is_auth_wall(page):
                print(f"[Auth] Verify failed — auth wall at {check_url}")
                return False
            print(f"[Auth] Verify OK → {getattr(page, 'url', check_url)}")
            return True
        except Exception as exc:
            print(f"[Auth] Verify error: {exc}")
            return False
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    async def login(self, *, seed_url: str = "") -> bool:
        user, pw = resolve_credentials(self.profile.username, self.profile.password)
        if not user or not pw:
            print("[Auth] Username/password required (CLI, profile, or WEBVAC_USER/WEBVAC_PASS).")
            return False
        self.profile.username = user
        self.profile.password = pw

        login_url = self.profile.login_url or seed_url
        if not login_url:
            print("[Auth] login_url is required.")
            return False
        self._login_url = login_url

        ok = await self._login_patchright(login_url)
        if not ok:
            return False
        await self._persist_and_broadcast(seed_url=seed_url or login_url)

        check = self.profile.auth_check_url
        if check:
            if not await self.verify(check):
                self._authenticated = False
                return False

        # Cookie audit (scrape-safe warnings)
        try:
            cookies = await self.browser.get_cookies(slot=0)
            issues = audit_cookies(cookies, page_url=login_url)
            print_audit_warnings(issues)
        except Exception:
            pass

        self._authenticated = True
        return True

    async def ensure_authenticated(self, *, seed_url: str = "") -> bool:
        """Restore session if possible; otherwise login."""
        if self._authenticated:
            return True
        path = self.profile.session_file
        if path and os.path.isfile(path):
            if await self.restore(path):
                return True
        if self.profile.has_credentials() or resolve_credentials(
            self.profile.username, self.profile.password
        )[0]:
            return await self.login(seed_url=seed_url)
        return False

    async def bootstrap_manual(self, *, url: str, session_file: str) -> bool:
        """
        Open a visible browser for manual OAuth/SSO login, then export storage_state.
        """
        if not session_file:
            print("[Auth] --session-file is required for --auth-bootstrap.")
            return False
        was_headless = self.headless
        # Bootstrap always visible
        page = None
        try:
            # If browser is headless, user should pass --no-headless; we still prompt.
            page = await self.browser.new_page(slot=0)
            print(f"[Auth/Bootstrap] Opening {url}")
            print("[Auth/Bootstrap] Complete login / OAuth in the browser window.")
            await page.goto(url, wait_until=self.wait_until, timeout=self.timeout)
            ok = await prompt_manual_challenge(
                message="When you are fully logged in, press ENTER to export the session.",
            )
            if not ok:
                return False
            await asyncio.sleep(0.5)
            await self._persist_and_broadcast(seed_url=url, session_override=session_file)
            self._authenticated = True
            if self.profile.auth_check_url:
                return await self.verify(self.profile.auth_check_url)
            return True
        except Exception as exc:
            print(f"[Auth/Bootstrap] Failed: {exc}")
            return False
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            self.headless = was_headless

    async def _login_patchright(self, login_url: str) -> bool:
        page = await self.browser.new_page(slot=0)
        try:
            await page.goto(login_url, wait_until=self.wait_until, timeout=self.timeout)
            await dismiss_popups_patchright(
                page,
                extra_selectors=self.profile.dismiss_selectors or None,
                rounds=4,
            )
            if self.profile.wait_for:
                try:
                    await page.wait_for_selector(self.profile.wait_for, timeout=self.timeout)
                except Exception:
                    print(f"[Auth] wait_for selector not found: {self.profile.wait_for}")

            if self.profile.steps:
                ok = await run_steps_patchright(
                    page,
                    self.profile.steps,
                    username=self.profile.username,
                    password=self.profile.password,
                    totp_secret=self.profile.totp_secret,
                    otp_prompt=self.profile.otp_prompt,
                    dismiss_selectors=self.profile.dismiss_selectors,
                    timeout_ms=self.timeout,
                )
                if not ok:
                    return False
                await asyncio.sleep(1.0)
                # Handle post-step MFA/CAPTCHA
                if await self._handle_mfa_challenge(page):
                    await asyncio.sleep(0.5)
                return not await self.is_auth_wall(page)

            # Standard single-form login
            if self.profile.username_selector and self.profile.password_selector:
                ok = await self._handler.login_with_selectors(
                    page,
                    login_url,
                    self.profile.username,
                    self.profile.password,
                    self.profile.username_selector,
                    self.profile.password_selector,
                    self.profile.submit_selector,
                    timeout=self.timeout,
                    wait_until=self.wait_until,
                )
            else:
                # Already navigated — use fill helpers via login() which navigates again
                # Prefer in-place fill to avoid double navigation:
                ok = await self._handler.login(
                    page,
                    login_url,
                    self.profile.username,
                    self.profile.password,
                    timeout=self.timeout,
                    wait_until=self.wait_until,
                )

            if not ok:
                # Maybe MFA challenge appeared
                if await self._handle_mfa_challenge(page):
                    await asyncio.sleep(1.0)
                    return not await self.is_auth_wall(page)
                return False

            if await self._handle_mfa_challenge(page):
                await asyncio.sleep(0.5)
            return True
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def _handle_mfa_challenge(self, page) -> bool:
        """If CAPTCHA/OTP visible, try TOTP / prompt. Returns True if handled."""
        # OTP field?
        otp_selectors = [
            'input[name="otp"]',
            'input[name="totp"]',
            'input[name="mfa"]',
            'input[name="two_factor"]',
            'input[autocomplete="one-time-code"]',
        ]
        for sel in otp_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=400):
                    code = None
                    if self.profile.totp_secret:
                        code = generate_totp(self.profile.totp_secret)
                        print("[Auth/MFA] Filled TOTP automatically.")
                    elif self.profile.otp_prompt or not self.headless:
                        code = await prompt_otp()
                    if code:
                        await loc.fill(code)
                        # try submit
                        try:
                            await page.keyboard.press("Enter")
                        except Exception:
                            pass
                        await asyncio.sleep(1.0)
                        return True
            except Exception:
                continue

        # CAPTCHA iframe?
        for sel in CAPTCHA_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=300):
                    if self.headless:
                        print(
                            "[Auth/MFA] CAPTCHA detected in headless mode. "
                            "Re-run with --no-headless or --auth-bootstrap."
                        )
                        return False
                    return await prompt_manual_challenge(
                        message="CAPTCHA/challenge detected — solve it in the browser, then press ENTER.",
                    )
            except Exception:
                continue
        return False

    async def _persist_and_broadcast(
        self,
        *,
        seed_url: str,
        session_override: Optional[str] = None,
    ) -> None:
        await asyncio.sleep(0.5)
        cookies = await self.browser.capture_auth_session(slot=0)
        await self.browser.broadcast_auth_session()

        path = session_override or self.profile.session_file
        if not path:
            host = urlparse(seed_url).netloc.replace(":", "_") or "session"
            path = os.path.join("sessions", f"{host}_auth.json")
            self.profile.session_file = path

        state = self.browser._auth_storage_state or {
            "cookies": cookies,
            "origins": [],
        }
        try:
            save_session(
                path,
                state,
                ttl_sec=self.profile.session_ttl,
                seed_url=seed_url,
                mark_verified=True,
            )
            print(f"[Auth] Session saved → {path} ({len(cookies)} cookies)")
        except Exception as exc:
            print(f"[Auth] Warning: could not save session: {exc}")


def build_profile_from_args(args, *, profile_path: Optional[str] = None) -> AuthProfile:
    """Build AuthProfile from CLI args and optional JSON profile/creds file."""
    profile = AuthProfile()
    path = profile_path or getattr(args, "auth_profile", None)
    if path and os.path.isfile(path):
        profile = load_auth_profile(path)

    user, pw = resolve_credentials(
        getattr(args, "username", None) or profile.username,
        getattr(args, "password", None) or profile.password,
    )
    dismiss = getattr(args, "dismiss_selector", None)
    if dismiss:
        profile.dismiss_selectors = list(dismiss)

    profile = merge_cli_into_profile(
        profile,
        username=user or profile.username,
        password=pw if pw is not None else profile.password,
        login_url=getattr(args, "login_url", None) or profile.login_url,
        session_file=getattr(args, "session_file", None) or profile.session_file,
        username_selector=getattr(args, "username_selector", None) or profile.username_selector,
        password_selector=getattr(args, "password_selector", None) or profile.password_selector,
        submit_selector=getattr(args, "submit_selector", None) or profile.submit_selector,
        auth_check_url=getattr(args, "auth_check_url", None) or profile.auth_check_url,
        on_auth_wall=getattr(args, "on_auth_wall", None) or profile.on_auth_wall,
        session_ttl=getattr(args, "session_ttl", None)
        if getattr(args, "session_ttl", None) is not None
        else profile.session_ttl,
        otp_prompt=bool(getattr(args, "otp_prompt", False) or profile.otp_prompt),
    )

    return profile
