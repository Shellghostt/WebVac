"""
config.py — Default settings for the dynamic scraper.
Edit these or override via CLI flags.
"""

DEFAULT_CONFIG = {
    # Browser
    "headless": True,
    "timeout": 45000,            # ms to wait for page load
    "wait_until": "load",  # domcontentloaded | load | networkidle
    "challenge_wait_ms": 45000,  # ms to wait for CF/JS challenges to resolve
    "scroll_max_steps": 30,      # cap lazy-scroll iterations per page
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),

    # Crawl limits
    "max_depth": 3,
    "max_pages": None,

    # CAPTCHA manual prompt timeout (seconds); 0 = wait forever
    "captcha_prompt_timeout_sec": 300,

    # Auto CAPTCHA solver (CapSolver). Enabled automatically when an API key is present.
    # Use captcha_solver=none (or --captcha-solver none) to force disable.
    "captcha_solver": "capsolver",     # none | capsolver
    "captcha_api_key": "",             # or env CAPSOLVER_API_KEY / WEBVAC_CAPSOLVER_KEY / capsolver.key
    "captcha_api_base": "https://api.capsolver.com",
    "captcha_solver_timeout_sec": 120,
    "captcha_poll_interval_sec": 2.0,
    "captcha_solver_retries": 2,
    "captcha_use_proxy": False,
    "captcha_fallback_manual": False,

    # Politeness delays (seconds)
    "delay_min": 1.0,
    "delay_max": 3.0,

    # Retry behaviour (on HTTP 429 or network failure)
    "max_retries": 3,

    # Proxy rotation strategy: "latency" (recommended), "random", "round_robin"
    # "latency" benchmarks all proxies at startup and always prefers the fastest.
    "proxy_strategy": "latency",

    # Sticky sessions: successful requests on one proxy before voluntary rotate.
    # 0 = disable voluntary rotate (stay on the same proxy). Recommended: 10.
    "sticky_requests": 10,

    # Cool-down queue: instead of immediately retiring a proxy that hits a 429
    # or timeout, put it in a cool-down queue for this many seconds, then retry.
    # Only permanently retire after max_cooldown_failures consecutive cool-down failures.
    "proxy_cooldown_seconds": 300,
    "max_cooldown_failures": 3,

    # Health-check URL: used to benchmark proxies at startup.
    # Must return JSON with an "origin" or "ip" key.
    "health_check_url": "http://api.ipify.org/?format=json",

    # robots.txt is bypassed by default via CLI --no-robots
    # (kept here only as documentation of intent; scraper uses argparse)

    # Concurrent pages to scrape at once (1 = sequential, backward-compatible)
    "concurrency": 1,

    # Output
    "output_dir": "scraped_data",

    # Comma-separated output formats: json, csv, markdown, sqlite, html, all
    "output_formats": "json,html",

    # Stealth / Anti-detection settings
    # Locale and Accept-Language always forced to US English
    "locale": "en-US",
    "timezone_id": "America/New_York",   # fallback only — overridden by geolocation rotation
    "accept_language": "en-US,en;q=0.9",

    # Rotate a random User-Agent from a curated pool on each new context
    "rotate_user_agent": True,

    # Rotate a random US city (lat/lon + matching timezone) on each new context
    "rotate_geolocation": True,

    # Rotate a random realistic viewport size on each new context
    "rotate_viewport": True,

    # Human-like pointer / scroll / settle (Patchright Chromium)
    "humanize": True,
    "humanize_warmup": True,       # visit site root once per host before scraping
    "humanize_after_goto": True,   # micro-moves after each successful load
    "humanize_idle_min": 0.35,
    "humanize_idle_max": 1.6,
    "humanize_type_delay_max_ms": 160,

    # Crawler rendering & scroll settings
    "spa_delay": 1500,           # ms to wait for SPA load / JS settling
    "scroll_viewport": 1080,     # height step size for dynamic scrolling
    "scroll_delay": 0.3,         # seconds to wait after each scroll step

    # Interactive/Auth delays (seconds/ms)
    "typing_delay": 80,          # ms between keystrokes
    "field_delay": 0.5,          # seconds to pause between auth fields

    # Screenshot settings (CAPTCHA / bot-block pages only; CLI --no-screenshots to disable)
    "screenshots_subdir": "screenshots",

    "allowed_domains": [],
    "allow_subdomains": False,
    "exclude_patterns": [],
    "include_patterns": [],

    # Origin bypass (optional OriginTarget dict via session_config — no CLI flag)
    "origin_access": None,
    "network_debug": True,
    "network_debug_always": False,

    # Download PDF links discovered during crawl
    "download_pdfs": True,

    # CMP / cookie consent
    "consent_dismiss": True,       # auto-click Accept on every dynamic page
    "pause_for_consent": False,    # headed wait-for-ENTER (once per host)
    "dismiss_selectors": [],       # extra Accept CSS selectors
}
