"""Unit tests for CapSolver captcha stack (no live API)."""

from __future__ import annotations

import unittest

from webvac.captcha.config import CaptchaSolverConfig
from webvac.captcha.models import CaptchaInfo, CaptchaType, SolverResult
from webvac.captcha.providers.capsolver import (
    build_capsolver_task,
    parse_capsolver_solution,
    _format_proxy,
)


class TestCaptchaConfig(unittest.TestCase):
    def test_disabled_by_default(self):
        cfg = CaptchaSolverConfig.from_mapping({}, load_files=False)
        self.assertFalse(cfg.enabled)

    def test_enabled_with_provider_and_key(self):
        cfg = CaptchaSolverConfig.from_mapping({
            "captcha_solver": "capsolver",
            "captcha_api_key": "test-key-1234",
        }, load_files=False)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.provider, "capsolver")

    def test_explicit_none_disables_even_with_key(self):
        cfg = CaptchaSolverConfig.from_mapping({
            "captcha_solver": "none",
            "captcha_api_key": "test-key-1234",
            "captcha_solver_disabled": True,
        }, load_files=False)
        self.assertFalse(cfg.enabled)

    def test_key_auto_enables_when_default_none(self):
        cfg = CaptchaSolverConfig.from_mapping({
            "captcha_solver": "none",
            "captcha_api_key": "test-key-1234",
        }, load_files=False)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.provider, "capsolver")

    def test_key_file_parsed(self):
        import tempfile
        from pathlib import Path
        from webvac.captcha.config import load_capsolver_key_from_files

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "capsolver.key"
            p.write_text("# comment\nCAPSOLVER_API_KEY=sk-live-abc\n", encoding="utf-8")
            key = load_capsolver_key_from_files(extra_paths=[str(p)])
            self.assertEqual(key, "sk-live-abc")

    def test_bare_key_file_parsed(self):
        import tempfile
        from pathlib import Path
        from webvac.captcha.config import load_capsolver_key_from_files

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "capsolver.key"
            p.write_text("sk-bare-key\n", encoding="utf-8")
            self.assertEqual(load_capsolver_key_from_files(extra_paths=[str(p)]), "sk-bare-key")


class TestCapSolverTaskBuilder(unittest.TestCase):
    """All six reCAPTCHA demo variants + Turnstile / hCaptcha."""

    def test_recaptcha_v2(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V2,
            website_url="https://2captcha.com/demo/recaptcha-v2",
            website_key="6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u",
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "ReCaptchaV2TaskProxyLess")
        self.assertNotIn("isInvisible", task)

    def test_recaptcha_v2_invisible(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V2_INVISIBLE,
            website_url="https://2captcha.com/demo/recaptcha-v2-invisible",
            website_key="6LdO5_IbAAAAAAeVBL9TClS19NUTt5wswEb3Q7C5",
            is_invisible=True,
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "ReCaptchaV2TaskProxyLess")
        self.assertTrue(task.get("isInvisible"))

    def test_recaptcha_v2_callback(self):
        # Same CapSolver task as v2; callback is an inject concern
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V2_CALLBACK,
            website_url="https://2captcha.com/demo/recaptcha-v2-callback",
            website_key="6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u",
            extra={"callback": "verifyDemoRecaptcha"},
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "ReCaptchaV2TaskProxyLess")

    def test_recaptcha_v2_enterprise(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V2_ENTERPRISE,
            website_url="https://2captcha.com/demo/recaptcha-v2-enterprise",
            website_key="6LcAAAAA",
            is_enterprise=True,
            extra={"s": "enterprise-s-token-value-here"},
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "ReCaptchaV2EnterpriseTaskProxyLess")
        self.assertEqual(task.get("enterprisePayload"), {"s": "enterprise-s-token-value-here"})

    def test_recaptcha_v3(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V3,
            website_url="https://2captcha.com/demo/recaptcha-v3",
            website_key="6LcAAAAA",
            page_action="homepage",
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "ReCaptchaV3TaskProxyLess")
        self.assertEqual(task["pageAction"], "homepage")
        self.assertEqual(task["minScore"], 0.7)

    def test_recaptcha_v3_enterprise(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V3_ENTERPRISE,
            website_url="https://2captcha.com/demo/recaptcha-v3-enterprise",
            website_key="6LcAAAAA",
            page_action="login",
            is_enterprise=True,
            extra={"s": "v3-enterprise-s"},
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "ReCaptchaV3EnterpriseTaskProxyLess")
        self.assertEqual(task["pageAction"], "login")
        self.assertEqual(task.get("enterprisePayload"), {"s": "v3-enterprise-s"})

    def test_all_six_recaptcha_types_mapped(self):
        expected = {
            CaptchaType.RECAPTCHA_V2: "ReCaptchaV2TaskProxyLess",
            CaptchaType.RECAPTCHA_V2_INVISIBLE: "ReCaptchaV2TaskProxyLess",
            CaptchaType.RECAPTCHA_V2_CALLBACK: "ReCaptchaV2TaskProxyLess",
            CaptchaType.RECAPTCHA_V2_ENTERPRISE: "ReCaptchaV2EnterpriseTaskProxyLess",
            CaptchaType.RECAPTCHA_V3: "ReCaptchaV3TaskProxyLess",
            CaptchaType.RECAPTCHA_V3_ENTERPRISE: "ReCaptchaV3EnterpriseTaskProxyLess",
        }
        for ctype, task_type in expected.items():
            info = CaptchaInfo(
                captcha_type=ctype,
                website_url="https://example.com/",
                website_key="6LcAAAAA",
                page_action="verify",
                is_enterprise="enterprise" in ctype.value,
                is_invisible="invisible" in ctype.value or "v3" in ctype.value,
            )
            task = build_capsolver_task(info)
            self.assertEqual(task["type"], task_type, msg=ctype.value)

    def test_turnstile(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.TURNSTILE,
            website_url="https://example.com/",
            website_key="0x4AAAA",
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "AntiTurnstileTaskProxyLess")

    def test_turnstile_metadata_action(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.TURNSTILE,
            website_url="https://example.com/login",
            website_key="0x4AAAAAAAUltW_516cjiM-8",
            page_action="login-form",
        )
        task = build_capsolver_task(info)
        self.assertEqual(task.get("metadata"), {"action": "login-form"})
        self.assertNotIn("action", task)

    def test_hcaptcha(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.HCAPTCHA,
            website_url="https://example.com/",
            website_key="a1b2c3",
        )
        task = build_capsolver_task(info)
        self.assertEqual(task["type"], "HCaptchaTaskProxyLess")

    def test_parse_solution(self):
        token = "x" * 50
        data = {"status": "ready", "solution": {"gRecaptchaResponse": token}}
        self.assertEqual(parse_capsolver_solution(data), token)

    def test_proxy_pipe_format(self):
        self.assertEqual(
            _format_proxy("http://1.2.3.4:8080|user|pass"),
            "http://user:pass@1.2.3.4:8080",
        )


class TestCaptchaInfo(unittest.TestCase):
    def test_solvable(self):
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V2,
            website_url="https://x.com",
            website_key="abc",
        )
        self.assertTrue(info.solvable)
        bad = CaptchaInfo(captcha_type=CaptchaType.UNKNOWN, website_url="https://x.com")
        self.assertFalse(bad.solvable)


class TestInjectSmartReload(unittest.TestCase):
    def test_turnstile_needs_reload(self):
        import asyncio
        from webvac.captcha.inject import should_reload_after_inject

        info = CaptchaInfo(captcha_type=CaptchaType.TURNSTILE, website_url="https://x.com", website_key="k")
        self.assertTrue(asyncio.run(should_reload_after_inject(info)))

    def test_recaptcha_v2_no_reload(self):
        import asyncio
        from webvac.captcha.inject import should_reload_after_inject

        info = CaptchaInfo(captcha_type=CaptchaType.RECAPTCHA_V2, website_url="https://x.com", website_key="k")
        self.assertFalse(asyncio.run(should_reload_after_inject(info)))

    def test_form_embedded_turnstile_no_reload(self):
        import asyncio
        from webvac.captcha.inject import should_reload_after_inject

        class FakePage:
            async def evaluate(self, _js):
                return True  # login form + turnstile fields

        info = CaptchaInfo(
            captcha_type=CaptchaType.TURNSTILE,
            website_url="https://www.chess.com/login_and_go",
            website_key="0x4AAAAAAAUltW_516cjiM-8",
        )
        self.assertFalse(asyncio.run(should_reload_after_inject(info, FakePage())))


class TestChessComAuthSelectors(unittest.TestCase):
    def test_chess_selectors_preferred(self):
        from webvac.auth.auth import (
            USERNAME_SELECTORS,
            PASSWORD_SELECTORS,
            SUBMIT_SELECTORS,
            CAPTCHA_WIDGET_SELECTORS,
        )

        self.assertEqual(USERNAME_SELECTORS[0], "#login-username")
        self.assertEqual(PASSWORD_SELECTORS[0], "#login-password")
        self.assertIn("button#login", SUBMIT_SELECTORS)
        self.assertIn('input[name="cf-turnstile-response"]', CAPTCHA_WIDGET_SELECTORS)
        self.assertIn("#turnstile_token", CAPTCHA_WIDGET_SELECTORS)


class TestTurnstileSitekeyFallback(unittest.TestCase):
    def test_config_style_sitekey_in_fallback_js(self):
        from webvac.captcha.extract import _SITEKEY_FALLBACK_JS

        self.assertIn("turnstile.sitekey", _SITEKEY_FALLBACK_JS)
        self.assertIn("window.Config", _SITEKEY_FALLBACK_JS)

    def test_detect_js_covers_all_recaptcha_variants(self):
        from webvac.captcha.detect import _DETECT_JS, _map_type
        from webvac.captcha.models import CaptchaType

        for raw, expected in [
            ("recaptcha_v2", CaptchaType.RECAPTCHA_V2),
            ("recaptcha_v2_invisible", CaptchaType.RECAPTCHA_V2_INVISIBLE),
            ("recaptcha_v2_callback", CaptchaType.RECAPTCHA_V2_CALLBACK),
            ("recaptcha_v2_enterprise", CaptchaType.RECAPTCHA_V2_ENTERPRISE),
            ("recaptcha_v3", CaptchaType.RECAPTCHA_V3),
            ("recaptcha_v3_enterprise", CaptchaType.RECAPTCHA_V3_ENTERPRISE),
        ]:
            self.assertEqual(_map_type(raw), expected)
            self.assertIn(raw, _DETECT_JS)

        self.assertIn("___grecaptcha_cfg", _DETECT_JS)
        self.assertIn("grecaptcha.enterprise", _DETECT_JS)
        self.assertIn("data-callback", _DETECT_JS)

    def test_detect_js_turnstile_action_is_generic(self):
        from webvac.captcha.detect import _DETECT_JS

        # Must not hard-require chess.com for Turnstile action
        self.assertIn("turnstile.render", _DETECT_JS.lower().replace("\\", ""))
        self.assertIn("data-action", _DETECT_JS)
        self.assertNotIn("if (host === 'chess.com')", _DETECT_JS)

    def test_inject_js_follows_2captcha_patterns(self):
        from webvac.captcha.inject import _INJECT_JS

        self.assertIn("cf-turnstile-response", _INJECT_JS)
        self.assertIn("g-recaptcha-response", _INJECT_JS)
        self.assertIn("___grecaptcha_cfg", _INJECT_JS)
        self.assertIn("data-callback", _INJECT_JS)
        self.assertIn("knownCallback", _INJECT_JS)


class TestProxyEntryUrl(unittest.TestCase):
    def test_to_url_with_creds(self):
        from webvac.utils.proxy import ProxyEntry
        e = ProxyEntry(server="http://1.2.3.4:8080", username="user", password="pass")
        url = e.to_url()
        self.assertIn("user:pass@", url)
        self.assertIn("1.2.3.4:8080", url)

    def test_to_url_no_creds(self):
        from webvac.utils.proxy import ProxyEntry
        e = ProxyEntry(server="http://1.2.3.4:8080")
        self.assertEqual(e.to_url(), "http://1.2.3.4:8080")


class TestDetectionAuthWallFirst(unittest.TestCase):
    def test_sync_auth_wall_before_status(self):
        from webvac.utils.detection import is_bot_detected_sync
        result = is_bot_detected_sync(
            url="https://example.com/login",
            title="Sign In",
            body='<input type="password">',
            status=403,
        )
        self.assertFalse(result, "Login page with 403 should NOT be flagged as bot")

    def test_sync_real_403_is_bot(self):
        from webvac.utils.detection import is_bot_detected_sync
        result = is_bot_detected_sync(
            url="https://example.com/data",
            title="Forbidden",
            body="<p>Access denied</p>",
            status=403,
        )
        self.assertTrue(result)


class TestErrorSelectorsNarrow(unittest.TestCase):
    def test_no_generic_error_class(self):
        from webvac.auth.auth import ERROR_SELECTORS
        for sel in ERROR_SELECTORS:
            self.assertNotIn('[class*="error"]', sel, "Generic [class*=error] causes false login failures")
            self.assertNotIn('[role="alert"]', sel, "Generic [role=alert] causes false login failures")


class TestNetworkFingerprint(unittest.TestCase):
    def test_recaptcha_v3_render(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://www.google.com/recaptcha/api.js?render=6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.family, "recaptcha")
        self.assertTrue(hint.v3)
        self.assertEqual(hint.sitekey, "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI")

    def test_recaptcha_v2_anchor_k(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://www.google.com/recaptcha/api2/anchor?k=6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u&size=normal"
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.family, "recaptcha")
        self.assertFalse(hint.v3)
        self.assertEqual(hint.sitekey, "6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u")
        self.assertIn("network_recaptcha_v2_frame", hint.signals)

    def test_recaptcha_invisible(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://www.google.com/recaptcha/api2/anchor?k=6Lfxxx&size=invisible"
        )
        self.assertIsNotNone(hint)
        self.assertTrue(hint.invisible)

    def test_enterprise(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://www.google.com/recaptcha/enterprise.js?render=6LeEnterpriseKey"
        )
        self.assertIsNotNone(hint)
        self.assertTrue(hint.enterprise)
        self.assertTrue(hint.v3)
        self.assertEqual(hint.sitekey, "6LeEnterpriseKey")

    def test_hcaptcha(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://js.hcaptcha.com/1/api.js?sitekey=10000000-ffff-ffff-ffff-000000000001"
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.family, "hcaptcha")
        self.assertEqual(hint.sitekey, "10000000-ffff-ffff-ffff-000000000001")

    def test_turnstile(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://challenges.cloudflare.com/turnstile/v0/api.js?sitekey=0x4AAAAAAADemoKey"
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.family, "turnstile")
        self.assertEqual(hint.sitekey, "0x4AAAAAAADemoKey")

    def test_challenge_platform(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        hint = fingerprint_captcha_url(
            "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.family, "challenge_page")
        self.assertFalse(hint.sitekey)

    def test_unrelated_url(self):
        from webvac.captcha.network_watch import fingerprint_captcha_url

        self.assertIsNone(fingerprint_captcha_url("https://example.com/static/app.js"))


class TestMergeRanking(unittest.TestCase):
    def test_network_recaptcha_beats_dom_turnstile_leftover(self):
        from webvac.captcha.extract import merge_dom_and_network
        from webvac.captcha.network_watch import NetworkHint

        page_url = "https://example.com/protected"
        dom = [
            CaptchaInfo(
                captcha_type=CaptchaType.TURNSTILE,
                website_url=page_url,
                website_key="0x4AAAAAAAleftover",
                confidence=40.0,
                signals=["script_turnstile"],
            ),
        ]
        hints = [
            NetworkHint(
                family="recaptcha",
                sitekey="6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u",
                confidence=75.0,
                signals=["network_recaptcha", "network_recaptcha_v2_frame"],
                url="https://www.google.com/recaptcha/api2/anchor?k=6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u",
            ),
        ]
        ranked = merge_dom_and_network(dom, hints, page_url=page_url)
        self.assertTrue(ranked)
        self.assertTrue(ranked[0].is_recaptcha)
        self.assertEqual(ranked[0].website_key, "6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u")
        self.assertGreater(ranked[0].confidence, 40.0)

    def test_network_boosts_matching_dom(self):
        from webvac.captcha.extract import merge_dom_and_network
        from webvac.captcha.network_watch import NetworkHint

        page_url = "https://example.com/"
        key = "6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u"
        dom = [
            CaptchaInfo(
                captcha_type=CaptchaType.RECAPTCHA_V2,
                website_url=page_url,
                website_key=key,
                confidence=55.0,
                signals=["dom_widget"],
            ),
        ]
        hints = [
            NetworkHint(
                family="recaptcha",
                sitekey=key,
                confidence=70.0,
                signals=["network_recaptcha_v2_frame"],
            ),
        ]
        ranked = merge_dom_and_network(dom, hints, page_url=page_url)
        self.assertEqual(len(ranked), 1)
        self.assertGreaterEqual(ranked[0].confidence, 55.0 + 30.0 - 0.1)
        self.assertIn("network_recaptcha_v2_frame", ranked[0].signals)

    def test_challenge_without_sitekey_unsolvable(self):
        from webvac.captcha.extract import merge_dom_and_network
        from webvac.captcha.network_watch import NetworkHint

        page_url = "https://example.com/"
        hints = [
            NetworkHint(
                family="challenge_page",
                confidence=70.0,
                signals=["network_cf_challenge"],
            ),
        ]
        ranked = merge_dom_and_network([], hints, page_url=page_url)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].captcha_type, CaptchaType.CHALLENGE_PAGE)
        self.assertFalse(ranked[0].solvable)

    def test_challenge_dropped_when_solvable_exists(self):
        from webvac.captcha.extract import merge_dom_and_network
        from webvac.captcha.network_watch import NetworkHint

        page_url = "https://example.com/"
        dom = [
            CaptchaInfo(
                captcha_type=CaptchaType.TURNSTILE,
                website_url=page_url,
                website_key="0x4AAAAAAAwidget",
                confidence=80.0,
                signals=["dom_turnstile"],
            ),
        ]
        hints = [
            NetworkHint(family="challenge_page", confidence=70.0, signals=["network_cf_challenge"]),
        ]
        ranked = merge_dom_and_network(dom, hints, page_url=page_url)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].captcha_type, CaptchaType.TURNSTILE)
        self.assertTrue(ranked[0].solvable)


class TestVariantRemaps(unittest.TestCase):
    def test_v2_remaps(self):
        from webvac.captcha.extract import variant_remaps

        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V2,
            website_url="https://example.com/",
            website_key="6Lfkey",
        )
        types = {a.captcha_type for a in variant_remaps(info)}
        self.assertIn(CaptchaType.RECAPTCHA_V2_INVISIBLE, types)
        self.assertIn(CaptchaType.RECAPTCHA_V2_CALLBACK, types)
        self.assertNotIn(CaptchaType.RECAPTCHA_V2, types)

    def test_v3_enterprise_swap(self):
        from webvac.captcha.extract import variant_remaps

        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA_V3,
            website_url="https://example.com/",
            website_key="6Lfkey",
            page_action="submit",
        )
        alts = variant_remaps(info)
        self.assertEqual(len(alts), 1)
        self.assertEqual(alts[0].captcha_type, CaptchaType.RECAPTCHA_V3_ENTERPRISE)
        self.assertTrue(alts[0].is_enterprise)

    def test_type_mismatch_error(self):
        from webvac.captcha.extract import is_type_mismatch_error

        self.assertTrue(is_type_mismatch_error("InvalidRequestError: check captcha type"))
        self.assertTrue(is_type_mismatch_error("ERROR: sitekey is not supported for this task"))
        self.assertFalse(is_type_mismatch_error("timeout waiting for solution"))
        self.assertFalse(is_type_mismatch_error(None))


if __name__ == "__main__":
    unittest.main()
