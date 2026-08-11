"""Unit tests for ProxyManager selection, cooldown, pin_geo, and slot assign."""

from __future__ import annotations

import time
import unittest

from webvac.cli.scraper import _assign_slot_proxies
from webvac.utils.proxy import (
    ProxyEntry,
    ProxyManager,
    classify_proxy_error,
    SOLE_PROXY_WAIT_CAP_SEC,
)


def _pm(*servers: str, strategy: str = "round_robin", pin_geo: bool = True) -> ProxyManager:
    return ProxyManager(
        [ProxyEntry(server=s) for s in servers],
        strategy=strategy,
        cooldown_seconds=60.0,
        max_failures=2,
        max_cooldown_failures=3,
        pin_geo=pin_geo,
    )


class TestClassifyProxyError(unittest.TestCase):
    def test_timeout_transient(self):
        self.assertEqual(classify_proxy_error(TimeoutError("nav timeout")), "transient")

    def test_connection_hard(self):
        self.assertEqual(
            classify_proxy_error(ConnectionRefusedError("Connection refused")),
            "hard",
        )

    def test_unrelated_empty(self):
        self.assertEqual(classify_proxy_error(ValueError("bad html")), "")


class TestGetNextExclude(unittest.TestCase):
    def test_round_robin_skips_excluded(self):
        pm = _pm("http://a:1", "http://b:1", "http://c:1")
        first = pm.get_next()
        second = pm.get_next(exclude=first)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNot(first, second)

    def test_exclude_sequence_unique(self):
        pm = _pm("http://a:1", "http://b:1", "http://c:1", strategy="random")
        a = pm.proxies[0]
        b = pm.proxies[1]
        c = pm.get_next(exclude=[a, b])
        self.assertIs(c, pm.proxies[2])


class TestCooldown(unittest.TestCase):
    def test_cooling_skipped_then_reactivated(self):
        pm = _pm("http://a:1", "http://b:1")
        a, b = pm.proxies
        pm.mark_failure(a, transient=True)
        nxt = pm.get_next(exclude=None)
        self.assertIs(nxt, b)
        a.cooldown_until = time.time() - 1
        nxt2 = pm.get_next()
        self.assertIn(nxt2, (a, b))
        self.assertFalse(a.is_on_cooldown())

    def test_reuse_cooling_if_only(self):
        pm = _pm("http://only:1")
        only = pm.proxies[0]
        pm.mark_failure(only, transient=True)
        self.assertTrue(only.is_on_cooldown())
        self.assertIsNone(pm.get_next(exclude=only, quiet=True))
        reused = pm.get_next(exclude=only, reuse_cooling_if_only=True)
        self.assertIs(reused, only)

    def test_hard_failure_retires(self):
        pm = ProxyManager(
            [ProxyEntry(server="http://a:1")],
            max_failures=2,
            cooldown_seconds=60.0,
        )
        a = pm.proxies[0]
        pm.mark_failure(a, transient=False)
        self.assertFalse(a.is_dead)
        pm.mark_failure(a, transient=False)
        self.assertTrue(a.is_dead)


class TestPinGeo(unittest.TestCase):
    def test_pin_geo_true_sets_timezone(self):
        pm = _pm("http://a:1", pin_geo=True)
        self.assertTrue(pm.proxies[0].pinned_timezone)
        self.assertIsNotNone(pm.proxies[0].pinned_location())

    def test_pin_geo_false_clears_geo(self):
        pm = _pm("http://a:1", pin_geo=False)
        e = pm.proxies[0]
        self.assertTrue(e.pinned_ua)
        self.assertEqual(e.pinned_timezone, "")
        self.assertIsNone(e.pinned_location())


class TestSocksDetect(unittest.TestCase):
    def test_is_socks(self):
        self.assertTrue(ProxyManager.is_socks("socks5://127.0.0.1:1080"))
        self.assertTrue(ProxyManager.is_socks("socks5h://host:1080"))
        self.assertFalse(ProxyManager.is_socks("http://1.2.3.4:8080"))


class TestSlotAssign(unittest.TestCase):
    def test_unique_while_pool_lasts(self):
        pm = _pm("http://a:1", "http://b:1", "http://c:1")
        slots = _assign_slot_proxies(pm, 3, first_entry=pm.proxies[0])
        self.assertEqual(len(slots), 3)
        self.assertEqual(len({id(s) for s in slots}), 3)

    def test_wrap_when_concurrency_exceeds_pool(self):
        pm = _pm("http://a:1", "http://b:1")
        slots = _assign_slot_proxies(pm, 4, first_entry=pm.proxies[0])
        self.assertEqual(len(slots), 4)
        self.assertTrue(all(s is not None for s in slots))
        self.assertLessEqual(len({id(s) for s in slots}), 2)


class TestStickyCounter(unittest.TestCase):
    def test_increment_and_reset(self):
        pm = _pm("http://a:1")
        e = pm.proxies[0]
        self.assertEqual(pm.increment_request_count(e), 1)
        self.assertEqual(pm.increment_request_count(e), 2)
        pm.reset_request_count(e)
        self.assertEqual(e.request_count, 0)

    def test_wait_cap_constant(self):
        self.assertGreater(SOLE_PROXY_WAIT_CAP_SEC, 0)
        self.assertLessEqual(SOLE_PROXY_WAIT_CAP_SEC, 60.0)


if __name__ == "__main__":
    unittest.main()
