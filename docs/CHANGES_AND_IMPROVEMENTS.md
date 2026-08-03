# WebVac Changes & Improvement Ideas

**Date:** 2026-07-27  
**Branch:** `main`  
**Baseline commit:** `2d26848` (Add detailed project README)  
**Range:** `2d26848..92b42c1` — **14 commits**, ~2,880 lines added across 22 files

---

## 1. Summary of what we shipped

This release is a full **Auth Logic Overhaul** (17 features) plus supporting crawl, security, CLI, and docs work. Existing `--login` / `--session-file` flows stay backward-compatible; new flags are additive. **Nodriver was later removed** — login is Patchright-only.

### 1.1 New auth modules (`auth/`)

| File | Purpose |
|------|---------|
| `manager.py` | Unified **AuthManager** facade: `login`, `restore`, `verify`, `ensure_authenticated`, `bootstrap_manual`, `is_auth_wall` |
| `session_store.py` | Playwright `storage_state` save/load; legacy cookie-list support; TTL metadata; optional Fernet encryption via `WEBVAC_SESSION_KEY` |
| `profile.py` | Rich `AuthProfile` from JSON (selectors, steps, TOTP, policies) |
| `steps.py` | Multi-step login runner (`fill` / `click` / `wait` / `totp` / `otp_prompt`) |
| `mfa.py` | TOTP via `pyotp`; interactive OTP / CAPTCHA pause |
| `wall.py` | Auth-wall heuristics + `abort` \| `skip` \| `relogin` policy; logout URL patterns |
| `credentials.py` | `WEBVAC_USER` / `WEBVAC_PASS`; CLI redaction helpers |
| `cookie_audit.py` | HttpOnly / Secure / SameSite warnings (login + VAPT) |
| `auth.py` | Patchright login engine |
| `popups.py` | Cookie/privacy popup dismiss helpers |

Existing engines kept: `auth/auth.py` (Patchright), called by AuthManager.

### 1.2 Crawl / browser integration

- **`webvac/cli/scraper.py`**: Login block routed through AuthManager; force `dynamic` engine on login; new CLI flags; auth session policies on crawler config.
- **`core/crawler.py`**: Soft-deny logout URLs when authenticated; skip voluntary proxy rotate when auth-pinned; reinject + re-verify after forced rotate.
- **`core/page_scrape_flow.py`**: Mid-crawl auth-wall detection with abort/skip/relogin.
- **`utils/browser.py`**: Capture/broadcast `storage_state` across slots so crawl workers keep the login session.

### 1.3 Security / VAPT

- Lightweight cookie-flag warnings after login (always available).
- Auth analyzer extended with cookie-flag intelligence **only when `vapt_enabled`**.
- `.gitignore` excludes `auth_creds.json`, `sessions/`, `proxies.txt`.
- Dependencies: `pyotp`, `cryptography`.

### 1.4 CLI / launcher / docs

**New flags:**

```
--auth-check-url URL
--on-auth-wall {abort,skip,relogin}   # default: skip
--session-ttl SECONDS
--auth-bootstrap
--otp-prompt
--auth-profile FILE
--no-auth-proxy-rotate
```

**Env:** `WEBVAC_USER`, `WEBVAC_PASS`, `WEBVAC_SESSION_KEY`

- **`run.py`**: Interactive prompts for reuse session / login / OAuth bootstrap, check URL, wall policy, TTL, OTP.
- **`examples/auth_creds.example.json`**: Full profile schema example.
- **`README.md`**: Auth section, examples, security notes.
- **`tests/test_auth_session.py`**: Unit tests for session store, wall, profile, cookie audit, Fernet, env creds.

### 1.5 Feature map (1–17)

| # | Feature | Status |
|---|---------|--------|
| 1 | `--auth-check-url` verify after login/restore | Done |
| 2 | Mid-crawl auth-wall + `--on-auth-wall` | Done |
| 3 | Full `storage_state` default | Done |
| 4 | Interactive MFA/CAPTCHA on login | Done |
| 5 | No voluntary proxy rotate when authed; reinject on forced rotate | Done |
| 6 | Multi-step login (`steps[]`) | Done |
| 7 | Rich auth profiles | Done |
| 8 | Session health / TTL expiry | Done |
| 9 | Same proxy for login+crawl (slot 0 pin) | Done |
| 10 | CSRF / wait-for form before fill | Done |
| 11 | `--auth-bootstrap` OAuth/SSO export | Done |
| 12 | TOTP / `--otp-prompt` | Done |
| 13 | Deny logout URL patterns when authed | Done |
| 14 | Force dynamic engine when `--login` | Done |
| 15 | Unified AuthManager | Done |
| 16 | Env creds + optional Fernet sessions | Done |
| 17 | Cookie flag audit (login warn + VAPT-gated) | Done |

### 1.6 Commits pushed to GitHub

1. Ignore local auth secrets, sessions, and proxy lists  
2. Add session store with storage_state, TTL, and optional Fernet  
3. Add auth-wall heuristics and cookie flag audit helpers  
4. Add rich auth profiles, multi-step login, and MFA/TOTP helpers  
5. Add unified AuthManager for login, restore, verify, and bootstrap  
6. Add cookie-popup dismiss helpers for Patchright auth
7. Broadcast auth storage_state across browser slots after login  
8. Add pyotp and cryptography for TOTP and session encryption  
9. Wire AuthManager and additive auth CLI flags into scraper  
10. Handle mid-crawl auth walls, logout deny, and pinned proxies  
11. Extend auth analyzer with VAPT-gated cookie flag findings  
12. Extend interactive launcher and example auth profile JSON  
13. Add unit tests for session store, wall, profile, and cookie audit  
14. Document AuthManager CLI flags, env vars, and security notes  

**Not committed (by design):** real `auth_creds.json`, `sessions/`, `proxies.txt`, `arc.png`, `implementation_plan.md`.

---

## 2. Suggested GitHub repos & tools to improve the scraper

Ideas are grouped by problem. Prefer **libraries / patterns to borrow** over wholesale replacement of Patchright + your crawl loop.

### 2.1 Anti-bot / browser realism (highest impact)

| Project | Why it helps |
|---------|----------------|
| [microsoft/playwright](https://github.com/microsoft/playwright) / Patchright ecosystem | You already use Patchright; keep aligning with Playwright `storage_state`, tracing, and network APIs. |
| [ultrafunkamsterdam/nodriver](https://github.com/ultrafunkamsterdam/nodriver) | Previously used for auth-only; **removed** from WebVac. Study CDP patterns only if reintroducing a second engine. |
| [seleniumbase/SeleniumBase](https://github.com/seleniumbase/SeleniumBase) | UC Mode / CDP Mode ideas for challenge pages; optional fallback engine. |
| [nicedoc/camoufox](https://github.com/daijro/camoufox) | Firefox-based anti-detect browser; useful when Chromium fingerprints fail. |
| [rebrowser/rebrowser-patches](https://github.com/rebrowser/rebrowser-patches) | Playwright anti-detect patches; compare with Patchright’s approach. |
| [berstend/puppeteer-extra](https://github.com/berstend/puppeteer-extra) (`puppeteer-extra-plugin-stealth`) | Stealth techniques to port (Navigator, WebGL, chrome.runtime) even if staying on Patchright. |

### 2.2 Crawling & discovery

| Project | Why it helps |
|---------|----------------|
| [apify/crawlee-python](https://github.com/apify/crawlee-python) | Mature queue, retries, session pool, request uniqueness — patterns for hardening `core/crawler.py`. |
| [scrapy/scrapy](https://github.com/scrapy/scrapy) | Middleware, auto-throttle, dupefilter concepts (not a full replace for JS sites). |
| [projectdiscovery/katana](https://github.com/projectdiscovery/katana) | Fast URL/JS endpoint discovery to seed your crawl graph. |
| [projectdiscovery/httpx](https://github.com/projectdiscovery/httpx) | Probe liveness, titles, tech before expensive browser crawls. |
| [GerbenJavado/LinkFinder](https://github.com/GerbenJavado/LinkFinder) | Extract endpoints from JS bundles (pairs with your sourcemap/PDF asset work). |
| [xnl-h4ck3r/xnLinkFinder](https://github.com/xnl-h4ck3r/xnLinkFinder) | Stronger JS link/param discovery for recon mode. |

### 2.3 Proxies, rate limits, resilience

| Project | Why it helps |
|---------|----------------|
| [oxylabs / Bright Data / Scrapoxy](https://github.com/scrapoxy/scrapoxy) | Proxy gateway patterns; sticky sessions that match your auth pin. |
| [encode/httpx](https://github.com/encode/httpx) | Better async HTTP client for lightweight engine + health checks. |
| [tornadoweb/tornado](https://github.com/tornadoweb/tornado) or retry libs like [jd/tenacity](https://github.com/jd/tenacity) | Structured backoff for 429/5xx (you already have sticky/cooldown — formalize with Tenacity). |

### 2.4 Auth & sessions (build on AuthManager)

| Project | Why it helps |
|---------|----------------|
| [pyotp/pyotp](https://github.com/pyotp/pyotp) | Already added; keep using for TOTP. |
| [oauthlib/requests-oauthlib](https://github.com/requests-oauthlib/requests-oauthlib) | Token refresh helpers for API-style OAuth after bootstrap. |
| [psf/requests-toolbelt](https://github.com/requests/toolbelt) | Multipart / cookie jar utilities for hybrid HTTP+browser flows. |

### 2.5 Parsing, extraction, change detection

| Project | Why it helps |
|---------|----------------|
| [scrapinghub/extruct](https://github.com/scrapinghub/extruct) | JSON-LD / microdata / OpenGraph extraction into richer page records. |
| [mozilla/readability](https://github.com/mozilla/readability) or [buriy/python-readability](https://github.com/buriy/python-readability) | Clean article/main-content extraction. |
| [difflib](https://docs.python.org/3/library/difflib.html) / [google/diff-match-patch](https://github.com/google/diff-match-patch) | Improve scan diffs beyond current JSON/MD diffs. |
| [lxml/cssselect](https://github.com/scrapy/cssselect) | You use BS4/lxml already — keep CSS extraction solid. |

### 2.6 Observability & ops

| Project | Why it helps |
|---------|----------------|
| [tqdm/tqdm](https://github.com/tqdm/tqdm) | Already used; add richer ETA / failure counters. |
| [prometheus/client_python](https://github.com/prometheus/client_python) | Metrics for pages/sec, auth-wall hits, proxy failures. |
| Playwright **trace viewer** | Record `--no-headless` failures as traces for debugging login/crawl. |

### 2.7 Security / recon (optional VAPT path)

| Project | Why it helps |
|---------|----------------|
| [projectdiscovery/nuclei](https://github.com/projectdiscovery/nuclei) | Template scans against discovered endpoints (keep gated). |
| [OWASP/CheatSheetSeries](https://github.com/OWASP/CheatSheetSeries) | Cookie/session flag guidance for `cookie_audit`. |
| [zaproxy/zaproxy](https://github.com/zaproxy/zaproxy) | Passive spider/passive scan ideas for analyzer design. |

---

## 3. Recommended next upgrades (practical order)

1. **Crawlee-style request queue** — persistent frontier, resume after crash, better dedupe.  
2. **Katana/httpx pre-pass** — cheap URL seed before Patchright crawl.  
3. **Playwright tracing** on auth failures — faster debug than screenshots alone.  
4. **extruct + readability** — richer `data.json` content fields.  
5. **Tenacity** on navigation/proxy rotate — cleaner retry policy.  
6. **Camoufox or SeleniumBase UC** as optional `--engine` fallback when CF/challenges block Patchright.  
7. **Prometheus metrics** if you run long crawls or multiple workers.

---

## 4. Compatibility reminders

- No `--login` → auth behavior unchanged.  
- Default `--on-auth-wall` is `skip`.  
- Auth is Patchright-only (Nodriver removed); crawl stays Patchright.
- Do not enable VAPT globally by default.  
- Never commit real `auth_creds.json` or live session files.

---

*Generated for the Auth Logic Overhaul push to https://github.com/Shellghostt/WebVac*
