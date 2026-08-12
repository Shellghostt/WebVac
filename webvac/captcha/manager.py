"""
Solver manager — detect → extract → provider solve → inject.

CapSolver-only auto-solving. No manual fallback.
"""

from __future__ import annotations

from typing import Any, Optional

from tqdm import tqdm

from webvac.captcha.config import CaptchaSolverConfig
from webvac.captcha.extract import extract_captcha_info
from webvac.captcha.inject import inject_solution, should_reload_after_inject
from webvac.captcha.models import CaptchaInfo, SolverResult
from webvac.captcha.providers.capsolver import CapSolverProvider


class CaptchaSolverManager:
    """Orchestrates CAPTCHA solving for a live Patchright page."""

    def __init__(self, config: CaptchaSolverConfig) -> None:
        self.config = config
        self._provider = None
        if config.enabled and config.api_key and config.provider == "capsolver":
            self._provider = CapSolverProvider(config)

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self._provider is not None)

    async def try_solve_on_page(
        self,
        page,
        *,
        url: str = "",
        proxy: Optional[str] = None,
        user_agent: str = "",
    ) -> SolverResult:
        """
        Detect CAPTCHA on *page*, solve via provider, inject token.

        Does not close the page. Returns SolverResult (success may be False).
        """
        if not self.enabled:
            return SolverResult(success=False, error="CAPTCHA solver disabled", provider="none")

        info = await extract_captcha_info(
            page, website_url=url or getattr(page, "url", ""), user_agent=user_agent, proxy=proxy,
        )
        if info is None:
            return SolverResult(
                success=False,
                error="No CAPTCHA sitekey detected on page",
                provider=self._provider.name if self._provider else "none",
            )

        action_note = f" action={info.page_action}" if info.page_action else ""
        tqdm.write(
            f"[Captcha] Detected {info.captcha_type.value} "
            f"sitekey={info.website_key[:12]}…{action_note} → {self._provider.name}"
        )

        last: SolverResult = SolverResult(success=False, error="No attempts", provider=self._provider.name)
        attempts = max(1, int(self.config.max_retries) + 1)
        for i in range(attempts):
            last = await self._provider.solve(info)
            if last.success:
                break
            tqdm.write(
                f"[Captcha] Solve attempt {i + 1}/{attempts} failed: {last.error}"
            )

        if not last.success:
            return last

        ok = await inject_solution(page, last, info)
        if not ok:
            return SolverResult(
                success=False,
                error="Token received but DOM inject failed",
                provider=last.provider,
                token=last.token,
                task_id=last.task_id,
                raw=last.raw,
            )
        tqdm.write(f"[Captcha] Injected token from {last.provider} (task={last.task_id})")
        last._needs_reload = await should_reload_after_inject(info, page)
        return last


def solver_from_config(session_config: Optional[dict[str, Any]] = None) -> CaptchaSolverManager:
    """Build manager from DEFAULT_CONFIG / session_config / env."""
    return CaptchaSolverManager(CaptchaSolverConfig.from_mapping(session_config))
