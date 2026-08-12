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
