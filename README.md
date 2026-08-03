# WebVac

WebVac is an asyncio-powered dynamic web scraping and crawling tool built for modern JavaScript-heavy targets. It drives a real Chromium browser through Patchright, supports proxy rotation, robots handling, anti-bot resilience, optional login/session reuse, and exports rich scan artifacts in multiple formats.

## Highlights

- Dynamic scraping with a real browser engine (Patchright)
- Single-page and recursive crawl modes
- Concurrency support with isolated browser slot identities
- Proxy pools with latency-based selection, round-robin, or random strategy
- robots.txt support with optional crawl-delay override
- Cloudflare-origin bypass helpers (manual origin IP and CF-Hero integration)
- Automatic screenshots for blocked/CAPTCHA pages
- Structured output in JSON, CSV, HTML, Markdown, SQLite, or all formats
- Historical scan sessions and diff generation between runs
- PDF and sourcemap asset download support
- Unified auth: Patchright login, session restore, MFA/TOTP, OAuth bootstrap
- Mid-crawl auth-wall handling, logout URL deny, and sticky proxy when authenticated
- Optional VAPT/recon pipeline present in codebase (disabled by default)

## Project Structure

All application code lives in the installable `webvac/` package. See [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

- `run.py`: Thin shim → interactive menu (`webvac.cli.interactive`)
- `webvac/cli/scraper.py`: Main CLI orchestrator (`python -m webvac`)
- `webvac/core/`: BFS crawler, page scrape flow, pipelines, VAPT runner
- `webvac/auth/`: AuthManager, sessions, MFA, auth-wall detection
- `webvac/utils/`: Browser, proxies, robots, CF-Hero, screenshots
- `webvac/data/`: HTML parse, page records, storage/export
- `webvac/collectors|analyzers|findings|active/`: Optional VAPT stack (default off)
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

### Windows PowerShell

```powershell
python -m venv .venv
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& .\.venv\Scripts\Activate.ps1)
pip install -r requirements.txt
pip install -e .
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

`pip install -e .` registers the `webvac` and `webvac-menu` console scripts and makes imports resolve as `webvac.*`.

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

The launcher helps you choose scrape mode, output formats, robots strategy, proxy mode, and browser visibility.

### Direct CLI usage

```bash
python -m webvac --url https://example.com --mode single
```

```bash
python -m webvac --url https://example.com --mode crawl --depth 3 --max-pages 50 --concurrency 2
```

## Common CLI Options

### Core

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
- `--auth-bootstrap`: Open a visible browser for manual OAuth/SSO, then export `--session-file`
- `--otp-prompt`: Prompt for OTP/MFA when an OTP field appears
- `--no-auth-proxy-rotate`: Pin proxy while authenticated (also default when `--login`)
- `--dismiss-selector CSS`: Extra Accept-button selector (repeatable; login + every scrape)
- `--pause-for-consent`: Headed wait-for-ENTER after first page per host (use with `--no-headless`)
- `--no-consent-dismiss`: Disable automatic cookie/CMP Accept clicks on scraped pages

Known-site CMP URL bypasses (applied automatically when the host matches): e.g. Deloitte gets `?hidebanner=true`. Google/YouTube get a `CONSENT=YES+` cookie before navigation. Not applied to unknown sites.
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
- `--sticky-requests N`: Requests before voluntary rotate
- `--cooldown-seconds SECS`: Cooldown after 429/timeout
- `--no-health-check`: Skip startup benchmark

### Origin bypass / CF-Hero

Requires [CF-Hero](https://github.com/musana/CF-Hero) on PATH (`go install -v github.com/musana/cf-hero/cmd/cf-hero@latest`).

- `--origin-ip IP`: Scrape using origin IP + Host header
- `--cf-hero`: Discover origin IP via CF-Hero first (uses `-f` tempfile — correct CF-Hero CLI)
- `--cf-hero-bin PATH`: Explicit CF-Hero executable path
- `--cf-hero-args "..."`: Extra flags (e.g. `"-shodan -censys -securitytrails -zoomeye"`)
- `--cf-hero-timeout SECS`: CF-Hero process timeout (default 300)
- `--cf-hero-workers N`: CF-Hero `-w` worker count
- `--cf-hero-quiet`: Omit CF-Hero `-v`
- `--cf-hero-log FILE`: Save raw CF-Hero output
- `--origin-title TITLE`: Expected title for validation (also passed as CF-Hero `-title`)
- `--skip-origin-validate`: Use discovered/manual IP without title check
- `--no-cf-hero-auto`: Disable mid-crawl auto discovery on bot/WAF blocks

See [`docs/architecture/CF_HERO.md`](docs/architecture/CF_HERO.md).

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
        assets/
          pdfs/
          sourcemaps/
          screenshots/
        meta/
          meta.json
          session.json
    diffs/
      ...
```

## Architecture Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Full system architecture (layers, sequence, status matrix)
- [`docs/architecture/AUTH.md`](docs/architecture/AUTH.md) — Authentication / sessions / MFA / auth-walls
- [`docs/architecture/CRAWL.md`](docs/architecture/CRAWL.md) — Crawler, page flow, browser pool
- [`docs/architecture/DATA.md`](docs/architecture/DATA.md) — Parsing, page records, storage layout
- [`docs/architecture/PROXY_ORIGIN.md`](docs/architecture/PROXY_ORIGIN.md) — Proxies, robots, CF-Hero / origin
- [`docs/architecture/CF_HERO.md`](docs/architecture/CF_HERO.md) — Complete CF-Hero CLI + validation flow
- [`docs/architecture/VAPT.md`](docs/architecture/VAPT.md) — Optional collectors → analyzers → findings
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
- VAPT/recon modules exist but are disabled by default in configuration.
- Default output formats are `json,csv,html`.

## Troubleshooting

### Browser launch or navigation fails

- Ensure dependencies are installed in the active virtual environment.
- Try visible browser mode with `--no-headless`.
- Switch wait strategy to `--wait-until domcontentloaded`.

### Frequent bot/challenge blocks

- Enable proxies and use latency strategy.
- Lower concurrency.
- Increase delays between requests.
- Use origin mode only when authorized.

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

Add your preferred license file and update this section accordingly.
