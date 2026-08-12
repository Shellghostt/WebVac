"""
webvac.captcha — modular CAPTCHA detect → extract → solve → inject stack.

Providers: CapSolver (API), manual headed prompt (fallback).
"""

from __future__ import annotations

from webvac.captcha.models import CaptchaInfo, CaptchaType, SolverResult
from webvac.captcha.manager import CaptchaSolverManager, solver_from_config

__all__ = [
    "CaptchaInfo",
    "CaptchaType",
    "SolverResult",
    "CaptchaSolverManager",
    "solver_from_config",
]
