# WebVac Session Report — CapSolver, Auth & Robots

**Date:** 2026-08-13  
**Author:** Adityaaa  
**Repo:** https://github.com/Shellghostt/WebVac  
**Branch:** `main`  
**Focus:** CapSolver auto-CAPTCHA (all reCAPTCHA variants + Turnstile), auth login hardening, robots.txt false-block fix

---

## 1. Executive summary

This release adds a **CapSolver-only** CAPTCHA pipeline (detect → extract → solve → inject) for login and scrape flows, hardens Patchright username/password login for invisible Turnstile and client-side submit gates, removes manual CAPTCHA / OTP-bootstrap from the default auth path, and fixes a **robots.txt false disallow** that aborted crawls (e.g. SpaceX) before any page load.

Chess.com was used as a Turnstile test case; detection and inject are **site-agnostic**. Known-host Turnstile `action` fallbacks remain optional last resorts only.

---

## 2. CapSolver CAPTCHA stack

### 2.1 New package `webvac/captcha/`

| Module | Role |
|--------|------|
| `config.py` | Load API key from env / `capsolver.key`; auto-enable when key present |
| `models.py` | `CaptchaType`, `CaptchaInfo`, `SolverResult` |
| `detect.py` | Page JS detection for Turnstile, hCaptcha, all 6 reCAPTCHA variants |
| `extract.py` | Sitekey, action, enterprise `s`, callbacks → `CaptchaInfo` |
| `inject.py` | Write tokens + fire `___grecaptcha_cfg` / `data-callback` (2captcha patterns) |
| `manager.py` | Orchestrate solve on a live Patchright page |
| `providers/capsolver.py` | Official CapSolver SDK; task builder for all types |

### 2.2 Supported types → CapSolver tasks

| Type | CapSolver task | Notes |
|------|----------------|-------|
| reCAPTCHA v2 | `ReCaptchaV2TaskProxyLess` | Response textarea |
| reCAPTCHA v2 Invisible | same + `isInvisible` | |
| reCAPTCHA v2 Callback | same as v2 | Inject fires named / cfg callback |
| reCAPTCHA v2 Enterprise | `ReCaptchaV2EnterpriseTaskProxyLess` | Optional `enterprisePayload.s` |
| reCAPTCHA v3 | `ReCaptchaV3TaskProxyLess` | Requires `pageAction` |
| reCAPTCHA v3 Enterprise | `ReCaptchaV3EnterpriseTaskProxyLess` | |
| Cloudflare Turnstile | `AntiTurnstileTaskProxyLess` | `metadata.action` / `cdata` when present |
| hCaptcha | `HCaptchaTaskProxyLess` | |

### 2.3 Config / secrets

- `capsolver.key` gitignored; template `examples/capsolver.example.key`
- `.env.example` documents CapSolver env vars
- CLI: auto-enable when key present; `--captcha-solver none` to disable
- Manual headed CAPTCHA prompt **removed** from browser evasion path

---

## 3. Auth / login hardening

| Change | Detail |
|--------|--------|
| Pre-submit CapSolver | Solve CAPTCHA on login form **before** submit |
| Invisible Turnstile | Detect via hidden fields, scripts, `Config` sitekey — not only visible widgets |
| CapSolver `metadata.action` | e.g. Turnstile `login-form` when exposed by the page |
| Dual credential fields | Sync visible → hidden `_username` / `_password` when present |
| Submit reliability | Prefer real login button; native `HTMLFormElement.submit()` if client `preventDefault` gates |
| Manual race | If user finishes login while CapSolver runs and URL leaves login path → success + session save |
| Failure policy | Login failure **aborts** crawl (no “continue unauthenticated”) |
| Scope | Username + password only; OTP/MFA/SSO bootstrap removed from interactive defaults |

Key files: `webvac/auth/auth.py`, `webvac/auth/manager.py`, `webvac/cli/scraper.py`, `webvac/cli/interactive.py`.

---

## 4. Robots.txt false-block fix

**Symptom:** SpaceX crawl logged `Blocked by robots.txt`, Chromium closed in ~0s — looked like the browser never opened.

**Cause:** Fetching `/robots.txt` with Python’s default User-Agent returned **403**. `urllib.robotparser` treats 401/403 as **disallow entire site**.

**Fix (`webvac/utils/robots.py`):**

- Download robots.txt with a browser-like User-Agent
- HTTP **404** → allow-all
- Clear tip to use `--no-robots` when a site is truly disallowed

---

## 5. Related crawl / detection updates (same working tree)

- Auth-wall checks before bot/403 classification (`detection.py`)
- Network debug + consent / popup improvements
- Proxy URL helper for CapSolver credentials
- HTML analyzer, network rules, sourcemap/network analyzers (as present in tree)
- Tests: `tests/test_captcha.py`, `tests/test_robots.py`, plus updates to consent / network_debug

---

## 6. How to run

```bash
# CapSolver key (repo root or env)
# capsolver.key  OR  CAPSOLVER_API_KEY=...

python -m webvac --url https://example.com --login --login-url https://example.com/login

# If robots blocks a site you are authorized to scrape:
python -m webvac --url https://www.spacex.com/ --crawl --no-robots
```

Interactive menu: choose CapSolver / robots bypass as prompted.

---
