# WebVac

WebVac is an asyncio-powered dynamic web scraping and crawling tool built for modern JavaScript-heavy targets. It drives a real Chromium browser through Patchright, supports proxy rotation, robots handling, anti-bot resilience, optional login/session reuse, exports rich scan artifacts in multiple formats, and can optionally launch De-Caffeinator for VAPT-focused JavaScript reverse engineering.

## Highlights

- Dynamic scraping with a real browser engine (Patchright)
- Single-page and recursive crawl modes
- Concurrency support with isolated browser slot identities
- Proxy pools with latency-based selection, round-robin, or random strategy (auto-uses `proxies.txt`)
- robots.txt bypassed by default (`--respect-robots` to obey)
- Automatic screenshots for blocked/CAPTCHA pages (per-scan `assets/screenshots/`)
- Structured output (default: JSON + HTML report)
- Historical scan sessions under `scraped_data/<target>/scans/…`
- PDF and sourcemap asset download support
- Unified auth: Patchright login, session restore, MFA/TOTP
- Auth walls (`/login`, `/ap/signin`, …) skipped separately from bot/WAF blocks
- Human-like mouse/scroll/warmup on Patchright Chromium (`--no-humanize` to disable)
- Network debug dumps on scrape failures (per-scan `network/` folder)
- Optional CapSolver auto-CAPTCHA (reCAPTCHA / hCaptcha / Turnstile)
- Logout URL deny and sticky proxy when authenticated
- Optional opt-in VAPT task powered by De-Caffeinator

## Release

Current release: `0.3.0`

Highlights in `0.3.0`:
- De-Caffeinator integration via `--task vapt`
- interactive launcher option **VAPT / JS analysis** (`python run.py`)
- session-scoped VAPT output under `analysis/decaffeinator/`
- improved `--doctor` preflight checks for both scrape and VAPT workflows
- streamlined scrape-only core after removing the old in-tree VAPT stack

See [`CHANGELOG.md`](CHANGELOG.md) for the release summary.

## Project Structure

All application code lives in the installable `webvac/` package. See [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

- `run.py`: Thin shim → interactive menu (`webvac.cli.interactive`)
- `webvac/cli/scraper.py`: Main CLI orchestrator (`python -m webvac`)
- `webvac/core/`: BFS crawler, page scrape flow, pipelines
- `webvac/auth/`: AuthManager, sessions, MFA, auth-wall detection
- `webvac/captcha/`: CapSolver detect → extract → solve → inject (optional)
- `webvac/utils/`: Browser, proxies, robots, origin probe, screenshots, network debug, humanize
- `webvac/data/`: HTML parse, page records, storage/export
- `examples/`: Input templates (auth, proxies, session, pipeline) — see [`examples/README.md`](examples/README.md)
- `docs/`, `tests/`, `scripts/`

## Requirements

- Python 3.11+ (3.12 recommended)
- Windows, Linux, or macOS
- Browser dependencies required by Patchright

## Installation

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Install Patchright browser binaries.

### Windows PowerShell

```powershell
python -m venv .venv
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& .\.venv\Scripts\Activate.ps1)
pip install -r requirements.txt
pip install -e .
python -m patchright install
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m patchright install
```

`pip install -e .` registers the `webvac` and `webvac-menu` console scripts and makes imports resolve as `webvac.*`.

## First Run Checklist

Run the built-in preflight before your first scrape:

```bash
python -m webvac --doctor
```

`--doctor` checks:
- Python/runtime availability
- Patchright browser launch
- output directory write access
- proxy file parsing and optional health-check
- pipeline file discovery
- CapSolver key detection
- De-Caffeinator root validation when `--task vapt` is selected

If your proxy pool is present but dead, WebVac will warn and continue with a direct connection using your real IP.

## Example input files

Templates live under [`examples/`](examples/). Copy and edit before use:

| Template | Flag |
|----------|------|
| `examples/auth_creds.example.json` | `--auth-profile` / login JSON |
| `examples/proxies.example.txt` | `--proxy-file` |
| `examples/session.example.json` | `--session-file` (storage_state) |
| `examples/session_cookies_legacy.example.json` | `--session-file` (cookie list) |
| `examples/pipeline.example.py` | `--pipeline-file` |

The interactive menu (`python run.py`) lists these files and shows format hints when you pick session / proxy / credentials / pipeline.

## Quick Start

### Interactive launcher (recommended first run)

```bash
python run.py
# or: webvac-menu
```

The launcher helps you choose scrape mode, VAPT / JS analysis, browser visibility, login/session options, and common runtime settings.

Pick **VAPT / JS analysis** to run De-Caffeinator (blob unpacker) instead of the scrape pipeline. That menu option maps to `--task vapt`.

Recommended first command:

```bash
python -m webvac --doctor
```

### Direct CLI usage

```bash
python -m webvac --url https://example.com --mode single
```

```bash
python -m webvac --url https://example.com --mode crawl --depth 3 --max-pages 50 --concurrency 2
```

### VAPT task

Use the opt-in VAPT task when you want De-Caffeinator analysis instead of the normal scrape flow.

Clone with the submodule (or init it after clone):

```bash
git clone --recurse-submodules https://github.com/Shellghostt/WebVac.git
# or, inside an existing clone:
git submodule update --init --recursive
```

The De-Caffeinator checkout lives at `decaffeinator/` (tool root: `decaffeinator/blob-unpacker`).

From the interactive launcher:

```bash
python run.py
```

Then choose **VAPT / JS analysis**.

Or from the CLI:

```bash
python -m webvac --task vapt --url https://example.com
```

Deep browser + historical JS discovery:

```bash
python -m webvac --task vapt --url https://example.com \
  --vapt-profile deep --vapt-playwright --vapt-wayback
```

## Common CLI Options

### Core

- `--task scrape|vapt`: Normal scrape flow or De-Caffeinator VAPT task
- `--url`: Target URL (required)
- `--mode single|crawl`: Single page or recursive internal crawl
- `--engine dynamic|lightweight`: Browser-based or lightweight HTTP engine
- `--depth`: Maximum crawl depth (crawl mode)
- `--max-pages`: Maximum number of pages (omit for unlimited crawl)
- `--concurrency`: Parallel workers for crawl mode

### Browser and loading

- `--no-headless`: Run browser in visible mode
- `--timeout`: Page load timeout in milliseconds
- `--wait-until domcontentloaded|load|networkidle`: Navigation wait strategy
- `--no-humanize`: Disable Bezier mouse paths, wheel scroll, per-host warmup, and post-load settle
- `--no-humanize-warmup`: Keep settle/scroll humanize but skip the once-per-host root visit

### Output

- `--output`: Output root directory (default: `scraped_data`)
- `--format`: `json,csv,markdown,sqlite,html,all`
- `--label`: Custom label for output naming

### Robots and etiquette

- `--no-robots`: Ignore robots.txt entirely
- `--ignore-crawl-delay`: Obey allow/deny rules but ignore crawl-delay
- `--delay-min`, `--delay-max`: Request pacing window

### Login / authentication

- `--login`: Enable login before scraping (forces `dynamic` engine)
- `--login-url`: Login page URL
- `--username`, `--password`: Credentials (or set `WEBVAC_USER` / `WEBVAC_PASS`)
- `--session-file`: Load/save Playwright `storage_state` (legacy cookie-list files still work)
- `--auth-profile FILE`: Rich credentials JSON (selectors, steps, TOTP, policies) — see `examples/auth_creds.example.json`
- `--auth-check-url URL`: Protected URL used to verify session after login/restore
- `--on-auth-wall abort|skip|relogin`: Mid-crawl login-wall policy (default: `skip`)
- `--session-ttl SECONDS`: Expire saved sessions (0 = never)
- `--otp-prompt`: Prompt for OTP/MFA when an OTP field appears
- `--no-auth-proxy-rotate`: Pin proxy while authenticated (also default when `--login`)
- `--dismiss-selector CSS`: Extra Accept-button selector (repeatable; login + every scrape)
- `--pause-for-consent`: Headed wait-for-ENTER after first page per host (use with `--no-headless`)
- `--no-consent-dismiss`: Disable automatic cookie/CMP Accept clicks on scraped pages

Known-site CMP URL bypasses (host-allowlisted): Deloitte `?hidebanner=true` (multi-TLD). Consent cookies before navigation: Google/YouTube `CONSENT=YES+` (broad TLD list), Bing/MSN `ENFORCE_PRIVACY`, Yahoo `GUCS`, DuckDuckGo preference cookie. Auto-dismiss also covers OneTrust, Cookiebot, Didomi, Osano, Sourcepoint, Quantcast, Usercentrics, Funding Choices. Not applied to unknown hosts.
Honeypot links (`display:none`, `visibility:hidden`, common hidden classes) are skipped when discovering crawl links.

Env vars: `WEBVAC_USER`, `WEBVAC_PASS`, optional `WEBVAC_SESSION_KEY` (Fernet-encrypt session files).

Example — login then crawl:

```bash
python -m webvac --url https://example.com/dashboard --mode crawl \
  --login --login-url https://example.com/login \
  --username you@example.com --password secret \
  --session-file sessions/example.json \
  --auth-check-url https://example.com/account \
  --on-auth-wall skip
```

Example — restore session only:

```bash
python -m webvac --url https://example.com/dashboard --mode single \
  --session-file sessions/example.json --auth-check-url https://example.com/account
```

### Proxies

- `--proxy-file FILE`: One proxy per line
- `--proxies "..."`: Comma-separated proxy list
- `--proxy-strategy latency|random|round_robin`
- `--proxy-playbook none|residential|datacenter`: Named sticky/cooldown/geo defaults (residential = sticky 25 + UA/geo/tz pin)
- `--sticky-requests N`: Successful requests before voluntary rotate (`0` = stay on the same proxy)
- `--cooldown-seconds SECS`: Cooldown after 429/timeout
- If no proxy source is passed, WebVac auto-uses `./proxies.txt` when present
- If configured proxies fail startup health-check, WebVac warns and falls back to a direct connection

### VAPT task (De-Caffeinator)

- `--task vapt`: Run De-Caffeinator instead of the normal scrape pipeline
- `--decaffeinator-root DIR`: Path to De-Caffeinator (default: `./decaffeinator/blob-unpacker`)
- `--vapt-profile standard|quick|stealth|deep`
- `--vapt-format json|jsonl`
- `--vapt-playwright`: Enable SPA asset discovery in De-Caffeinator
- `--vapt-wayback`: Enable historical JS discovery from Wayback
- `--vapt-no-files`: Skip source/deobfuscated file writes

VAPT task output is stored under the normal scan session path in `analysis/decaffeinator/`.

Residential example:

```bash
python -m webvac --url https://example.com --mode crawl \
  --proxy-file proxies.txt --proxy-playbook residential
```

Each proxy line gets a locked UA + matching US city geolocation/timezone. Use provider session usernames for ISP sticky IPs (see `examples/proxies.example.txt`).
- `--no-health-check`: Skip startup benchmark

### Network diagnosis (default on)

Listeners attach on every dynamic page load (document, script, xhr/fetch/websocket + failed resources). On scrape failure, dumps go to `{scan_session}/network/*.json` with status histogram and root-cause hints.

- `--no-network-debug`: Disable listeners and dumps
- `--network-debug-always`: Also dump on successful pages

Auth/login URLs (`/ap/signin`, `/login`, `/register`, …) are classified as `auth_wall` and skipped — they do **not** trigger bot retries or proxy rotation. Reports show them under “Auth Walls Skipped”.

### Auto CAPTCHA (CapSolver)

When a bot/CAPTCHA page is detected, WebVac can call [CapSolver](https://www.capsolver.com/) to solve reCAPTCHA v2/v3, hCaptcha, or Cloudflare Turnstile, then inject the token into the page. Manual headed prompt remains the fallback.

```bash
# Recommended: gitignored key file (copy examples/capsolver.example.key → capsolver.key)
python -m webvac --url https://example.com --mode single --captcha-solver capsolver

# or via environment
set CAPSOLVER_API_KEY=YOUR_KEY
python -m webvac --url https://example.com --captcha-solver capsolver

# or one-off flag (ends up in shell history)
python -m webvac --url https://example.com --mode single \
  --captcha-solver capsolver --captcha-api-key YOUR_KEY
```

- Key file: repo-root `capsolver.key` (gitignored) or `.env` with `CAPSOLVER_API_KEY=`
- `--captcha-solver none|capsolver` (`none` disables even if a key file exists)
- `--captcha-api-key KEY` (or `CAPSOLVER_API_KEY` / `WEBVAC_CAPSOLVER_KEY`)
- `--captcha-timeout SECS` (default 120)
- `--no-captcha-prompt`: disable manual fallback after auto-solve fails

## Proxy File Format

Use either of the following per line:

- `http://ip:port`
- `http://ip:port|username|password`

Lines beginning with `#` are treated as comments.

Example:

```text
# plain
http://1.2.3.4:8080

# authenticated
http://5.6.7.8:3128|myuser|mypassword
```

## Output Layout

WebVac writes data under `scraped_data` using scan-session folders for versioned runs.

```text
scraped_data/
  <target>/
    scans/
      <timestamp>_<scan-id>/
        scrape/
          data.json
          data.csv
          report.html
        network/
          <host>_<timestamp>.json
        assets/
          pdfs/
          sourcemaps/
          screenshots/
        meta/
          meta.json
          session.json
```

## Architecture Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Full system architecture (layers, sequence, status matrix)
- [`docs/architecture/AUTH.md`](docs/architecture/AUTH.md) — Authentication / sessions / MFA / auth-walls
- [`docs/architecture/CRAWL.md`](docs/architecture/CRAWL.md) — Crawler, page flow, browser pool
- [`docs/architecture/DATA.md`](docs/architecture/DATA.md) — Parsing, page records, storage layout
- [`docs/architecture/PROXY_ORIGIN.md`](docs/architecture/PROXY_ORIGIN.md) — Proxies, robots, manual origin IP
- [`docs/CHANGES_AND_IMPROVEMENTS.md`](docs/CHANGES_AND_IMPROVEMENTS.md) — Recent changes + improvement ideas
- [`docs/webvac-architecture-one-page.html`](docs/webvac-architecture-one-page.html) — One-page visual architecture

To regenerate architecture PDF:

```bash
python scripts/generate_architecture_pdf.py
```

## Testing

Run tests from project root:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Notes on Security and Responsible Usage

- Respect target terms of service and legal boundaries.
- Use `--no-robots` only when you are explicitly authorized.
- Avoid scraping sensitive targets without permission.
- Store credentials and proxy secrets securely — copy `examples/auth_creds.example.json` to `auth_creds.json` (gitignored).
- Prefer env vars (`WEBVAC_USER` / `WEBVAC_PASS`) over committing credentials.
- Optional session encryption: set `WEBVAC_SESSION_KEY` before saving sessions.

## Current Default Behavior

- Scrape pipeline is enabled.
- Default output formats are `json,html`.

## Troubleshooting

### Browser launch or navigation fails

- Ensure dependencies are installed in the active virtual environment.
- Try visible browser mode with `--no-headless`.
- Switch wait strategy to `--wait-until domcontentloaded`.

### Frequent bot/challenge blocks

- Enable proxies and use latency strategy.
- Lower concurrency.
- Increase delays between requests.
- Keep humanize enabled (default); try `--no-headless` for hard challenges.
- Use origin mode only when authorized.
- Inspect `{scan_session}/network/*.json` for challenge/CAPTCHA URL hints.

### Empty or partial data

- Increase timeout.
- Crawl deeper with higher `--depth`.
- Verify selectors if using targeted extraction options.

## Contributors

- [Adityaaa](https://github.com/Shellghostt) — author & maintainer

## Contributing Workflow

1. Create a feature branch.
2. Keep changes focused and test locally.
3. Add or update tests where relevant.
4. Open a pull request with a concise summary.

## License

This project is licensed under the [MIT License](LICENSE).
