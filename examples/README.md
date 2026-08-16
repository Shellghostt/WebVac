# WebVac example input files

Copy these templates, fill in real values, and point the CLI / menu at them.
Real secrets (`auth_creds.json`, `proxies.txt`, `capsolver.key`, `sessions/*.json`, `.env`) are gitignored.

| File | CLI flag | Purpose |
|------|----------|---------|
| [`auth_creds.example.json`](auth_creds.example.json) | `--auth-profile` / `--login` + JSON | Username/password, selectors, steps, TOTP |
| [`proxies.example.txt`](proxies.example.txt) | `--proxy-file` | Proxy pool (one per line) |
| [`capsolver.example.key`](capsolver.example.key) | (auto) / `--captcha-solver capsolver` | CapSolver API key → copy to repo-root `capsolver.key` |
| [`session.example.json`](session.example.json) | `--session-file` | Playwright `storage_state` (preferred) |
| [`session_cookies_legacy.example.json`](session_cookies_legacy.example.json) | `--session-file` | Legacy cookie-list format |
| [`pipeline.example.py`](pipeline.example.py) | `--pipeline-file` | Clean/drop page records before save |
| [`captcha_smoke.py`](captcha_smoke.py) | (standalone) | Live CapSolver E2E against 2captcha demos |

## Quick copy

```bash
# Windows PowerShell
copy examples\proxies.example.txt proxies.txt
copy examples\auth_creds.example.json auth_creds.json
copy examples\capsolver.example.key capsolver.key

# Linux / macOS
cp examples/proxies.example.txt proxies.txt
cp examples/auth_creds.example.json auth_creds.json
cp examples/capsolver.example.key capsolver.key
```

## CLI examples

```bash
python -m webvac --url https://example.com --mode single \
  --proxy-file examples/proxies.example.txt

python -m webvac --url https://example.com/app --mode crawl \
  --session-file examples/session.example.json \
  --auth-check-url https://example.com/account

python -m webvac --url https://example.com --mode crawl \
  --login --auth-profile examples/auth_creds.example.json

python -m webvac --url https://example.com --mode single \
  --pipeline-file examples/pipeline.example.py
```

Interactive menu (`python run.py`) also offers these paths as defaults and lists files under `examples/`.

## CapSolver live smoke

Uses your repo-root `capsolver.key` and spends CapSolver balance. Prefer `--only` first.

**Note:** CapSolver rejects many 2captcha demo sitekeys and Cloudflare dummy Turnstile keys (`1x…` / `3x…`). Default cases use CapSolver-friendly Google demos; override Turnstile with a real widget page.

```bash
# List cases
python examples/captcha_smoke.py --list

# Full E2E (Google official reCAPTCHA v2 demo — detect + solve + inject + site success)
python examples/captcha_smoke.py --only recaptcha_v2

# Broader token smoke (invisible + v3; site HTML verify not required)
python examples/captcha_smoke.py --only recaptcha_v2,recaptcha_v2_invisible,recaptcha_v3

# Real Turnstile page (dummy Cloudflare keys will SKIP)
python examples/captcha_smoke.py --only turnstile --override turnstile=https://yoursite.com/login

# CapSolver token only (no browser)
python examples/captcha_smoke.py --api-only --only recaptcha_v2

# Visible browser
python examples/captcha_smoke.py --only recaptcha_v2 --no-headless
```

## CapSolver watch demo (headed)

Standalone only (not in ``run.py`` / main CLI):

```bash
python examples/captcha_watch_demo.py
python examples/captcha_watch_demo.py --only v2 --pause 8 --keep-open
python examples/captcha_watch_demo.py --url https://www.google.com/recaptcha/api2/demo
```

Opens a **visible** Chromium window, solves with your `capsolver.key` on the
**backend only**, then finds and clicks Check / Verify / Submit / Test.
