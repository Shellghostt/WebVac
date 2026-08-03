"""
profile.py — Rich auth profile loaded from JSON credentials files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AuthProfile:
    username: str = ""
    password: str = ""
    login_url: Optional[str] = None
    session_file: Optional[str] = None
    username_selector: Optional[str] = None
    password_selector: Optional[str] = None
    submit_selector: Optional[str] = None
    dismiss_selectors: list[str] = field(default_factory=list)
    auth_check_url: Optional[str] = None
    on_auth_wall: str = "skip"  # abort | skip | relogin
    totp_secret: Optional[str] = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    wait_for: Optional[str] = None  # CSS selector before fill
    session_ttl: int = 0
    otp_prompt: bool = False

    def has_credentials(self) -> bool:
        return bool(self.username and self.password)


def load_auth_profile(path: str) -> AuthProfile:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("creds"), dict):
        data = data["creds"]
    if not isinstance(data, dict):
        raise ValueError("Auth profile JSON must be an object.")
    return profile_from_dict(data)


def profile_from_dict(data: dict) -> AuthProfile:
    username = data.get("username") or data.get("user") or ""
    password = data.get("password") or data.get("pass") or ""

    engine = data.get("auth_engine") or data.get("engine")
    if engine and str(engine).lower() == "nodriver":
        raise ValueError(
            "Nodriver auth has been removed from WebVac. "
            "Use Patchright login (--login) or a --session-file."
        )

    dismiss = data.get("dismiss_selectors") or data.get("dismiss_selector") or []
    if isinstance(dismiss, str):
        dismiss = [dismiss]
    if not isinstance(dismiss, list):
        raise ValueError("dismiss_selectors must be a string or list.")

    steps = data.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError("steps must be a list.")

    wall = str(data.get("on_auth_wall") or "skip").lower()
    if wall not in ("abort", "skip", "relogin"):
        wall = "skip"

    return AuthProfile(
        username=str(username),
        password=str(password),
        login_url=data.get("login_url") or data.get("login"),
        session_file=data.get("session_file") or data.get("session"),
        username_selector=data.get("username_selector"),
        password_selector=data.get("password_selector"),
        submit_selector=data.get("submit_selector"),
        dismiss_selectors=[str(s) for s in dismiss],
        auth_check_url=data.get("auth_check_url") or data.get("check_url"),
        on_auth_wall=wall,
        totp_secret=data.get("totp_secret") or data.get("totp"),
        steps=list(steps),
        wait_for=data.get("wait_for"),
        session_ttl=int(data.get("session_ttl") or data.get("ttl_sec") or 0),
        otp_prompt=bool(data.get("otp_prompt", False)),
    )


def merge_cli_into_profile(profile: AuthProfile, **overrides) -> AuthProfile:
    """Apply non-None CLI overrides onto a profile."""
    for key, val in overrides.items():
        if val is None:
            continue
        if hasattr(profile, key):
            setattr(profile, key, val)
    return profile
