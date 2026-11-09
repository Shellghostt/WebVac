"""Unit tests for proxy parsing, selection strategies, and failure tracking.

Everything here is deterministic and offline: no benchmark or network call
is made, and latency values are set directly on the entries under test.
"""

import time

import pytest

from webvac.utils.proxy import (
    ProxyEntry,
    ProxyManager,
    classify_proxy_error,
    proxy_entry_to_url,
)


def make_manager(servers, **kwargs):
    return ProxyManager.from_strings(servers, **kwargs)


class TestParseLine:
    def test_plain_server(self):
        entry = ProxyManager._parse_line("http://1.2.3.4:8080")
        assert entry.server == "http://1.2.3.4:8080"
        assert entry.username == ""
        assert entry.password == ""

    def test_server_with_credentials(self):
        entry = ProxyManager._parse_line("socks5://host:1080|alice|secret")
        assert entry.server == "socks5://host:1080"
        assert entry.username == "alice"
        assert entry.password == "secret"

    def test_whitespace_is_stripped(self):
        entry = ProxyManager._parse_line("  http://h:1 | bob | pw ")
        assert (entry.server, entry.username, entry.password) == (
            "http://h:1",
            "bob",
            "pw",
        )


class TestFromStrings:
    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            ProxyManager.from_strings([])

    def test_blank_lines_are_skipped(self):
        manager = make_manager(["", "  ", "http://1.2.3.4:8080"])
        assert len(manager.proxies) == 1

    def test_empty_manager_rejected(self):
        with pytest.raises(ValueError):
            ProxyManager([])


class TestEntryUrls:
    def test_to_url_without_credentials_returns_server(self):
        assert ProxyEntry("http://h:8080").to_url() == "http://h:8080"

    def test_to_url_embeds_quoted_credentials(self):
        entry = ProxyEntry("http://h:8080", username="user@x", password="p w")
        assert entry.to_url() == "http://user%40x:p%20w@h:8080"

    def test_to_patchright_omits_empty_credentials(self):
        assert ProxyEntry("http://h:8080").to_patchright() == {"server": "http://h:8080"}
        entry = ProxyEntry("http://h:8080", username="u", password="p")
        assert entry.to_patchright() == {
            "server": "http://h:8080",
            "username": "u",
            "password": "p",
        }

    def test_is_socks(self):
        assert ProxyManager.is_socks("socks5://h:1080")
        assert ProxyManager.is_socks("SOCKS4://h:1080")
        assert not ProxyManager.is_socks("http://h:8080")

    def test_socks_url_defaults_port_and_quotes_credentials(self):
        entry = ProxyEntry("socks5://h", username="u@x", password="p")
        assert ProxyManager._socks_url(entry) == "socks5://u%40x:p@h:1080"

    def test_proxy_entry_to_url_handles_none(self):
        assert proxy_entry_to_url(None) is None
        assert proxy_entry_to_url(ProxyEntry("http://h:1", "u", "p")) == "http://u:p@h:1"


class TestSelection:
    def test_round_robin_cycles_in_order(self):
        manager = make_manager(
            ["http://a:1", "http://b:2", "http://c:3"], strategy="round_robin"
        )
        picked = [manager.get_next().server for _ in range(4)]
        assert picked == ["http://a:1", "http://b:2", "http://c:3", "http://a:1"]

    def test_round_robin_skips_excluded_and_cooling(self):
        manager = make_manager(["http://a:1", "http://b:2"], strategy="round_robin")
        first = manager.get_next()
        assert manager.get_next(exclude=first).server != first.server

    def test_random_strategy_returns_active_proxy(self):
        manager = make_manager(["http://a:1", "http://b:2"], strategy="random")
        for _ in range(10):
            assert manager.get_next().server in {"http://a:1", "http://b:2"}

    def test_latency_strategy_prefers_fastest_third(self):
        manager = make_manager(
            ["http://slow:1", "http://mid:2", "http://fast:3"], strategy="latency"
        )
        latencies = {"http://slow:1": 900.0, "http://mid:2": 500.0, "http://fast:3": 50.0}
        for entry in manager.proxies:
            entry.latency_ms = latencies[entry.server]
        for _ in range(10):
            assert manager.get_next().server == "http://fast:3"

    def test_no_active_proxies_returns_none(self):
        manager = make_manager(["http://a:1"])
        manager.proxies[0].is_dead = True
        assert manager.get_next(quiet=True) is None

    def test_cooling_proxy_reactivates_after_expiry(self):
        manager = make_manager(["http://a:1"], cooldown_seconds=60)
        entry = manager.proxies[0]
        manager.mark_failure(entry, transient=True)
        assert manager.get_next(quiet=True) is None
        entry.cooldown_until = time.time() - 1
        assert manager.get_next(quiet=True) is entry

    def test_reuse_cooling_if_only_returns_soonest(self):
        manager = make_manager(["http://a:1", "http://b:2"])
        for entry in manager.proxies:
            entry.cooldown_until = time.time() + 120
        manager.proxies[1].cooldown_until = time.time() + 30
        picked = manager.get_next(reuse_cooling_if_only=True, quiet=True)
        assert picked is manager.proxies[1]


class TestFailureTracking:
    def test_transient_failures_retire_after_max_cooldown_strikes(self):
        manager = make_manager(["http://a:1"], max_cooldown_failures=2)
        entry = manager.proxies[0]
        manager.mark_failure(entry, transient=True)
        assert not entry.is_dead
        entry.cooldown_until = 0.0
        manager.mark_failure(entry, transient=True)
        assert entry.is_dead

    def test_hard_failures_retire_after_max_failures(self):
        manager = make_manager(["http://a:1"], max_failures=2)
        entry = manager.proxies[0]
        manager.mark_failure(entry, transient=False)
        assert not entry.is_dead
        manager.mark_failure(entry, transient=False)
        assert entry.is_dead

    def test_mark_success_resets_counters(self):
        manager = make_manager(["http://a:1"])
        entry = manager.proxies[0]
        manager.mark_failure(entry, transient=True)
        manager.mark_failure(entry, transient=False)
        manager.mark_success(entry)
        assert entry.failures == 0
        assert entry.consecutive_cooldown_failures == 0

    def test_dead_proxy_ignores_further_failures(self):
        manager = make_manager(["http://a:1"])
        entry = manager.proxies[0]
        entry.is_dead = True
        manager.mark_failure(entry, transient=False)
        assert entry.failures == 0


class TestLatency:
    def test_first_measurement_replaces_sentinel(self):
        manager = make_manager(["http://a:1"])
        entry = manager.proxies[0]
        manager.update_latency(entry, 120.0)
        assert entry.latency_ms == 120.0

    def test_ema_blends_subsequent_measurements(self):
        manager = make_manager(["http://a:1"])
        entry = manager.proxies[0]
        manager.update_latency(entry, 100.0)
        manager.update_latency(entry, 200.0, alpha=0.3)
        assert entry.latency_ms == pytest.approx(130.0)


class TestStatusAndClassify:
    def test_status_counts(self):
        manager = make_manager(["http://a:1", "http://b:2", "http://c:3"])
        manager.proxies[1].cooldown_until = time.time() + 60
        manager.proxies[2].is_dead = True
        assert manager.status() == "1 active / 1 cooling / 1 dead / 3 total"

    def test_classify_timeout_is_transient(self):
        assert classify_proxy_error(TimeoutError("timed out")) == "transient"

    def test_classify_connection_refused_is_hard(self):
        assert classify_proxy_error(OSError("ECONNREFUSED")) == "hard"

    def test_classify_unrelated_error_is_empty(self):
        assert classify_proxy_error(ValueError("boom")) == ""
