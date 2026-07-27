"""
steps.py — Multi-step login runner for Patchright (and best-effort Nodriver).

Supported step types:
  {"wait": 1.5}                          # seconds
  {"wait_for": "css"}                    # wait for selector
  {"fill": "css", "value": "$username"}  # $username / $password / $totp / literal
  {"click": "css"}
  {"press": "Enter", "selector": "css"}  # optional selector focus
  {"totp": "css"}                        # fill TOTP into selector
  {"otp_prompt": "css"}                  # ask user for OTP, fill selector
  {"dismiss_popups": true}
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from auth.mfa import generate_totp, prompt_otp
from auth.popups import dismiss_popups_patchright, dismiss_popups_nodriver


def _resolve_value(raw: Any, *, username: str, password: str, totp_secret: Optional[str]) -> str:
    text = str(raw)
    if text == "$username":
        return username
    if text == "$password":
        return password
    if text == "$totp":
        if not totp_secret:
            raise ValueError("Step uses $totp but totp_secret is not set.")
        return generate_totp(totp_secret)
    return text


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
    for i, step in enumerate(steps):
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


async def run_steps_nodriver(
    tab,
    steps: list[dict[str, Any]],
    *,
    username: str,
    password: str,
    totp_secret: Optional[str] = None,
    dismiss_selectors: Optional[list[str]] = None,
) -> bool:
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        try:
            if step.get("dismiss_popups"):
                await dismiss_popups_nodriver(tab, extra_selectors=dismiss_selectors, rounds=3)
                continue
            if "wait" in step and "wait_for" not in step:
                await tab.sleep(float(step["wait"]))
                continue
            if "wait_for" in step:
                await tab.select(step["wait_for"], timeout=15)
                continue
            if "fill" in step:
                sel = step["fill"]
                val = _resolve_value(
                    step.get("value", ""),
                    username=username,
                    password=password,
                    totp_secret=totp_secret,
                )
                el = await tab.select(sel, timeout=10)
                if not el:
                    raise RuntimeError(f"selector not found: {sel}")
                try:
                    await el.clear_input()
                except Exception:
                    pass
                await el.send_keys(val)
                continue
            if "click" in step:
                el = await tab.select(step["click"], timeout=5)
                if not el:
                    raise RuntimeError(f"click target missing: {step['click']}")
                await el.click()
                continue
            if "totp" in step:
                if not totp_secret:
                    return False
                code = generate_totp(totp_secret)
                el = await tab.select(step["totp"], timeout=10)
                await el.clear_input()
                await el.send_keys(code)
                continue
            if "otp_prompt" in step:
                code = await prompt_otp()
                if not code:
                    return False
                el = await tab.select(step["otp_prompt"], timeout=10)
                await el.clear_input()
                await el.send_keys(code)
                continue
            if "press" in step:
                # best-effort: send Enter on last focused via password-like selector
                key = step["press"]
                sel = step.get("selector")
                if sel and key.lower() in ("enter", "return", "\n"):
                    el = await tab.select(sel, timeout=5)
                    if el:
                        await el.send_keys("\n")
                continue
        except Exception as exc:
            print(f"[Auth/Steps/Nodriver] Step {i} failed ({step}): {exc}")
            return False
    return True
