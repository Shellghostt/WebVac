"""
steps.py — Multi-step login runner for Patchright.

Supported step types (compact):
  {"wait": 1.5}                          # seconds
  {"wait_for": "css"}                    # wait for selector
  {"fill": "css", "value": "$username"}  # $username / $password / $totp / literal
  {"click": "css"}
  {"press": "Enter", "selector": "css"}  # optional selector focus
  {"totp": "css"}                        # fill TOTP into selector
  {"otp_prompt": "css"}                  # ask user for OTP, fill selector
  {"dismiss_popups": true}

Also accepted (normalized to compact):
  {"action": "fill", "selector": "#email", "value": "{{username}}"}
  {"action": "wait", "selector": "input[type=password]"}
  {"action": "click", "selector": "button[type=submit]"}
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from webvac.auth.mfa import generate_totp, prompt_otp
from webvac.auth.popups import dismiss_popups_patchright

_TEMPLATE_RE = re.compile(
    r"^\s*(?:\{\{\s*(username|password|totp)\s*\}\}|\$?(username|password|totp))\s*$",
    re.I,
)

_COMPACT_KEYS = (
    "fill",
    "click",
    "wait_for",
    "totp",
    "otp_prompt",
    "press",
    "dismiss_popups",
)


def _normalize_template(raw: Any) -> str:
    """Map {{username}} / $username / username tokens to $username style."""
    text = str(raw)
    m = _TEMPLATE_RE.match(text)
    if not m:
        return text
    token = (m.group(1) or m.group(2) or "").lower()
    return f"${token}"


def normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    """Normalize action/selector or compact step dicts to one compact form."""
    if not isinstance(step, dict):
        return step

    # Compact already (may still need value template normalize)
    if any(k in step for k in _COMPACT_KEYS):
        out = dict(step)
        if "value" in out:
            out["value"] = _normalize_template(out["value"])
        return out

    # Numeric wait without action
    if "wait" in step and "action" not in step:
        return dict(step)

    action = str(step.get("action") or "").lower().strip()
    if not action:
        return dict(step)

    sel = step.get("selector") or step.get("target") or ""
    out: dict[str, Any] = {}

    if action in ("wait", "sleep", "delay"):
        if sel:
            out["wait_for"] = sel
        elif "timeout_ms" in step:
            out["wait"] = float(step["timeout_ms"]) / 1000.0
        elif "seconds" in step:
            out["wait"] = float(step["seconds"])
        elif "value" in step:
            try:
                out["wait"] = float(step["value"])
            except (TypeError, ValueError):
                out["wait"] = 1.0
        else:
            out["wait"] = 1.0
        return out

    if action in ("wait_for", "waitfor"):
        out["wait_for"] = sel or step.get("value") or step.get("wait_for") or ""
        return out

    if action == "fill":
        out["fill"] = sel
        out["value"] = _normalize_template(step.get("value", ""))
        return out

    if action == "click":
        out["click"] = sel
        return out

    if action == "press":
        out["press"] = step.get("key") or step.get("value") or "Enter"
        if sel:
            out["selector"] = sel
        return out

    if action == "totp":
        out["totp"] = sel
        return out

    if action in ("otp", "otp_prompt", "mfa"):
        out["otp_prompt"] = sel
        return out

    if action in ("dismiss", "dismiss_popups", "popups"):
        out["dismiss_popups"] = True
        return out

    # Unknown action — return as-is so runner can log
    return dict(step)


def normalize_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_step(s) if isinstance(s, dict) else s for s in steps]


def _resolve_value(raw: Any, *, username: str, password: str, totp_secret: Optional[str]) -> str:
    text = _normalize_template(raw)
    if text == "$username":
        return username
    if text == "$password":
        return password
    if text == "$totp":
        if not totp_secret:
            raise ValueError("Step uses $totp but totp_secret is not set.")
        return generate_totp(totp_secret)
    return str(raw) if not text.startswith("$") else text


async def run_steps_patchright(
    page,
    steps: list[dict[str, Any]],
    *,
    username: str,
    password: str,
    totp_secret: Optional[str] = None,
    otp_prompt: bool = False,
    dismiss_selectors: Optional[list[str]] = None,
    timeout_ms: int = 30000,
) -> bool:
    del otp_prompt  # reserved; use {"otp_prompt": "css"} steps
    for i, step in enumerate(normalize_steps(steps)):
        if not isinstance(step, dict):
            print(f"[Auth/Steps] Skipping invalid step {i}: {step}")
            continue
        try:
            if step.get("dismiss_popups"):
                await dismiss_popups_patchright(page, extra_selectors=dismiss_selectors, rounds=3)
                continue
            if "wait" in step and "wait_for" not in step:
                await asyncio.sleep(float(step["wait"]))
                continue
            if "wait_for" in step:
                await page.wait_for_selector(step["wait_for"], timeout=timeout_ms)
                continue
            if "fill" in step:
                sel = step["fill"]
                val = _resolve_value(
                    step.get("value", ""),
                    username=username,
                    password=password,
                    totp_secret=totp_secret,
                )
                await page.fill(sel, val)
                continue
            if "click" in step:
                await page.click(step["click"])
                continue
            if "press" in step:
                key = step["press"]
                sel = step.get("selector")
                if sel:
                    await page.press(sel, key)
                else:
                    await page.keyboard.press(key)
                continue
            if "totp" in step:
                if not totp_secret:
                    print("[Auth/Steps] totp step requires totp_secret")
                    return False
                code = generate_totp(totp_secret)
                await page.fill(step["totp"], code)
                continue
            if "otp_prompt" in step:
                code = await prompt_otp()
                if not code:
                    return False
                await page.fill(step["otp_prompt"], code)
                continue
            print(f"[Auth/Steps] Unknown step keys: {list(step.keys())}")
        except Exception as exc:
            print(f"[Auth/Steps] Step {i} failed ({step}): {exc}")
            return False
    return True
