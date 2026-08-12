"""CapSolver provider — uses the official ``capsolver`` Python SDK (async wrapper)."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from webvac.captcha.config import CaptchaSolverConfig
from webvac.captcha.models import CaptchaInfo, CaptchaType, SolverResult

try:
    from capsolver.capsolver import Capsolver
    from capsolver import error as capsolver_error

    _HAS_SDK = True
except ImportError:  # pragma: no cover - optional at dev time until pip install
    Capsolver = None  # type: ignore[misc, assignment]
    capsolver_error = None  # type: ignore[assignment]
    _HAS_SDK = False


def build_capsolver_task(info: CaptchaInfo, *, use_proxy: bool = False) -> dict[str, Any]:
    """Map CaptchaInfo → CapSolver task payload (without clientKey).

    Covers all six reCAPTCHA demo variants plus Turnstile / hCaptcha:
      v2, v2 invisible, v2 callback, v2 enterprise, v3, v3 enterprise.
    Callback is the same CapSolver task as v2; inject fires the site callback.
    """
    proxyless = not (use_proxy and info.proxy)
    ctype = info.captcha_type

    if ctype == CaptchaType.TURNSTILE:
        task: dict[str, Any] = {
            "type": "AntiTurnstileTaskProxyLess" if proxyless else "AntiTurnstileTask",
            "websiteURL": info.website_url,
            "websiteKey": info.website_key,
        }
        metadata: dict[str, str] = {}
        action = (info.page_action or info.extra.get("action") or "").strip()
        cdata = str(info.extra.get("cdata") or info.extra.get("cData") or "").strip()
        if action:
            metadata["action"] = action
        if cdata:
            metadata["cdata"] = cdata
        if metadata:
            task["metadata"] = metadata

    elif ctype == CaptchaType.HCAPTCHA:
        task = {
            "type": "HCaptchaTaskProxyLess" if proxyless else "HCaptchaTask",
            "websiteURL": info.website_url,
            "websiteKey": info.website_key,
        }
        if info.extra.get("rqdata"):
            task["enterprisePayload"] = {"rqdata": info.extra["rqdata"]}

    elif ctype in (CaptchaType.RECAPTCHA_V3, CaptchaType.RECAPTCHA_V3_ENTERPRISE):
        enterprise = ctype == CaptchaType.RECAPTCHA_V3_ENTERPRISE or info.is_enterprise
        if enterprise:
            task_type = (
                "ReCaptchaV3EnterpriseTaskProxyLess"
                if proxyless
                else "ReCaptchaV3EnterpriseTask"
            )
        else:
            task_type = "ReCaptchaV3TaskProxyLess" if proxyless else "ReCaptchaV3Task"
        task = {
            "type": task_type,
            "websiteURL": info.website_url,
            "websiteKey": info.website_key,
            "pageAction": info.page_action or "verify",
            "minScore": float(info.extra.get("min_score", 0.7) or 0.7),
        }
        _attach_enterprise_s(task, info)

    else:
        # v2 / v2 invisible / v2 callback / v2 enterprise
        enterprise = ctype == CaptchaType.RECAPTCHA_V2_ENTERPRISE or info.is_enterprise
        if enterprise:
            task_type = (
                "ReCaptchaV2EnterpriseTaskProxyLess"
                if proxyless
                else "ReCaptchaV2EnterpriseTask"
            )
        else:
            task_type = "ReCaptchaV2TaskProxyLess" if proxyless else "ReCaptchaV2Task"
        task = {
            "type": task_type,
            "websiteURL": info.website_url,
            "websiteKey": info.website_key,
        }
        if info.is_invisible or ctype == CaptchaType.RECAPTCHA_V2_INVISIBLE:
            task["isInvisible"] = True
        if info.page_action:
            task["pageAction"] = info.page_action
        if enterprise:
            _attach_enterprise_s(task, info)
        else:
            s_val = str(info.extra.get("s") or info.extra.get("recaptchaDataSValue") or "").strip()
            if s_val:
                task["recaptchaDataSValue"] = s_val

    if not proxyless and info.proxy:
        task["proxy"] = _format_proxy(info.proxy)
    if info.user_agent:
        task["userAgent"] = info.user_agent
    return task


def _attach_enterprise_s(task: dict[str, Any], info: CaptchaInfo) -> None:
    s_val = str(info.extra.get("s") or info.extra.get("enterprise_s") or "").strip()
    if not s_val:
        return
    payload = task.get("enterprisePayload")
    if not isinstance(payload, dict):
        payload = {}
    payload["s"] = s_val
    task["enterprisePayload"] = payload


def _format_proxy(proxy: str) -> str:
    """
    CapSolver expects ``http://user:pass@host:port`` (or socks5://…).
    Patchright proxy dicts often pass only ``http://host:port|user|pass``.
    """
    raw = (proxy or "").strip()
    if not raw:
        return raw
    if "|" not in raw:
        return raw
    server, user, password = (raw.split("|") + ["", ""])[:3]
    server = server.strip()
    user = user.strip()
    password = password.strip()
    if not user:
        return server
    scheme, rest = server.split("://", 1) if "://" in server else ("http", server)
    return f"{scheme}://{user}:{password}@{rest}"


def parse_capsolver_solution(data: dict[str, Any]) -> str:
    """Pull token string from CapSolver getTaskResult payload or bare solution dict."""
    solution = data.get("solution") if isinstance(data.get("solution"), dict) else data
    if not isinstance(solution, dict):
        return ""
    for key in (
        "gRecaptchaResponse",
        "token",
        "respKey",
        "cfClearance",
    ):
        val = solution.get(key)
        if isinstance(val, str) and len(val) > 20:
            return val
    for val in solution.values():
        if isinstance(val, str) and len(val) > 40:
            return val
    return ""


def _sdk_error_message(exc: Exception) -> str:
    if capsolver_error and isinstance(exc, capsolver_error.CapsolverError):
        return str(exc)
    return str(exc)


class CapSolverProvider:
    """CapSolver client backed by the official ``capsolver`` SDK (run in a thread)."""

    name = "capsolver"

    def __init__(self, config: CaptchaSolverConfig) -> None:
        self.config = config
        if not _HAS_SDK:
            raise RuntimeError(
                "CapSolver SDK not installed. Run: pip install capsolver"
            )

    def _client(self) -> Capsolver:
        return Capsolver(api_key=self.config.api_key, api_base=self.config.api_base)

    async def solve(self, info: CaptchaInfo) -> SolverResult:
        if not self.config.api_key:
            return SolverResult(success=False, error="Missing CapSolver API key", provider=self.name)
        if not info.solvable:
            return SolverResult(success=False, error="CaptchaInfo not solvable", provider=self.name)

        task = build_capsolver_task(info, use_proxy=self.config.use_proxy)
        try:
            task_id, solution = await asyncio.to_thread(self._solve_sync, task)
        except Exception as exc:
            return SolverResult(
                success=False,
                error=f"CapSolver SDK: {_sdk_error_message(exc)}",
                provider=self.name,
            )

        if not task_id and not solution:
            return SolverResult(success=False, error="createTask returned no taskId", provider=self.name)

        token = parse_capsolver_solution({"solution": solution} if solution else {})
        if not token:
            return SolverResult(
                success=False,
                error="Solution ready but token empty",
                provider=self.name,
                task_id=str(task_id or ""),
            )
        return SolverResult(
            success=True,
            token=token,
            provider=self.name,
            task_id=str(task_id or ""),
            raw={"solution": solution} if solution else None,
        )

    def _solve_sync(self, task: dict[str, Any]) -> tuple[Optional[str], dict[str, Any]]:
        """Blocking solve via official SDK (createTask + poll getTaskResult)."""
        import time

        client = self._client()
        created = client.request("post", "/createTask", {"task": task})
        if isinstance(created, capsolver_error.CapsolverError):
            raise created
        if int(created.get("errorId") or 0) != 0:
            raise RuntimeError(
                created.get("errorDescription") or created.get("errorCode") or str(created)
            )

        # Immediate solution (some task types)
        if str(created.get("status") or "") == "ready" and isinstance(created.get("solution"), dict):
            return str(created.get("taskId") or ""), created["solution"]

        task_id = created.get("taskId")
        if not task_id:
            raise RuntimeError("createTask returned no taskId")

        deadline = time.monotonic() + float(self.config.timeout_sec)
        poll = max(0.5, float(self.config.poll_interval_sec))
        while time.monotonic() < deadline:
            time.sleep(poll)
            result = client.request("post", "/getTaskResult", {"taskId": task_id})
            if isinstance(result, capsolver_error.CapsolverError):
                raise result
            if int(result.get("errorId") or 0) != 0:
                raise RuntimeError(
                    result.get("errorDescription") or result.get("errorCode") or str(result)
                )
            status = str(result.get("status") or "")
            if status == "ready":
                solution = result.get("solution") or {}
                return str(task_id), solution if isinstance(solution, dict) else {}
            if status not in ("processing", "idle", ""):
                raise RuntimeError(
                    result.get("errorDescription") or f"unexpected status={status}"
                )

        raise TimeoutError("CapSolver poll timeout")
