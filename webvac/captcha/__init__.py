"""
webvac.captcha — modular CAPTCHA detect → extract → solve → inject stack.

Provider: CapSolver (API). Works in both headless and headed Chromium —
the API key stays on the backend; only the solution token is injected into the page.

Detection merges DOM multi-candidates with CaptchaNetworkWatcher fingerprints.
"""

from __future__ import annotations

from webvac.captcha.models import CaptchaInfo, CaptchaType, SolverResult
from webvac.captcha.manager import CaptchaSolverManager, solver_from_config
from webvac.captcha.network_watch import CaptchaNetworkWatcher, fingerprint_captcha_url

__all__ = [
    "CaptchaInfo",
    "CaptchaType",
    "SolverResult",
    "CaptchaSolverManager",
    "solver_from_config",
    "CaptchaNetworkWatcher",
    "fingerprint_captcha_url",
]
