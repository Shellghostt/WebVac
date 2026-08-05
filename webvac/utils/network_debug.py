"""
network_debug.py — Persist scrape network listener dumps for failure diagnosis.

Always-on (unless ``network_debug`` is False). Writes JSON under
``{output_dir}/_network_debug/`` with a summary of failed/challenge requests.
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
    r"cf-browser|__cf_chl|akamai|bot.?detect|just.?a.?moment",
    re.I,
)


def _safe_host(url: str) -> str:
    try:
        host = urlparse(url).netloc.split("@")[-1].split(":")[0]
    except Exception:
        host = "page"
    return re.sub(r"[^\w.\-]+", "_", host) or "page"


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
        row = {
            "status": st,
            "method": e.get("method"),
            "type": rtype,
            "url": url[:300],
        }
        if st >= 400 or st == 0:
            failed.append(row)
        if _CHALLENGE_HINTS.search(url) or _CHALLENGE_HINTS.search(e.get("body_preview") or ""):
            challenges.append(row)
        if rtype in ("xhr", "fetch") or "/api/" in url.lower() or "graphql" in url.lower():
            if st >= 400 or st == 0:
                apis.append(row)

    root_cause_hints: list[str] = []
    if challenges:
        root_cause_hints.append("challenge_or_captcha_traffic")
    if any(int(e.get("status") or 0) == 429 for e in entries):
        root_cause_hints.append("rate_limited_429")
    if any(int(e.get("status") or 0) in (401, 403) for e in entries if e.get("resource_type") in ("xhr", "fetch", "document")):
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
        return path
    except Exception:
        return None
