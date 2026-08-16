#!/usr/bin/env python3
"""
Live CapSolver smoke test for WebVac's captcha stack.

Exercises: detect -> CapSolver -> inject -> (optional) form submit -> site success.

Important:
  CapSolver often rejects *competitor demo* sitekeys (2captcha.com/demo/...) and
  Cloudflare *dummy* Turnstile keys (1x… / 2x… / 3x…). This harness uses CapSolver-
  friendly public pages (Google reCAPTCHA demos) by default.

Requires:
  - repo-root ``capsolver.key`` (or CAPSOLVER_API_KEY / WEBVAC_CAPSOLVER_KEY)
  - ``pip install capsolver`` + Patchright Chromium
    (``python -m patchright install chromium``)

Usage (from repo root)::

  python examples/captcha_smoke.py --list
  python examples/captcha_smoke.py --only recaptcha_v2
  python examples/captcha_smoke.py --only recaptcha_v2,recaptcha_v2_invisible,recaptcha_v3
  python examples/captcha_smoke.py --api-only --only recaptcha_v2
  python examples/captcha_smoke.py --override turnstile=https://yoursite.com/login --only turnstile
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from webvac.captcha.config import CaptchaSolverConfig
from webvac.captcha.extract import extract_captcha_info
from webvac.captcha.manager import CaptchaSolverManager
from webvac.captcha.models import CaptchaInfo, CaptchaType
from webvac.captcha.providers.capsolver import CapSolverProvider, build_capsolver_task
from webvac.utils.browser import BrowserManager

SUCCESS_RE = re.compile(
    r"(verification\s+success"
    r"|captcha\s+(is\s+)?(passed|solved)\s+successfully"
    r"|captcha\s+solved"
    r"|thank you[!]?)",
    re.I,
)

DUMMY_TURNSTILE_RE = re.compile(r"^[123]x0{10,}", re.I)

SUBMIT_SELECTORS = (
    'button:has-text("Check")',
    'button:has-text("Verify")',
    'button:has-text("Submit")',
    'input[type="submit"]',
    'button[type="submit"]',
    "#recaptcha-demo-submit",
)


@dataclass(frozen=True)
class SmokeCase:
    name: str
    url: str
    expect: CaptchaType
    # Require site success HTML after submit (full E2E). If False, token+inject is enough.
    require_site: bool = True
    # Known CapSolver-friendly sitekey for --api-only
    api_sitekey: str = ""
    api_action: str = ""
    api_invisible: bool = False
    api_enterprise: bool = False
    notes: str = ""


# CapSolver-friendly public demos (not 2captcha competitor keys).
CASES: list[SmokeCase] = [
    SmokeCase(
        "recaptcha_v2",
        "https://www.google.com/recaptcha/api2/demo",
        CaptchaType.RECAPTCHA_V2,
        api_sitekey="6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
        notes="Official Google demo; CapSolver docs use this key.",
    ),
    SmokeCase(
        "recaptcha_v2_invisible",
        "https://www.google.com/recaptcha/api2/demo?invisible=true",
        CaptchaType.RECAPTCHA_V2_INVISIBLE,
        api_invisible=True,
        notes="Google invisible checkbox demo.",
    ),
    SmokeCase(
        "recaptcha_v2_callback",
        "https://2captcha.com/demo/recaptcha-v2-callback",
        CaptchaType.RECAPTCHA_V2_CALLBACK,
        require_site=False,
        notes="2captcha demo — CapSolver may reject sitekey; use --override with a real page.",
    ),
    SmokeCase(
        "recaptcha_v2_enterprise",
        "https://2captcha.com/demo/recaptcha-v2-enterprise",
        CaptchaType.RECAPTCHA_V2_ENTERPRISE,
        require_site=False,
        api_enterprise=True,
        notes="2captcha demo — often CapSolver-unsupported; prefer a real enterprise page.",
    ),
    SmokeCase(
        "recaptcha_v3",
        "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php",
        CaptchaType.RECAPTCHA_V3,
        require_site=False,
        api_action="homepage",
        notes="Google appspot v3 demo; PASS = detect + CapSolver token + inject.",
    ),
    SmokeCase(
        "recaptcha_v3_enterprise",
        "https://2captcha.com/demo/recaptcha-v3-enterprise",
        CaptchaType.RECAPTCHA_V3_ENTERPRISE,
        require_site=False,
        api_action="homepage",
        api_enterprise=True,
        notes="2captcha demo — often CapSolver-unsupported.",
    ),
    SmokeCase(
        "turnstile",
        "https://2captcha.com/demo/cloudflare-turnstile",
        CaptchaType.TURNSTILE,
        require_site=False,
        notes=(
            "Default page uses Cloudflare dummy keys CapSolver rejects. "
            "Pass a real widget page: --override turnstile=https://..."
        ),
    ),
    SmokeCase(
        "hcaptcha",
        "https://accounts.hcaptcha.com/demo",
        CaptchaType.HCAPTCHA,
        require_site=False,
        notes="hCaptcha public demo; CapSolver must accept the live sitekey.",
    ),
]


@dataclass
class CaseResult:
    name: str
    ok: bool
    skipped: bool = False
    detected: str = ""
    detect_match: bool = False
    solved: bool = False
    injected: bool = False
    site_ok: bool = False
    detail: str = ""
    token_len: int = 0
    task_id: str = ""
    extras: dict = field(default_factory=dict)


def _load_config(*, retries: int, timeout: float) -> CaptchaSolverConfig:
    cfg = CaptchaSolverConfig.from_mapping(
        {
            "captcha_solver": "capsolver",
            "captcha_solver_enabled": True,
            "captcha_solver_retries": retries,
            "captcha_solver_timeout_sec": timeout,
        },
        load_files=True,
    )
    if not cfg.api_key:
        raise SystemExit(
            "No CapSolver API key found.\n"
            "  Create repo-root capsolver.key (see examples/capsolver.example.key)\n"
            "  or set CAPSOLVER_API_KEY / WEBVAC_CAPSOLVER_KEY."
        )
    return cfg


def _select_cases(only: Optional[str], overrides: dict[str, str]) -> list[SmokeCase]:
    cases = list(CASES)
    if only:
        wanted = {p.strip().lower() for p in only.split(",") if p.strip()}
        unknown = wanted - {c.name for c in CASES}
        if unknown:
            raise SystemExit(f"Unknown --only names: {sorted(unknown)}. Use --list.")
        cases = [c for c in CASES if c.name in wanted]
    out: list[SmokeCase] = []
    for c in cases:
        if c.name in overrides:
            out.append(replace(c, url=overrides[c.name], notes=c.notes + " (URL overridden)"))
        else:
            out.append(c)
    return out


def _parse_overrides(raw: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise SystemExit(f"Bad --override {item!r}; expected name=https://...")
        name, _, url = item.partition("=")
        name = name.strip().lower()
        url = url.strip()
        if not name or not url.startswith("http"):
            raise SystemExit(f"Bad --override {item!r}; expected name=https://...")
        out[name] = url
    return out


async def _page_success_text(page) -> str:
    try:
        return await page.evaluate(
            """() => {
              const pick = (sel) => {
                const el = document.querySelector(sel);
                return el ? (el.innerText || el.textContent || '').trim() : '';
              };
              return (
                pick('.recaptcha-success') ||
                pick('#recaptcha-demo-success') ||
                pick('.result') ||
                pick('.alert-success') ||
                pick('[class*="success"]') ||
                pick('main') ||
                (document.body && document.body.innerText) ||
                ''
              ).slice(0, 4000);
            }"""
        )
    except Exception:
        return ""


async def _click_check(page) -> bool:
    for sel in SUBMIT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            await loc.click(timeout=5000)
            return True
        except Exception:
            continue
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const form = document.querySelector('form');
                  if (!form) return false;
                  if (form.requestSubmit) form.requestSubmit();
                  else form.submit();
                  return true;
                }"""
            )
        )
    except Exception:
        return False


def _soft_detect_match(info: CaptchaInfo, expect: CaptchaType) -> bool:
    if info.captcha_type == expect:
        return True
    # Callback pages often look like plain v2 (and Google's demo has a callback).
    v2_family = {
        CaptchaType.RECAPTCHA_V2,
        CaptchaType.RECAPTCHA_V2_CALLBACK,
    }
    if expect in v2_family and info.captcha_type in v2_family:
        return True
    # Invisible flag may land as v2 with is_invisible.
    if expect == CaptchaType.RECAPTCHA_V2_INVISIBLE and info.captcha_type == CaptchaType.RECAPTCHA_V2:
        return bool(info.is_invisible)
    if expect == CaptchaType.RECAPTCHA_V2 and info.captcha_type == CaptchaType.RECAPTCHA_V2_INVISIBLE:
        return True
    return False


async def _run_browser_case(
    browser: BrowserManager,
    mgr: CaptchaSolverManager,
    case: SmokeCase,
    *,
    settle_ms: int,
) -> CaseResult:
    page = await browser.new_page()
    try:
        await page.goto(case.url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(settle_ms)

        info = await extract_captcha_info(page, website_url=case.url)
        if info is None:
            return CaseResult(
                name=case.name,
                ok=False,
                detail="No captcha detected on page",
            )

        detect_match = _soft_detect_match(info, case.expect)

        # CapSolver cannot solve Cloudflare dummy Turnstile keys.
        if (
            info.captcha_type == CaptchaType.TURNSTILE
            and DUMMY_TURNSTILE_RE.match(info.website_key or "")
        ):
            return CaseResult(
                name=case.name,
                ok=False,
                skipped=True,
                detected=info.captcha_type.value,
                detect_match=detect_match,
                detail=(
                    f"Dummy Turnstile sitekey {info.website_key!r} — CapSolver rejects these. "
                    "Re-run with --override turnstile=https://real-page-with-widget"
                ),
            )

        result = await mgr.try_solve_on_page(page, url=case.url)
        if not result.success:
            err = result.error or "solve failed"
            skipped = "not supported" in err.lower() or "invalid websitekey" in err.lower()
            return CaseResult(
                name=case.name,
                ok=False,
                skipped=skipped,
                detected=info.captcha_type.value,
                detect_match=detect_match,
                solved=False,
                detail=err + (f" | {case.notes}" if skipped and case.notes else ""),
                task_id=result.task_id or "",
            )

        injected = bool(result.token)
        if getattr(result, "_needs_reload", False):
            try:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)
            except Exception as exc:
                return CaseResult(
                    name=case.name,
                    ok=False,
                    detected=info.captcha_type.value,
                    detect_match=detect_match,
                    solved=True,
                    injected=injected,
                    token_len=len(result.token or ""),
                    task_id=result.task_id or "",
                    detail=f"reload after inject failed: {exc}",
                )

        site_ok = False
        if case.require_site:
            clicked = await _click_check(page)
            await page.wait_for_timeout(2500)
            body = await _page_success_text(page)
            site_ok = bool(SUCCESS_RE.search(body or ""))
            if not site_ok:
                url_now = (page.url or "").lower()
                if "success" in url_now or "passed" in url_now:
                    site_ok = True
            ok = detect_match and injected and site_ok
            detail_parts = []
            if not detect_match:
                detail_parts.append(f"expected {case.expect.value}, got {info.captcha_type.value}")
            if not clicked:
                detail_parts.append("no Check/Submit control found")
            if not site_ok:
                snippet = re.sub(r"\s+", " ", (body or ""))[:180]
                detail_parts.append(f"site did not confirm success ({snippet!r})")
            elif ok:
                detail_parts.append("detect+solve+inject+site OK")
            elif detect_match and injected:
                detail_parts.append("solve OK but site verify unclear")
            return CaseResult(
                name=case.name,
                ok=ok,
                detected=info.captcha_type.value,
                detect_match=detect_match,
                solved=True,
                injected=injected,
                site_ok=site_ok,
                detail="; ".join(detail_parts),
                token_len=len(result.token or ""),
                task_id=result.task_id or "",
            )

        ok = detect_match and injected
        detail = (
            "detect+solve+inject OK (site verify not required for this case)"
            if ok
            else f"expected {case.expect.value}, got {info.captcha_type.value}"
        )
        return CaseResult(
            name=case.name,
            ok=ok,
            detected=info.captcha_type.value,
            detect_match=detect_match,
            solved=True,
            injected=injected,
            site_ok=False,
            detail=detail,
            token_len=len(result.token or ""),
            task_id=result.task_id or "",
        )
    except Exception as exc:
        return CaseResult(name=case.name, ok=False, detail=f"exception: {exc}")
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def _run_api_only(cfg: CaptchaSolverConfig, cases: list[SmokeCase]) -> list[CaseResult]:
    provider = CapSolverProvider(cfg)
    out: list[CaseResult] = []
    for case in cases:
        if not case.api_sitekey:
            out.append(
                CaseResult(
                    name=case.name,
                    ok=False,
                    skipped=True,
                    detail="--api-only needs api_sitekey; use browser mode or set a known key",
                )
            )
            continue
        info = CaptchaInfo(
            captcha_type=case.expect,
            website_url=case.url,
            website_key=case.api_sitekey,
            page_action=case.api_action,
            is_invisible=case.api_invisible,
            is_enterprise=case.api_enterprise,
        )
        task = build_capsolver_task(info)
        print(f"\n=== {case.name} (API) task={task.get('type')} ===")
        result = await provider.solve(info)
        out.append(
            CaseResult(
                name=case.name,
                ok=bool(result.success and result.token),
                detected=case.expect.value,
                detect_match=True,
                solved=bool(result.success),
                token_len=len(result.token or ""),
                task_id=result.task_id or "",
                detail=result.error or f"token_len={len(result.token or '')}",
            )
        )
    return out


async def _run_browser(
    cfg: CaptchaSolverConfig,
    cases: list[SmokeCase],
    *,
    headless: bool,
    settle_ms: int,
) -> list[CaseResult]:
    mgr = CaptchaSolverManager(cfg)
    if not mgr.enabled:
        raise SystemExit(
            "Captcha solver manager failed to enable "
            "(check key + pip install capsolver)."
        )

    browser = BrowserManager(headless=headless, humanize=False)
    browser.configure_humanize({"humanize": False, "humanize_warmup": False})
    await browser.start()
    results: list[CaseResult] = []
    try:
        for case in cases:
            print(f"\n=== {case.name} -> {case.url} ===")
            if case.notes:
                print(f"  note: {case.notes}")
            res = await _run_browser_case(browser, mgr, case, settle_ms=settle_ms)
            if res.skipped:
                status = "SKIP"
            elif res.ok:
                status = "PASS"
            else:
                status = "FAIL"
            print(
                f"[{status}] detect={res.detected or '-'} "
                f"match={res.detect_match} solved={res.solved} "
                f"site={res.site_ok} token_len={res.token_len} — {res.detail}"
            )
            results.append(res)
    finally:
        await browser.stop()
    return results


def _print_summary(results: list[CaseResult]) -> int:
    print("\n" + "=" * 72)
    print(f"{'CASE':28} {'DETECT':12} {'SOLVE':6} {'SITE':6} RESULT")
    print("-" * 72)
    passed = skipped = failed = 0
    for r in results:
        if r.skipped:
            skipped += 1
            label = "SKIP"
        elif r.ok:
            passed += 1
            label = "PASS"
        else:
            failed += 1
            label = "FAIL"
        print(
            f"{r.name:28} {(r.detected or '-')[:12]:12} "
            f"{'yes' if r.solved else 'no':6} "
            f"{'yes' if r.site_ok else 'no':6} "
            f"{label}"
        )
        if not r.ok and r.detail:
            print(f"  -> {r.detail}")
    print("-" * 72)
    print(f"{passed} passed, {failed} failed, {skipped} skipped / {len(results)} total")
    # Skips are expected for unsupported demo keys; exit 1 only on hard fails.
    return 0 if failed == 0 and (passed + skipped) == len(results) and results else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="WebVac CapSolver live smoke test")
    ap.add_argument("--only", help="Comma-separated case names (see --list)")
    ap.add_argument("--list", action="store_true", help="List cases and exit")
    ap.add_argument("--no-headless", action="store_true", help="Show Chromium window")
    ap.add_argument(
        "--api-only",
        action="store_true",
        help="Skip browser; CapSolver token smoke for cases with known sitekeys",
    )
    ap.add_argument(
        "--override",
        action="append",
        default=[],
        help="Override case URL, e.g. turnstile=https://example.com/login (repeatable)",
    )
    ap.add_argument("--retries", type=int, default=1, help="CapSolver retries (default 1)")
    ap.add_argument("--timeout", type=float, default=120.0, help="Solve timeout seconds")
    ap.add_argument(
        "--settle-ms",
        type=int,
        default=2500,
        help="Wait after page load before detect (ms)",
    )
    args = ap.parse_args()

    if args.list:
        for c in CASES:
            flag = "site" if c.require_site else "token"
            print(f"{c.name:28} {c.expect.value:28} [{flag}] {c.url}")
            if c.notes:
                print(f"  {c.notes}")
        return

    overrides = _parse_overrides(args.override)
    cases = _select_cases(args.only, overrides)
    cfg = _load_config(retries=max(0, args.retries), timeout=args.timeout)
    print(f"CapSolver key loaded (...{cfg.api_key[-4:]}), {len(cases)} case(s)")

    if args.api_only:
        results = asyncio.run(_run_api_only(cfg, cases))
        for r in results:
            status = "SKIP" if r.skipped else ("PASS" if r.ok else "FAIL")
            print(f"[{status}] {r.name}: {r.detail}")
    else:
        results = asyncio.run(
            _run_browser(
                cfg,
                cases,
                headless=not args.no_headless,
                settle_ms=max(500, args.settle_ms),
            )
        )

    raise SystemExit(_print_summary(results))


if __name__ == "__main__":
    main()
