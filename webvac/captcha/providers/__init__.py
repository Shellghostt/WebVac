"""Provider adapter protocol."""

from __future__ import annotations

from typing import Protocol

from webvac.captcha.models import CaptchaInfo, SolverResult


class CaptchaProvider(Protocol):
    name: str

    async def solve(self, info: CaptchaInfo) -> SolverResult:
        """Create a task, poll until ready, return SolverResult."""
        ...
