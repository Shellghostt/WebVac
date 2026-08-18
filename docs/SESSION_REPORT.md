# WebVac Session Report

**Date:** 2026-08-03  
**Author:** Adityaaa  
**Repo:** https://github.com/Shellghostt/WebVac  
**Branch:** `main`

---

## 1. Executive summary

This release packages WebVac as an installable `webvac/` module, removes Nodriver (Patchright-only auth), hardens CMP/consent handling for crawl pages, simplifies the interactive menu for auth and subdomains, and improves anti-bot hygiene (honeypot link filtering, Sec-Fetch headers, Google consent cookie).

---

## 2. Changes delivered

### 2.1 Package restructure
- Application code moved under installable `webvac/` package
- Entry points: `python -m webvac`, `python run.py` (thin shim), `pyproject.toml` scripts
- Example inputs under `examples/`
- Docs: `docs/STRUCTURE.md`, architecture updates

### 2.2 Nodriver removed (Patchright-only auth)
- Deleted Nodriver auth engine and dependency
- Removed `--auth-engine` CLI / menu choices
- Profiles with `auth_engine: "nodriver"` are rejected with a clear error
- Login, session restore, MFA/TOTP, bootstrap remain on Patchright

### 2.3 Interactive menu (`run.py`)
**Auth auto-defaults (no longer prompted):**
- `login_url` → target URL (or JSON profile)
- `session_file` → `sessions/patchright_session.json`
- `on-auth-wall` → `skip`
- `session-ttl` → `0`
- OTP / auth-check URL → off unless set in JSON

**Crawl:**
- Always enables `--allow-subdomains` (prompt removed)

### 2.4 CMP / cookie consent
| Feature | Flag / behavior |
|---------|-----------------|
| Auto-dismiss Accept on every scrape page | default on; `--no-consent-dismiss` to disable |
| Known URL bypass | e.g. Deloitte `?hidebanner=true` (host allowlist only) |
| Known consent cookies | Google/YouTube `CONSENT=YES+` before navigate |
| Headed pause | `--pause-for-consent` + `--no-headless` (once per host) |
| Extra Accept selectors | `--dismiss-selector` (login + scrape) |
| Module | `webvac/utils/consent.py` |
| Tests | `tests/test_consent.py` |

### 2.5 Anti-scraping hardening
- Honeypot link filter in HTML parser (`display:none`, `visibility:hidden`, hidden classes)
- `Sec-Fetch-*` request headers on browser contexts
- Network debug dumps on scrape failures (`_network_debug/`)

### 2.6 Documentation
- `docs/architecture/AUTH.md` — Patchright-only
- `README.md` — consent flags, no Nodriver
- `docs/BAS_MCP_LINUX_ROADMAP.md` — remote BAS planning

---

## 3. Gaps remaining (roadmap)

### Critical
| Gap | Impact |
|-----|--------|
| No MCP / job API | No start/status/cancel/result for remote BAS |
| Headless-safe auth incomplete | OTP, CAPTCHA, bootstrap, pause-for-consent still need a human |

### Scraping / anti-bot
| Gap | Notes |
|-----|--------|
| No paid CAPTCHA solver | Manual headed prompt only |
| Thin known-consent catalog | Deloitte + Google/YouTube only |
| No alternate browser (e.g. Camoufox) | Patchright/Chromium only |
| Proxy quality | Code supports pools; success is operational |

### UX
Interactive menu still prompts for format, robots, wait-until, origin IP, proxies, pipeline, headless, screenshots, crawl depth/pages/concurrency.

### Ops
| Gap | Notes |
|-----|--------|
| Linux Docker image | Planned, not built |
| Structured logging | Still print/tqdm-heavy |

---

## 4. Recommended next priorities

1. **P0** — Library job API (start / status / cancel / result)  
2. **P0** — Headless-safe auth mode (no prompts; fail hard)  
3. **P1** — MCP server + Linux container  
4. **P2** — Expand CMP known-site list; slim remaining menu prompts  

See also: [`docs/BAS_MCP_LINUX_ROADMAP.md`](BAS_MCP_LINUX_ROADMAP.md).

---

## 5. How to run (post-update)

```bash
pip install -e .
python -m webvac --url https://example.com --mode crawl
python run.py   # interactive menu
```

Consent-aware scrape:

```bash
python -m webvac --url https://www.deloitte.com/in/en.html --mode single
python -m webvac --url https://example.com --mode single --no-headless --pause-for-consent
```

---

## 6. Security notes

- Real `auth_creds.json`, `sessions/`, `proxies.txt` are gitignored — do not commit them
- Rotate credentials if they were ever shared outside the local machine
