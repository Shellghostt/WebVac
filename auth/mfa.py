"""
mfa.py — TOTP generation and interactive OTP / CAPTCHA pauses during login.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config.config import DEFAULT_CONFIG


def generate_totp(secret: str) -> str:
    try:
        import pyotp
    except ImportError as exc:
        raise RuntimeError(
            "pyotp is required for TOTP. Install: pip install pyotp"
        ) from exc
    return pyotp.TOTP(secret.replace(" ", "")).now()


async def prompt_otp(
    *,
    prompt: str = "[Auth/MFA] Enter OTP / MFA code: ",
    timeout_sec: Optional[float] = None,
) -> Optional[str]:
    """Read OTP from stdin (hidden not required — codes are short-lived)."""
    timeout = timeout_sec
    if timeout is None:
        timeout = float(DEFAULT_CONFIG.get("captcha_prompt_timeout_sec", 300) or 0)
    loop = asyncio.get_event_loop()
    try:
        if timeout > 0:
            return (
                await asyncio.wait_for(
                    loop.run_in_executor(None, input, prompt),
                    timeout=timeout,
                )
            ).strip() or None
        return (await loop.run_in_executor(None, input, prompt)).strip() or None
    except asyncio.TimeoutError:
        print(f"[Auth/MFA] Timed out after {timeout:.0f}s waiting for OTP.")
        return None
    except (KeyboardInterrupt, EOFError):
        return None


async def prompt_manual_challenge(
    *,
    message: str = "Solve CAPTCHA / MFA in the browser, then press ENTER.",
    timeout_sec: Optional[float] = None,
) -> bool:
    print(f"[Auth/MFA] {message}")
    timeout = timeout_sec
    if timeout is None:
        timeout = float(DEFAULT_CONFIG.get("captcha_prompt_timeout_sec", 300) or 0)
    loop = asyncio.get_event_loop()
    prompt = "[Auth/MFA] ▶  Press ENTER when done: "
    try:
        if timeout > 0:
            await asyncio.wait_for(
                loop.run_in_executor(None, input, prompt),
                timeout=timeout,
            )
        else:
            await loop.run_in_executor(None, input, prompt)
        return True
    except asyncio.TimeoutError:
        print(f"[Auth/MFA] Timed out after {timeout:.0f}s.")
        return False
    except (KeyboardInterrupt, EOFError):
        return False
