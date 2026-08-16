"""
Solver manager — network watch + multi-candidate detect → CapSolver → inject.

CapSolver-only auto-solving. No manual fallback.
"""

from __future__ import annotations

from typing import Any, Optional

from tqdm import tqdm

from webvac.captcha.config import CaptchaSolverConfig
from webvac.captcha.extract import (
    extract_captcha_candidates,
    is_type_mismatch_error,
    variant_remaps,
)
from webvac.captcha.inject import inject_solution, should_reload_after_inject
from webvac.captcha.models import CaptchaInfo, CaptchaType, SolverResult
from webvac.captcha.network_watch import CaptchaNetworkWatcher
from webvac.captcha.providers.capsolver import CapSolverProvider

_LAZY_WAIT_MS = 1500
_MAX_CANDIDATES = 3
_WIDGET_SELECTORS = (
    ".g-recaptcha, .cf-turnstile, .h-captcha, "
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare.com']"
)


class CaptchaSolverManager:
    """Orchestrates CAPTCHA solving for a live Patchright page."""

    def __init__(self, config: CaptchaSolverConfig) -> None:
        self.config = config
        self._provider = None
        self._watchers: dict[int, CaptchaNetworkWatcher] = {}
        if config.enabled and config.api_key and config.provider == "capsolver":
            self._provider = CapSolverProvider(config)

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self._provider is not None)

    def attach_network_watcher(self, page) -> CaptchaNetworkWatcher:
        """Attach (or reuse) a captcha network watcher on *page* before goto when possible."""
        key = id(page)
        existing = self._watchers.get(key)
        if existing and existing.attached:
            return existing
        watcher = CaptchaNetworkWatcher()
        watcher.attach(page)
        self._watchers[key] = watcher
        return watcher

    def detach_network_watcher(self, page) -> None:
        key = id(page)
        watcher = self._watchers.pop(key, None)
        if watcher:
            watcher.detach()

    def _watcher_for(self, page) -> CaptchaNetworkWatcher:
        key = id(page)
        watcher = self._watchers.get(key)
        if watcher is None or not watcher.attached:
            return self.attach_network_watcher(page)
        return watcher

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

        Uses network fingerprints + ranked DOM candidates, with CapSolver
        variant remaps on type mismatches. Does not close the page.
        """
        if not self.enabled:
            return SolverResult(success=False, error="CAPTCHA solver disabled", provider="none")

        provider_name = self._provider.name if self._provider else "none"
        watcher = self._watcher_for(page)

        # Allow lazy widgets / network traffic to settle
        try:
            await page.wait_for_timeout(_LAZY_WAIT_MS)
        except Exception:
            pass
        try:
            await page.wait_for_selector(_WIDGET_SELECTORS, timeout=4000)
        except Exception:
            pass

        hints = watcher.snapshot()
        candidates = await extract_captcha_candidates(
            page,
            website_url=url or getattr(page, "url", ""),
            user_agent=user_agent,
            proxy=proxy,
            network_hints=hints,
        )

        if hints:
            summary = ", ".join(
                f"{h.family}{'/' + h.sitekey[:10] if h.sitekey else ''}@{h.confidence:.0f}"
                for h in hints[:5]
            )
            tqdm.write(f"[Captcha] Network fingerprints: {summary}")

        solvable = [c for c in candidates if c.solvable]
        if not solvable:
            only_challenge = any(
                c.captcha_type == CaptchaType.CHALLENGE_PAGE for c in candidates
            )
            self.detach_network_watcher(page)
            if only_challenge:
                return SolverResult(
                    success=False,
                    error="Challenge page without solvable widget sitekey — skip CapSolver",
                    provider=provider_name,
                )
            return SolverResult(
                success=False,
                error="No CAPTCHA sitekey detected on page",
                provider=provider_name,
            )

        cand_note = ", ".join(
            f"{c.captcha_type.value}@{c.confidence:.0f}" for c in solvable[:5]
        )
        tqdm.write(f"[Captcha] Candidates: {cand_note}")

        last = SolverResult(success=False, error="No attempts", provider=provider_name)
        for info in solvable[:_MAX_CANDIDATES]:
            action_note = f" action={info.page_action}" if info.page_action else ""
            tqdm.write(
                f"[Captcha] Trying {info.captcha_type.value} "
                f"sitekey={info.website_key[:12]}…{action_note} "
                f"signals={info.signals[:4]} → {provider_name}"
            )
            last = await self._solve_with_remaps(info)
            if not last.success:
                continue

            ok = await inject_solution(page, last, info)
            if not ok:
                last = SolverResult(
                    success=False,
                    error="Token received but DOM inject failed",
                    provider=last.provider,
                    token=last.token,
                    task_id=last.task_id,
                    raw=last.raw,
                )
                continue

            tqdm.write(f"[Captcha] Injected token from {last.provider} (task={last.task_id})")
            last._needs_reload = await should_reload_after_inject(info, page)
            self.detach_network_watcher(page)
            return last

        self.detach_network_watcher(page)
        return last

    async def _solve_with_remaps(self, info: CaptchaInfo) -> SolverResult:
        assert self._provider is not None
        attempts = max(1, int(self.config.max_retries) + 1)
        queue: list[CaptchaInfo] = [info]
        seen: set[str] = set()
        last = SolverResult(success=False, error="No attempts", provider=self._provider.name)

        while queue:
            current = queue.pop(0)
            sig = f"{current.captcha_type.value}|{current.website_key}|{current.is_invisible}"
            if sig in seen:
                continue
            seen.add(sig)

            for i in range(attempts):
                last = await self._provider.solve(current)
                if last.success:
                    return last
                tqdm.write(
                    f"[Captcha] Solve attempt {i + 1}/{attempts} "
                    f"({current.captcha_type.value}) failed: {last.error}"
                )
                if not is_type_mismatch_error(last.error):
                    break

            if is_type_mismatch_error(last.error):
                for alt in variant_remaps(current):
                    alt_sig = f"{alt.captcha_type.value}|{alt.website_key}|{alt.is_invisible}"
                    if alt_sig not in seen:
                        queue.append(alt)
                        tqdm.write(f"[Captcha] Remap → {alt.captcha_type.value}")

        return last


def solver_from_config(session_config: Optional[dict[str, Any]] = None) -> CaptchaSolverManager:
    """Build manager from DEFAULT_CONFIG / session_config / env."""
    return CaptchaSolverManager(CaptchaSolverConfig.from_mapping(session_config))
