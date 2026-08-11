"""
proxy_playbook.py — Named defaults for residential / datacenter proxy usage.

Hooks already exist (sticky sessions, per-proxy pinned UA). Playbooks set
operator-friendly defaults and document geo↔UA↔timezone pinning.
"""

from __future__ import annotations

from typing import Any

# Named playbooks. CLI ``--proxy-playbook`` applies these onto session args
# when the corresponding flags were left at config defaults.
PROXY_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "none": {},
    "residential": {
        # Keep the same exit IP long enough for cookies / rate windows
        "sticky_requests": 25,
        "proxy_strategy": "latency",
        "proxy_cooldown_seconds": 600.0,
        # Geo is pinned per proxy identity (see ProxyManager._assign_identities)
        "rotate_geolocation": False,
        "pin_proxy_geo": True,
    },
    "datacenter": {
        "sticky_requests": 5,
        "proxy_strategy": "round_robin",
        "proxy_cooldown_seconds": 120.0,
        "rotate_geolocation": True,
        "pin_proxy_geo": False,
    },
}


def apply_proxy_playbook(
    playbook: str,
    *,
    sticky_requests: int,
    proxy_strategy: str,
    proxy_cooldown_seconds: float,
    sticky_default: int,
    strategy_default: str,
    cooldown_default: float,
) -> dict[str, Any]:
    """
    Merge playbook defaults over CLI values when those values still match
    global config defaults (so explicit ``--sticky-requests`` wins).
    """
    name = (playbook or "none").strip().lower()
    preset = PROXY_PLAYBOOKS.get(name) or {}
    out: dict[str, Any] = {
        "playbook": name,
        "sticky_requests": sticky_requests,
        "proxy_strategy": proxy_strategy,
        "proxy_cooldown_seconds": proxy_cooldown_seconds,
        "rotate_geolocation": True,
        "pin_proxy_geo": True,
    }
    if not preset:
        return out

    if sticky_requests == sticky_default and "sticky_requests" in preset:
        out["sticky_requests"] = int(preset["sticky_requests"])
    if proxy_strategy == strategy_default and "proxy_strategy" in preset:
        out["proxy_strategy"] = str(preset["proxy_strategy"])
    if (
        float(proxy_cooldown_seconds) == float(cooldown_default)
        and "proxy_cooldown_seconds" in preset
    ):
        out["proxy_cooldown_seconds"] = float(preset["proxy_cooldown_seconds"])
    if "rotate_geolocation" in preset:
        out["rotate_geolocation"] = bool(preset["rotate_geolocation"])
    if "pin_proxy_geo" in preset:
        out["pin_proxy_geo"] = bool(preset["pin_proxy_geo"])
    return out


def playbook_help_text() -> str:
    lines = [
        "Proxy playbook presets:",
        "  residential — sticky=25, latency pick, long cooldown, UA+geo+tz pinned per IP",
        "  datacenter  — sticky=5, round-robin, short cooldown",
        "  none        — no playbook overrides (default)",
        "",
        "Residential tip: use provider sticky-session credentials in the username",
        "(e.g. user-session-abc123) so the ISP IP stays stable for the sticky window.",
    ]
    return "\n".join(lines)
