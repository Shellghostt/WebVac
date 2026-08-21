# Configuration reference

**Code:** `webvac/config/config.py` (`DEFAULT_CONFIG`) · overlays in `webvac/cli/scraper.py`

CLI flags and interactive defaults merge into a `session_config` dict consumed by BrowserManager, Crawler, CapSolver, and related modules.

---

## 1. Browser & navigation

| Key | Default | CLI / notes |
|-----|---------|-------------|
| `headless` | `True` | `--no-headless` → headed |
| `timeout` | `45000` | `--timeout` (ms) |
| `wait_until` | `load` | `--wait-until` |
| `challenge_wait_ms` | `45000` | CF JS challenge wait |
| `scroll_max_steps` | `30` | Lazy scroll cap |
| `user_agent` | Chrome/133 UA string | Overridable via stealth / proxy identity |
| `spa_delay` | `1500` | ms after load before extract |
| `scroll_viewport` / `scroll_delay` | `1080` / `0.3` | Scroll behaviour |

---

## 2. Crawl limits

| Key | Default | CLI |
|-----|---------|-----|
| `max_depth` | `3` | `--depth` |
| `max_pages` | `None` | `--max-pages` |
| `concurrency` | `1` | `--concurrency` |
| `delay_min` / `delay_max` | `1.0` / `3.0` | `--delay-min` / `--delay-max` |
| `max_retries` | `3` | `--max-retries` |

---

## 3. CapSolver

| Key | Default | CLI |
|-----|---------|-----|
| `captcha_solver` | `capsolver` | `--captcha-solver none\|capsolver` |
| `captcha_api_key` | `""` | `--captcha-api-key` / env / `capsolver.key` |
| `captcha_api_base` | `https://api.capsolver.com` | |
| `captcha_solver_timeout_sec` | `120` | `--captcha-timeout` |
| `captcha_poll_interval_sec` | `2.0` | |
| `captcha_solver_retries` | `2` | |
| `captcha_use_proxy` | `False` | CapSolver proxy task types |
| `captcha_solver_disabled` | unset | Set when CLI forces `none` |

**Runtime rule:** enabled when a real API key exists unless explicitly disabled.

---

## 4. Proxy

| Key | Default | CLI |
|-----|---------|-----|
| `proxy_strategy` | `latency` | `--proxy-strategy` |
| `sticky_requests` | `10` | `--sticky-requests` |
| `proxy_cooldown_seconds` | `300` | `--cooldown-seconds` |
| `max_cooldown_failures` | `3` | |
| `health_check_url` | ipify JSON | |
| playbook | `none` | `--proxy-playbook residential\|datacenter\|none` |

Auto file: `./proxies.txt` when present.

---

## 5. Robots

| Behavior | Flag |
|----------|------|
| Bypass (default) | `--no-robots` default True |
| Obey | `--respect-robots` |
| Ignore crawl-delay | `--ignore-crawl-delay` |

---

## 6. Humanize & consent

| Key | Default | CLI |
|-----|---------|-----|
| `humanize` | `True` | `--no-humanize` |
| `humanize_warmup` | `True` | `--no-humanize-warmup` |
| `humanize_after_goto` | `True` | follows humanize |
| `consent_dismiss` | `True` | `--no-consent-dismiss` |
| `pause_for_consent` | `False` | `--pause-for-consent` (needs headed) |

---

## 7. Network debug & output

| Key | Default | CLI |
|-----|---------|-----|
| `network_debug` | `True` | `--no-network-debug` |
| `network_debug_always` | `False` | `--network-debug-always` |
| `output_dir` | `scraped_data` | `--output` |
| `output_formats` | `json,html` | `--format` |
| `download_pdfs` | `True` | |
| `screenshots` | on | `--no-screenshots` |
| `origin_access` | `None` | library / advanced only |

---

## 8. Auth-related CLI (not all in DEFAULT_CONFIG)

`--login`, `--login-url`, `--username`, `--password`, `--auth-profile`, `--session-file`, `--auth-check-url`, `--on-auth-wall`, `--session-ttl`, `--otp-prompt`, `--dismiss-selector`, `--no-auth-proxy-rotate`, `--allow-subdomains`, `--parent-scan-id`.

---

## 9. VAPT

`--task vapt`, `--decaffeinator-root`, `--vapt-profile`, `--vapt-format`, `--vapt-playwright`, `--vapt-wayback`, `--vapt-no-files`.

See [architecture/VAPT.md](architecture/VAPT.md).

---

## 10. Related

- [CLI](architecture/CLI.md)  
- [SECURITY](SECURITY.md)  
