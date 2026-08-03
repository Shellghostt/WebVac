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

    def test_logout(self):
        self.assertTrue(is_logout_url("https://x.com/logout"))
        self.assertTrue(is_logout_url("https://x.com/sign-out?x=1"))
        self.assertFalse(is_logout_url("https://x.com/dashboard"))

    def test_policy(self):
        self.assertEqual(apply_wall_policy("relogin"), "relogin")
        self.assertEqual(apply_wall_policy("nope"), "skip")


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
