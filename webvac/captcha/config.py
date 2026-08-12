"""CAPTCHA solver configuration (API keys, timeouts, provider)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Repo-root key file (gitignored). Override with WEBVAC_CAPSOLVER_KEY_FILE.
_DEFAULT_KEY_FILES = (
    "capsolver.key",
    ".env",
)

_PLACEHOLDER_KEYS = frozenset({
    "",
    "YOUR_CAPSOLVER_KEY_HERE",
    "YOUR_KEY",
    "YOUR_KEY_HERE",
    "CHANGEME",
    "REPLACE_ME",
})


def _parse_key_text(text: str) -> str:
    """Extract a key from a raw file: KEY=value lines or a bare key."""
    found = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, val = line.partition("=")
            name = name.strip().upper()
            val = val.strip().strip("'").strip('"')
            if name in ("CAPSOLVER_API_KEY", "WEBVAC_CAPSOLVER_KEY", "API_KEY", "KEY"):
                if val.upper() not in _PLACEHOLDER_KEYS:
                    return val
            continue
        if line.upper() not in _PLACEHOLDER_KEYS:
            found = line
    return found


def load_capsolver_key_from_files(*, extra_paths: Optional[list[str]] = None) -> str:
    """
    Load CapSolver key from local files (never committed).

    Order: ``WEBVAC_CAPSOLVER_KEY_FILE``, extra paths, repo-root ``capsolver.key``, ``.env``.
    """
    candidates: list[Path] = []
    env_path = os.environ.get("WEBVAC_CAPSOLVER_KEY_FILE", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    for rel in extra_paths or []:
        if rel:
            candidates.append(Path(rel))
    root = Path.cwd()
    for name in _DEFAULT_KEY_FILES:
        candidates.append(root / name)

    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = str(path.resolve())
        except Exception:
            resolved = str(path)
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        key = _parse_key_text(text)
        if key:
            return key
    return ""


@dataclass
class CaptchaSolverConfig:
    """Runtime settings for auto CAPTCHA solving."""

    enabled: bool = False
    provider: str = "capsolver"  # capsolver | none
    api_key: str = ""
    api_base: str = "https://api.capsolver.com"
    timeout_sec: float = 120.0
    poll_interval_sec: float = 2.0
    max_retries: int = 2
    use_proxy: bool = False  # CapSolver proxy task types when True
    fallback_manual: bool = True

    @classmethod
    def from_mapping(
        cls,
        data: Optional[dict[str, Any]] = None,
        *,
        load_files: bool = True,
    ) -> "CaptchaSolverConfig":
        data = dict(data or {})
        api_key = (
            str(data.get("captcha_api_key") or "").strip()
            or os.environ.get("CAPSOLVER_API_KEY", "").strip()
            or os.environ.get("WEBVAC_CAPSOLVER_KEY", "").strip()
        )
        if load_files and not api_key:
            api_key = load_capsolver_key_from_files()
        if api_key.upper() in _PLACEHOLDER_KEYS:
            api_key = ""

        explicit = str(data.get("captcha_solver") or "").strip().lower()
        disabled = bool(data.get("captcha_solver_disabled", False))
        if explicit in ("none", "off", "disabled", "false", "0"):
            # Default config is "none" — still auto-enable when a real API key exists,
            # unless the user explicitly passed --captcha-solver none.
            if api_key and not disabled:
                provider = "capsolver"
                enabled = True
            else:
                provider = "none"
                enabled = False
        elif explicit in ("",):
            provider = "capsolver" if api_key else "none"
            enabled = bool(api_key)
        else:
            provider = explicit
            enabled = bool(data.get("captcha_solver_enabled", bool(api_key)))

        if provider == "none":
            enabled = False

        return cls(
            enabled=enabled,
            provider=provider if provider != "none" else "capsolver",
            api_key=api_key,
            api_base=str(data.get("captcha_api_base") or "https://api.capsolver.com").rstrip("/"),
            timeout_sec=float(data.get("captcha_solver_timeout_sec", 120) or 120),
            poll_interval_sec=float(data.get("captcha_poll_interval_sec", 2) or 2),
            max_retries=int(data.get("captcha_solver_retries", 2) or 2),
            use_proxy=bool(data.get("captcha_use_proxy", False)),
            fallback_manual=bool(data.get("captcha_fallback_manual", True)),
        )
