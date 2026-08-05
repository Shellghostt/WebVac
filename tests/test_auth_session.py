"""Unit tests for auth session store, wall detection, profile, cookie audit."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from webvac.auth.session_store import (
    normalize_to_storage_state,
    save_session,
    load_session,
    is_expired,
    set_meta,
    cookies_from_state,
)
from webvac.auth.wall import is_auth_wall, is_logout_url, apply_wall_policy
from webvac.auth.profile import profile_from_dict, load_auth_profile
from webvac.auth.cookie_audit import audit_cookies
from webvac.auth.credentials import resolve_credentials, redact_cmd_args
from webvac.utils.browser import BrowserManager


class TestSessionStore(unittest.TestCase):
    def test_normalize_cookie_list(self):
        state = normalize_to_storage_state([{"name": "a", "value": "1", "domain": ".x.com"}])
        self.assertEqual(len(state["cookies"]), 1)
        self.assertEqual(state["origins"], [])

    def test_roundtrip_plaintext(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "s.json")
            state = {"cookies": [{"name": "sid", "value": "abc", "domain": ".ex.com", "path": "/"}], "origins": []}
            save_session(path, state, ttl_sec=3600, seed_url="https://ex.com", mark_verified=True)
            loaded = load_session(path)
            self.assertEqual(cookies_from_state(loaded)[0]["name"], "sid")
            self.assertIn("_webvac_session_meta", loaded)

    def test_expiry(self):
        state = {"cookies": [], "origins": []}
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        set_meta(state, created_at=past, ttl_sec=60)
        self.assertTrue(is_expired(state))
        set_meta(state, created_at=past, ttl_sec=0)
        self.assertFalse(is_expired(state))

    def test_fernet_roundtrip(self):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("cryptography not installed")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "enc.session")
            os.environ["WEBVAC_SESSION_KEY"] = "test-secret-key-for-unit-tests"
            try:
                state = {"cookies": [{"name": "x", "value": "y", "domain": ".t.com", "path": "/"}], "origins": []}
                save_session(path, state, ttl_sec=0)
                with open(path, "rb") as f:
                    raw = f.read()
                self.assertFalse(raw.lstrip().startswith(b"{"))
                loaded = load_session(path)
                self.assertEqual(loaded["cookies"][0]["value"], "y")
            finally:
                os.environ.pop("WEBVAC_SESSION_KEY", None)


class TestWall(unittest.TestCase):
    def test_login_path(self):
        self.assertTrue(is_auth_wall(url="https://x.com/login"))
        self.assertTrue(
            is_auth_wall(
                url="https://x.com/account",
                title="Sign In",
                html='<input type="password" name="pw">',
            )
        )
        self.assertFalse(is_auth_wall(url="https://x.com/dashboard", title="Home", html="<p>hi</p>"))

    def test_amazon_auth_paths(self):
        """Amazon account URLs are walls even with CAPTCHA markup in HTML."""
        captcha_html = '<div class="g-recaptcha"></div><script src="recaptcha/api.js"></script>'
        self.assertTrue(is_auth_wall(url="https://www.amazon.in/ap/signin?openid.ns=x", html=captcha_html))
        self.assertTrue(is_auth_wall(url="https://www.amazon.in/ap/register", title="Amazon Registration"))
        self.assertTrue(is_auth_wall(url="https://www.amazon.com/ap/signin"))

    def test_auth_wall_record_not_failed(self):
        from webvac.auth.wall import make_auth_wall_record

        url = (
            "https://www.amazon.in/ap/signin?openid.return_to="
            "https%3A%2F%2Fwww.amazon.in%2F%3Fref_%3Dnav_ya_signin"
        )
        rec = make_auth_wall_record(url, policy="skip")
        self.assertEqual(rec["status"], "auth_wall")
        self.assertNotEqual(rec["status"], "failed")
        self.assertIn("Auth wall", rec["error"])

    def test_soft_password_title_wall(self):
        self.assertTrue(
            is_auth_wall(
                url="https://shop.example/checkout",
                title="Please Sign In",
                html='<form><input type="password" name="pw"></form>',
            )
        )

    def test_logout(self):
        self.assertTrue(is_logout_url("https://x.com/logout"))
        self.assertTrue(is_logout_url("https://x.com/sign-out?x=1"))
        self.assertFalse(is_logout_url("https://x.com/dashboard"))

    def test_policy(self):
        self.assertEqual(apply_wall_policy("relogin"), "relogin")
        self.assertEqual(apply_wall_policy("nope"), "skip")


class TestBotVsAuthWall(unittest.TestCase):
    def test_login_with_captcha_is_not_bot(self):
        from webvac.utils.detection import is_bot_detected_sync

        html = (
            '<html><title>Amazon Sign-In</title>'
            '<div class="g-recaptcha"></div>'
            '<script src="https://www.google.com/recaptcha/api.js"></script>'
            '<input type="password" name="password">'
            "</html>"
        )
        url = "https://www.amazon.in/ap/signin?openid.return_to=%2F"
        self.assertTrue(is_auth_wall(url=url, title="Amazon Sign-In", html=html))
        self.assertFalse(is_bot_detected_sync(url, "Amazon Sign-In", html))

    def test_real_cf_challenge_still_bot(self):
        from webvac.utils.detection import is_bot_detected_sync

        html = '<html><title>Just a moment...</title><div id="cf-challenge"></div></html>'
        url = "https://example.com/products/1"
        self.assertFalse(is_auth_wall(url=url, title="Just a moment...", html=html))
        self.assertTrue(is_bot_detected_sync(url, "Just a moment...", html))

    def test_page_record_marks_auth_wall(self):
        from webvac.data.page_record import PageRecordBuilder

        html = '<html><title>Sign In</title><input type="password"></html>'
        data = PageRecordBuilder().from_html(
            html, page_url="https://www.amazon.in/ap/signin",
        )
        self.assertEqual(data["status"], "auth_wall")
        self.assertNotEqual(data.get("error"), "Bot/WAF challenge page detected")


class TestProfile(unittest.TestCase):
    def test_parse(self):
        p = profile_from_dict({
            "username": "u",
            "password": "p",
            "steps": [{"fill": "#e", "value": "$username"}],
            "dismiss_selectors": ["#ok"],
            "on_auth_wall": "abort",
            "totp_secret": "JBSWY3DPEHPK3PXP",
        })
        self.assertEqual(len(p.steps), 1)
        self.assertEqual(p.on_auth_wall, "abort")

    def test_nodriver_rejected(self):
        with self.assertRaises(ValueError):
            profile_from_dict({
                "username": "u",
                "password": "p",
                "auth_engine": "nodriver",
            })

    def test_load_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "c.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"username": "a", "password": "b"}, f)
            p = load_auth_profile(path)
            self.assertEqual(p.username, "a")


class TestCookieAudit(unittest.TestCase):
    def test_session_cookie_flags(self):
        issues = audit_cookies([
            {"name": "sessionid", "value": "1", "httpOnly": False, "secure": False},
            {"name": "theme", "value": "dark"},
        ])
        keys = {i["key"] for i in issues}
        self.assertIn("cookie_missing_httponly", keys)
        self.assertIn("cookie_missing_secure", keys)
        # theme should be ignored
        self.assertTrue(all(i["cookie_name"] == "sessionid" for i in issues))


class TestCredentials(unittest.TestCase):
    def test_env_fallback(self):
        os.environ["WEBVAC_USER"] = "envuser"
        os.environ["WEBVAC_PASS"] = "envpass"
        try:
            u, p = resolve_credentials(None, None)
            self.assertEqual(u, "envuser")
            self.assertEqual(p, "envpass")
            u2, p2 = resolve_credentials("cli", "clipass")
            self.assertEqual(u2, "cli")
            self.assertEqual(p2, "clipass")
        finally:
            os.environ.pop("WEBVAC_USER", None)
            os.environ.pop("WEBVAC_PASS", None)

    def test_redact(self):
        args = ["--username", "u", "--password", "secret", "--url", "https://x"]
        out = redact_cmd_args(args)
        self.assertEqual(out[3], "********")


class TestCookieNormalize(unittest.TestCase):
    def test_browser_normalize(self):
        cookies = BrowserManager._normalize_cookies([
            {"name": "a", "value": "1", "domain": ".x.com", "sameSite": "lax"},
            {"name": "bad"},  # missing value
        ])
        self.assertEqual(len(cookies), 1)
        self.assertEqual(cookies[0]["sameSite"], "Lax")


if __name__ == "__main__":
    unittest.main()
