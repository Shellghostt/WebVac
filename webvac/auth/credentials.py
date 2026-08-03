"""
credentials.py — Env-var credentials and secret redaction helpers.
"""

from __future__ import annotations

import os
from typing import Optional


def resolve_credentials(
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Prefer explicit args; fall back to WEBVAC_USER / WEBVAC_PASS."""
    user = username or os.environ.get("WEBVAC_USER") or None
    pw = password or os.environ.get("WEBVAC_PASS") or None
    if user is not None:
        user = str(user).strip() or None
    if pw is not None:
        pw = str(pw)  # do not strip password spaces
    return user, pw


def redact_cmd_args(cmd_args: list[str]) -> list[str]:
    """Mask --password values for display."""
    redacted: list[str] = []
    skip_next = False
    for arg in cmd_args:
        if skip_next:
            redacted.append("********")
            skip_next = False
            continue
        if arg == "--password":
            redacted.append(arg)
            skip_next = True
            continue
        redacted.append(arg)
    return redacted
