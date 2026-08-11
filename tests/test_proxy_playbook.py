"""Tests for residential / datacenter proxy playbooks and geo-pinned identities."""

from __future__ import annotations

import unittest

from webvac.config.config import DEFAULT_CONFIG
from webvac.utils.proxy import ProxyEntry, ProxyManager
from webvac.utils.proxy_playbook import apply_proxy_playbook


class TestProxyPlaybook(unittest.TestCase):
    def test_residential_overrides_defaults(self):
        out = apply_proxy_playbook(
            "residential",
            sticky_requests=DEFAULT_CONFIG["sticky_requests"],
            proxy_strategy=DEFAULT_CONFIG["proxy_strategy"],
            proxy_cooldown_seconds=DEFAULT_CONFIG["proxy_cooldown_seconds"],
            sticky_default=DEFAULT_CONFIG["sticky_requests"],
            strategy_default=DEFAULT_CONFIG["proxy_strategy"],
            cooldown_default=DEFAULT_CONFIG["proxy_cooldown_seconds"],
        )
        self.assertEqual(out["sticky_requests"], 25)
        self.assertEqual(out["proxy_cooldown_seconds"], 600.0)
        self.assertTrue(out["pin_proxy_geo"])
        self.assertFalse(out["rotate_geolocation"])

    def test_explicit_sticky_wins(self):
        out = apply_proxy_playbook(
            "residential",
            sticky_requests=99,
            proxy_strategy=DEFAULT_CONFIG["proxy_strategy"],
            proxy_cooldown_seconds=DEFAULT_CONFIG["proxy_cooldown_seconds"],
            sticky_default=DEFAULT_CONFIG["sticky_requests"],
            strategy_default=DEFAULT_CONFIG["proxy_strategy"],
            cooldown_default=DEFAULT_CONFIG["proxy_cooldown_seconds"],
        )
        self.assertEqual(out["sticky_requests"], 99)

    def test_proxy_identity_includes_geo(self):
        pm = ProxyManager([ProxyEntry(server="http://127.0.0.1:9")])
        e = pm.proxies[0]
        self.assertTrue(e.pinned_ua)
        self.assertTrue(e.pinned_timezone)
        loc = e.pinned_location()
        self.assertIsNotNone(loc)
        assert loc is not None
        self.assertEqual(loc[3], e.pinned_timezone)

    def test_datacenter_playbook_disables_geo_pin(self):
        out = apply_proxy_playbook(
            "datacenter",
            sticky_requests=DEFAULT_CONFIG["sticky_requests"],
            proxy_strategy=DEFAULT_CONFIG["proxy_strategy"],
            proxy_cooldown_seconds=DEFAULT_CONFIG["proxy_cooldown_seconds"],
            sticky_default=DEFAULT_CONFIG["sticky_requests"],
            strategy_default=DEFAULT_CONFIG["proxy_strategy"],
            cooldown_default=DEFAULT_CONFIG["proxy_cooldown_seconds"],
        )
        self.assertFalse(out["pin_proxy_geo"])
        self.assertTrue(out["rotate_geolocation"])
        self.assertEqual(out["sticky_requests"], 5)


if __name__ == "__main__":
    unittest.main()
