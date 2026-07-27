"""
session_store.py — Playwright storage_state persistence with optional Fernet encryption.

Supports:
  - Full storage_state (cookies + origins/localStorage) — preferred
  - Legacy cookie-list JSON files
  - Metadata: created_at, last_verified_at, ttl_sec
  - Optional encryption when WEBVAC_SESSION_KEY is set
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


META_KEY = "_webvac_session_meta"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet_from_env():
    key = os.environ.get("WEBVAC_SESSION_KEY", "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        print("[Auth] WEBVAC_SESSION_KEY set but cryptography not installed; saving plaintext.")
        return None
    # Derive a valid Fernet key from arbitrary passphrase
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    fkey = base64.urlsafe_b64encode(digest)
    return Fernet(fkey)


def normalize_to_storage_state(data: Any) -> dict:
    """Convert cookie-list or storage_state dict into a storage_state-shaped dict."""
    if isinstance(data, list):
        return {"cookies": data, "origins": []}
    if isinstance(data, dict):
        if "cookies" in data or "origins" in data:
            out = {
                "cookies": list(data.get("cookies") or []),
                "origins": list(data.get("origins") or []),
            }
            if META_KEY in data:
                out[META_KEY] = data[META_KEY]
            return out
        # Single-cookie-like mistake
        if "name" in data and "value" in data:
            return {"cookies": [data], "origins": []}
    raise ValueError("Session file must be a cookie list or storage_state object.")


def get_meta(state: dict) -> dict:
    return dict(state.get(META_KEY) or {})


def set_meta(
    state: dict,
    *,
    created_at: Optional[str] = None,
    last_verified_at: Optional[str] = None,
    ttl_sec: int = 0,
    seed_url: str = "",
) -> dict:
    meta = get_meta(state)
    if created_at is not None:
        meta["created_at"] = created_at
    elif "created_at" not in meta:
        meta["created_at"] = _now_iso()
    if last_verified_at is not None:
        meta["last_verified_at"] = last_verified_at
    meta["ttl_sec"] = int(ttl_sec or 0)
    if seed_url:
        meta["seed_url"] = seed_url
    state[META_KEY] = meta
    return state


def is_expired(state: dict, *, now: Optional[datetime] = None) -> bool:
    meta = get_meta(state)
    ttl = int(meta.get("ttl_sec") or 0)
    if ttl <= 0:
        return False
    stamp = meta.get("last_verified_at") or meta.get("created_at")
    if not stamp:
        return False
    try:
        created = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    ref = now or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (ref - created).total_seconds() > ttl


def load_session(path: str) -> dict:
    """Load session file (plaintext or Fernet-encrypted)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        raw = f.read()
    fernet = _fernet_from_env()
    text: str
    if fernet and not raw.lstrip().startswith(b"{") and not raw.lstrip().startswith(b"["):
        try:
            text = fernet.decrypt(raw).decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Failed to decrypt session file: {exc}") from exc
    else:
        text = raw.decode("utf-8")
    data = json.loads(text)
    return normalize_to_storage_state(data)


def save_session(
    path: str,
    state: dict,
    *,
    ttl_sec: int = 0,
    seed_url: str = "",
    mark_verified: bool = False,
) -> None:
    """Save storage_state (+ metadata), optionally Fernet-encrypted."""
    state = normalize_to_storage_state(state)
    kwargs: dict[str, Any] = {"ttl_sec": ttl_sec, "seed_url": seed_url}
    if mark_verified:
        kwargs["last_verified_at"] = _now_iso()
    set_meta(state, **kwargs)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = json.dumps(state, indent=2).encode("utf-8")
    fernet = _fernet_from_env()
    if fernet:
        payload = fernet.encrypt(payload)
    with open(path, "wb") as f:
        f.write(payload)


def cookies_from_state(state: dict) -> list[dict]:
    return list(normalize_to_storage_state(state).get("cookies") or [])
