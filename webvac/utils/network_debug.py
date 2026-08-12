"""
network_debug.py — Persist scrape network listener dumps for failure diagnosis.

Always-on (unless ``network_debug`` is False). Writes JSON under
``{output_dir}/_network_debug/`` with a summary of failed/challenge requests
and classified challenge types (turnstile / recaptcha_v2 / managed_cf / …)
so operators know when CapSolver can help.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

_CHALLENGE_HINTS = re.compile(
    r"cdn-cgi|challenge|captcha|turnstile|hcaptcha|recaptcha|"
    r"cf-browser|__cf_chl|akamai|bot.?detect|just.?a.?moment|"
    r"datadome|perimeterx|px-captcha|captcha-delivery",
    re.I,
)

# Ordered classifiers: first match wins per haystack segment.
# ``capsolver`` = True when CapSolver (or similar token solvers) can typically help.
_CHALLENGE_CLASSIFIERS: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    (
        "turnstile",
        re.compile(
            r"challenges\.cloudflare\.com|cf-turnstile|turnstile/v0|"
            r"cdn-cgi/challenge-platform/.*/turnstile",
            re.I,
        ),
        True,
    ),
    (
        "hcaptcha",
        re.compile(r"hcaptcha\.com|h-captcha|newassets\.hcaptcha", re.I),
        True,
    ),
    (
        "recaptcha_v3",
        re.compile(
            r"recaptcha/api\.js\?.*render=|grecaptcha\.execute|"
            r"recaptcha/enterprise\.js\?.*render=|size=invisible",
            re.I,
        ),
        True,
    ),
    (
        "recaptcha_enterprise",
        re.compile(r"recaptcha/enterprise|google\.com/recaptcha/enterprise", re.I),
        True,
    ),
    (
        "recaptcha_v2",
        re.compile(
            r"recaptcha/(api2|enterprise)|google\.com/recaptcha|"
            r"gstatic\.com/recaptcha|grecaptcha",
            re.I,
        ),
        True,
    ),
    (
        "managed_cf",
        re.compile(
            r"cdn-cgi/challenge-platform|__cf_chl|cf-browser-verification|"
            r"just.?a.?moment|cf-mitigated|cdn-cgi/l/chk_",
            re.I,
        ),
        False,
    ),
    (
        "akamai",
        re.compile(r"_abck|akamai|/akam/|edgesuite\.net|akamaized\.net", re.I),
        False,
    ),
    (
        "datadome",
        re.compile(r"datadome|dd\.js|captcha-delivery\.com", re.I),
        False,
    ),
    (
        "perimeterx",
        re.compile(r"perimeterx|px-captcha|_px\d|humansecurity|hs-analytics", re.I),
        False,
    ),
)

_CAPSOLVER_TYPES = frozenset(
    {
        "turnstile",
        "hcaptcha",
        "recaptcha_v2",
        "recaptcha_v3",
        "recaptcha_enterprise",
    }
)


def _safe_host(url: str) -> str:
    try:
        host = urlparse(url).netloc.split("@")[-1].split(":")[0]
    except Exception:
        host = "page"
    return re.sub(r"[^\w.\-]+", "_", host) or "page"


def classify_challenge_text(*parts: str) -> Optional[str]:
    """Return the first matching challenge type for concatenated URL/body text."""
    hay = " ".join(p for p in parts if p)
    if not hay:
        return None
    for name, pattern, _ in _CHALLENGE_CLASSIFIERS:
        if pattern.search(hay):
            return name
    if _CHALLENGE_HINTS.search(hay):
        return "unknown_challenge"
    return None


def classify_challenges(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Tag network traffic with challenge types and CapSolver suitability.

    CapSolver helps with widget/token challenges (Turnstile, reCAPTCHA, hCaptcha).
    Managed Cloudflare interstitial / Akamai / DataDome / PerimeterX typically
    need a different approach (proxy, residential sticky, origin, or manual).
    """
    types: set[str] = set()
    tagged: list[dict[str, Any]] = []

    for e in entries:
        url = e.get("request_url") or ""
        body = e.get("body_preview") or ""
        ctype = classify_challenge_text(url, body)
        if not ctype:
            continue
        types.add(ctype)
        tagged.append(
            {
                "type": ctype,
                "status": int(e.get("status") or 0),
                "method": e.get("method"),
                "resource_type": e.get("resource_type"),
                "url": url[:300],
                "capsolver_supported": ctype in _CAPSOLVER_TYPES,
            }
        )

    suitable = sorted(t for t in types if t in _CAPSOLVER_TYPES)
    unsupported = sorted(t for t in types if t not in _CAPSOLVER_TYPES)
    can_help = bool(suitable)

    if not types:
        note = "No challenge traffic classified."
    elif can_help and unsupported:
        note = (
            f"CapSolver may solve {', '.join(suitable)}; "
            f"also saw {', '.join(unsupported)} which CapSolver typically cannot clear."
        )
    elif can_help:
        note = f"CapSolver can typically help with: {', '.join(suitable)}."
    else:
        note = (
            f"Challenge types {', '.join(unsupported)} are not CapSolver widget "
            "targets — try residential sticky proxy, evasion, or manual solve."
        )

    return {
        "challenge_types": sorted(types),
        "capsolver_suitable": suitable,
        "capsolver_unsupported": unsupported,
        "capsolver_can_help": can_help,
        "capsolver_note": note,
        "tagged": tagged[:30],
    }


def summarize_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a compact diagnosis summary from network entries."""
    by_status: dict[str, int] = {}
    failed: list[dict[str, Any]] = []
    challenges: list[dict[str, Any]] = []
    apis: list[dict[str, Any]] = []

    for e in entries:
        st = int(e.get("status") or 0)
        key = str(st) if st else "pending"
        by_status[key] = by_status.get(key, 0) + 1
        url = e.get("request_url") or ""
        rtype = e.get("resource_type") or ""
        body = e.get("body_preview") or ""
        ctype = classify_challenge_text(url, body)
        row = {
            "status": st,
            "method": e.get("method"),
            "type": rtype,
            "url": url[:300],
        }
        if ctype:
            row["challenge"] = ctype
        if st >= 400 or st == 0:
            failed.append(row)
        if ctype or _CHALLENGE_HINTS.search(url) or _CHALLENGE_HINTS.search(body):
            challenges.append(row)
        if rtype in ("xhr", "fetch") or "/api/" in url.lower() or "graphql" in url.lower():
            if st >= 400 or st == 0:
                apis.append(row)

    classification = classify_challenges(entries)

    root_cause_hints: list[str] = []
    if challenges:
        root_cause_hints.append("challenge_or_captcha_traffic")
    for t in classification["challenge_types"]:
        root_cause_hints.append(f"challenge:{t}")
    if classification["capsolver_can_help"]:
        root_cause_hints.append("capsolver_may_help")
    elif classification["challenge_types"]:
        root_cause_hints.append("capsolver_unlikely")
    if any(int(e.get("status") or 0) == 429 for e in entries):
        root_cause_hints.append("rate_limited_429")
    if any(
        int(e.get("status") or 0) in (401, 403)
        for e in entries
        if e.get("resource_type") in ("xhr", "fetch", "document")
    ):
        root_cause_hints.append("auth_or_forbidden")
    if any(int(e.get("status") or 0) >= 500 for e in entries):
        root_cause_hints.append("upstream_5xx")
    if not entries:
        root_cause_hints.append("no_network_events_captured")

    return {
        "entry_count": len(entries),
        "by_status": dict(sorted(by_status.items(), key=lambda x: x[0])),
        "failed_count": len(failed),
        "failed": failed[:40],
        "challenges": challenges[:20],
        "failed_apis": apis[:20],
        "root_cause_hints": root_cause_hints,
        "challenge_classification": classification,
    }


def dump_network_debug(
    *,
    output_dir: str,
    page_url: str,
    reason: str,
    entries: list[dict[str, Any]],
    doc_status: Optional[int] = None,
    final_url: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    Write a network debug JSON file. Returns path or None on failure.
    """
    if not output_dir:
        output_dir = "scraped_data"
    debug_dir = os.path.join(output_dir, "_network_debug")
    try:
        os.makedirs(debug_dir, exist_ok=True)
    except Exception:
        return None

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    host = _safe_host(page_url)
    path = os.path.join(debug_dir, f"{host}_{ts}.json")
    summary = summarize_entries(entries)
    payload = {
        "page_url": page_url,
        "final_url": final_url or page_url,
        "reason": reason,
        "doc_status": doc_status,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "entries": entries,
    }
    if extra:
        payload["extra"] = extra
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        cc = summary.get("challenge_classification") or {}
        types = cc.get("challenge_types") or []
        if types:
            flag = "CapSolver may help" if cc.get("capsolver_can_help") else "CapSolver unlikely"
            print(
                f"[NetworkDebug] {host}: challenges={','.join(types)}  "
                f"({flag}) → {path}"
            )
        return path
    except Exception:
        return None
