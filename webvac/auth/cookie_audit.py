"""
cookie_audit.py — Lightweight auth cookie flag checks (scrape-safe warnings + VAPT intel).
"""

from __future__ import annotations

import re
from typing import Any

_SESSION_NAME_RE = re.compile(
    r"session|sess|auth|token|jwt|sid|csrf|remember|login",
    re.I,
)


def audit_cookies(cookies: list[dict], *, page_url: str = "") -> list[dict[str, Any]]:
    """
    Return list of issue dicts:
      {key, cookie_name, message, severity, affected_url}
    """
    issues: list[dict[str, Any]] = []
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "")
        if not name:
            continue
        interesting = bool(_SESSION_NAME_RE.search(name))
        if not interesting:
            continue
        if not c.get("httpOnly"):
            issues.append({
                "key": "cookie_missing_httponly",
                "cookie_name": name,
                "message": f"Cookie '{name}' missing HttpOnly",
                "severity": "medium",
                "affected_url": page_url,
            })
        if not c.get("secure"):
            issues.append({
                "key": "cookie_missing_secure",
                "cookie_name": name,
                "message": f"Cookie '{name}' missing Secure",
                "severity": "medium",
                "affected_url": page_url,
            })
        same = c.get("sameSite") or c.get("same_site")
        if not same:
            issues.append({
                "key": "cookie_missing_samesite",
                "cookie_name": name,
                "message": f"Cookie '{name}' missing SameSite",
                "severity": "low",
                "affected_url": page_url,
            })
    return issues


def print_audit_warnings(issues: list[dict[str, Any]]) -> None:
    for issue in issues:
        print(f"[Auth/CookieAudit] ⚠  {issue['message']} ({issue['severity']})")
