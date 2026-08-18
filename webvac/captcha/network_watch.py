"""Lightweight captcha network fingerprint watcher.

Attaches page request/response listeners and records which captcha provider
scripts/iframes loaded (and any sitekeys in query strings). Independent of
the scrape network debug listener.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlparse

_MAX_EVENTS = 100


@dataclass
class NetworkHint:
    """One captcha-related network observation."""

    family: str  # turnstile | recaptcha | hcaptcha | challenge_page
    sitekey: str = ""
    confidence: float = 40.0
    signals: list[str] = field(default_factory=list)
    url: str = ""
    invisible: bool = False
    enterprise: bool = False
    v3: bool = False
    action: str = ""


def fingerprint_captcha_url(url: str) -> Optional[NetworkHint]:
    """Parse a request/response URL into a NetworkHint, or None if unrelated."""
    raw = (url or "").strip()
    if not raw:
        return None
    lower = raw.lower()

    try:
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
    except Exception:
        qs = {}

    def _q(*names: str) -> str:
        for n in names:
            vals = qs.get(n) or []
            if vals and vals[0]:
                return str(vals[0]).strip()
        return ""

    # Cloudflare interstitial challenge (often not CapSolver-widget-solvable)
    if "challenges.cloudflare.com/cdn-cgi/challenge-platform" in lower or (
        "cdn-cgi/challenge-platform" in lower and "turnstile" not in lower
    ):
        return NetworkHint(
            family="challenge_page",
            confidence=70.0,
            signals=["network_cf_challenge"],
            url=raw[:300],
        )

    # Turnstile widget
    if (
        "challenges.cloudflare.com/turnstile" in lower
        or "/turnstile/v0/api.js" in lower
        or "turnstile/v0/" in lower
    ):
        key = _q("sitekey", "k")
        if not key:
            m = re.search(r"(0x[0-9A-Za-z_-]{10,})", raw)
            if m:
                key = m.group(1)
        return NetworkHint(
            family="turnstile",
            sitekey=key,
            confidence=75.0 if key else 55.0,
            signals=["network_turnstile"],
            url=raw[:300],
        )

    # hCaptcha
    if "hcaptcha.com" in lower or "newassets.hcaptcha.com" in lower:
        key = _q("sitekey", "k")
        return NetworkHint(
            family="hcaptcha",
            sitekey=key,
            confidence=75.0 if key else 55.0,
            signals=["network_hcaptcha"],
            url=raw[:300],
        )

    # reCAPTCHA
    if "recaptcha" not in lower and "gstatic.com/recaptcha" not in lower:
        return None

    enterprise = "enterprise" in lower
    invisible = "size=invisible" in lower or "size%3dinvisible" in lower
    v3 = False
    key = ""
    signals = ["network_recaptcha"]

    if "api.js" in lower or "enterprise.js" in lower:
        render = _q("render")
        if render and render.lower() not in ("explicit", "onload"):
            key = render
            v3 = True
            signals.append("network_recaptcha_v3_render")
        if enterprise:
            signals.append("network_recaptcha_enterprise")

    if "/api2/" in lower or "/enterprise/" in lower:
        key = key or _q("k", "sitekey")
        if "anchor" in lower or "reload" in lower or "bframe" in lower:
            signals.append("network_recaptcha_v2_frame")
        if invisible:
            signals.append("network_recaptcha_invisible")

    if len(signals) <= 1 and not key and not enterprise:
        # bare "recaptcha" mention without actionable signal
        if "google.com/recaptcha" not in lower and "gstatic.com/recaptcha" not in lower:
            return None

    confidence = 50.0
    if key:
        confidence += 25.0
    if enterprise:
        confidence += 5.0
    if v3:
        confidence += 5.0

    return NetworkHint(
        family="recaptcha",
        sitekey=key,
        confidence=min(95.0, confidence),
        signals=signals,
        url=raw[:300],
        invisible=invisible,
        enterprise=enterprise,
        v3=v3,
    )


def _merge_hints(hints: list[NetworkHint]) -> list[NetworkHint]:
    """Dedupe by (family, sitekey), keep highest confidence."""
    best: dict[tuple[str, str], NetworkHint] = {}
    for h in hints:
        key = (h.family, h.sitekey or "")
        prev = best.get(key)
        if prev is None:
            best[key] = h
            continue
        if h.confidence > prev.confidence:
            merged_signals = list(dict.fromkeys(prev.signals + h.signals))
            best[key] = NetworkHint(
                family=h.family,
                sitekey=h.sitekey or prev.sitekey,
                confidence=max(h.confidence, prev.confidence),
                signals=merged_signals,
                url=h.url or prev.url,
                invisible=h.invisible or prev.invisible,
                enterprise=h.enterprise or prev.enterprise,
                v3=h.v3 or prev.v3,
                action=h.action or prev.action,
            )
        else:
            prev.signals = list(dict.fromkeys(prev.signals + h.signals))
            prev.invisible = prev.invisible or h.invisible
            prev.enterprise = prev.enterprise or h.enterprise
            prev.v3 = prev.v3 or h.v3
            if not prev.sitekey and h.sitekey:
                prev.sitekey = h.sitekey
    return sorted(best.values(), key=lambda x: -x.confidence)


class CaptchaNetworkWatcher:
    """Page-scoped captcha URL fingerprint buffer."""

    def __init__(self) -> None:
        self._hints: list[NetworkHint] = []
        self._page = None
        self._attached = False
        self._on_request = None
        self._on_response = None

    @property
    def attached(self) -> bool:
        return self._attached

    def attach(self, page) -> None:
        if self._attached and self._page is page:
            return
        if self._attached:
            self.detach()
        self._page = page
        self._hints = []

        def _ingest(url: str) -> None:
            hint = fingerprint_captcha_url(url)
            if hint is None:
                return
            self._hints.append(hint)
            if len(self._hints) > _MAX_EVENTS:
                self._hints = self._hints[-_MAX_EVENTS:]

        def on_request(request) -> None:
            try:
                _ingest(getattr(request, "url", "") or "")
            except Exception:
                pass

        def on_response(response) -> None:
            try:
                _ingest(getattr(response, "url", "") or "")
            except Exception:
                pass

        self._on_request = on_request
        self._on_response = on_response
        try:
            page.on("request", on_request)
            page.on("response", on_response)
            self._attached = True
        except Exception:
            self._attached = False

    def detach(self) -> None:
        page = self._page
        if page is not None and self._on_request is not None:
            try:
                page.remove_listener("request", self._on_request)
            except Exception:
                pass
        if page is not None and self._on_response is not None:
            try:
                page.remove_listener("response", self._on_response)
            except Exception:
                pass
        self._page = None
        self._on_request = None
        self._on_response = None
        self._attached = False

    def snapshot(self) -> list[NetworkHint]:
        return _merge_hints(list(self._hints))

    def clear(self) -> None:
        self._hints.clear()

    def ingest_url(self, url: str) -> None:
        """Test / manual inject of a URL (no browser)."""
        hint = fingerprint_captcha_url(url)
        if hint:
            self._hints.append(hint)
