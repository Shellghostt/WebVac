"""
Scan profiles — preset bundles of collectors, analyzers, and active recon flags.

CLI: --profile standard  (individual flags override profile defaults)
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PROFILE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "quick": {
        "description": "Fast passive snapshot: HTML, headers, cookies",
        "collectors": {
            "http": True,
            "html": True,
            "storage": True,
            "network": False,
            "javascript": False,
        },
        "analyzers": {
            "headers": True,
            "cookies": True,
            "auth": False,
            "storage": False,
            "js": False,
            "sourcemap": False,
            "network": False,
            "tech": False,
            "graphql": False,
            "oauth": False,
            "cloud": False,
            "html": True,
        },
        "active_recon": False,
        "javascript": {
            "download_external": False,
            "fetch_source_maps": False,
        },
    },
    "standard": {
        "description": "Full passive recon: network, JS discovery, analysis",
        "collectors": {
            "http": True,
            "html": True,
            "storage": True,
            "network": True,
            "javascript": True,
        },
        "analyzers": {
            "headers": True,
            "cookies": True,
            "auth": True,
            "storage": True,
            "js": True,
            "sourcemap": False,
            "network": True,
            "tech": True,
            "graphql": False,
            "oauth": False,
            "cloud": False,
            "html": True,
        },
        "active_recon": False,
        "javascript": {
            "download_external": True,
            "fetch_source_maps": False,
            "concurrency": 5,
        },
    },
    "deep": {
        "description": "Standard + source maps + active reconnaissance",
        "collectors": {
            "http": True,
            "html": True,
            "storage": True,
            "network": True,
            "javascript": True,
        },
        "analyzers": {
            "headers": True,
            "cookies": True,
            "auth": True,
            "storage": True,
            "js": True,
            "sourcemap": True,
            "network": True,
            "tech": True,
            "graphql": True,
            "oauth": True,
            "cloud": True,
            "html": True,
        },
        "active_recon": True,
        "active_probes": {
            "files": True,
            "graphql": True,
            "swagger": True,
            "git": True,
            "env": True,
            "http_methods": True,
        },
        "javascript": {
            "download_external": True,
            "fetch_source_maps": True,
            "concurrency": 5,
        },
    },
    "bugbounty": {
        "description": "Passive only, aggressive secrets and endpoint discovery",
        "collectors": {
            "http": True,
            "html": True,
            "storage": True,
            "network": True,
            "javascript": True,
        },
        "analyzers": {
            "headers": True,
            "cookies": True,
            "auth": True,
            "storage": True,
            "js": True,
            "sourcemap": True,
            "network": True,
            "tech": True,
            "graphql": True,
            "oauth": False,
            "cloud": True,
            "html": True,
        },
        "active_recon": False,
        "javascript": {
            "download_external": True,
            "fetch_source_maps": True,
            "concurrency": 8,
        },
    },
}


def list_profiles() -> dict[str, str]:
    return {name: spec["description"] for name, spec in PROFILE_DEFINITIONS.items()}


def apply_profile(base_config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    if profile_name not in PROFILE_DEFINITIONS:
        raise ValueError(
            f"Unknown profile '{profile_name}'. "
            f"Available: {', '.join(PROFILE_DEFINITIONS)}"
        )
    merged = deepcopy(base_config)
    profile = deepcopy(PROFILE_DEFINITIONS[profile_name])
    merged["profile"] = profile_name
    for key, value in profile.items():
        if key == "description":
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def is_analyzer_enabled(config: dict[str, Any], analyzer_name: str) -> bool:
    return config.get("analyzers", {}).get(analyzer_name, False)


def is_collector_enabled(config: dict[str, Any], collector_name: str) -> bool:
    return config.get("collectors", {}).get(collector_name, False)
