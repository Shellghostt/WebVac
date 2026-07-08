"""
config.py — Default settings for the dynamic scraper.
Edit these or override via CLI flags.
"""

DEFAULT_CONFIG = {
    # Browser
    "headless": True,
    "timeout": 45000,            # ms to wait for page load
    "wait_until": "domcontentloaded", # domcontentloaded | load | networkidle
    "challenge_wait_ms": 45000,  # ms to wait for CF/JS challenges to resolve
    "scroll_max_steps": 30,      # cap lazy-scroll iterations per page
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),

    # Crawl limits
    "max_depth": 3,
    "max_pages": None,

    # CAPTCHA manual prompt timeout (seconds); 0 = wait forever
    "captcha_prompt_timeout_sec": 300,

    # Politeness delays (seconds)
    "delay_min": 1.0,
    "delay_max": 3.0,

    # Retry behaviour (on HTTP 429 or network failure)
    "max_retries": 3,

    # Proxy rotation strategy: "latency" (recommended), "random", "round_robin"
    # "latency" benchmarks all proxies at startup and always prefers the fastest.
    "proxy_strategy": "latency",

    # Sticky sessions: how many requests to make on one proxy before voluntarily
    # rotating. 0 = rotate on every request. Recommended: 10.
    "sticky_requests": 10,

    # Cool-down queue: instead of immediately retiring a proxy that hits a 429
    # or timeout, put it in a cool-down queue for this many seconds, then retry.
    # Only permanently retire after max_cooldown_failures consecutive cool-down failures.
    "proxy_cooldown_seconds": 300,
    "max_cooldown_failures": 3,

    # Health-check URL: used to benchmark proxies at startup.
    # Must return JSON with an "origin" or "ip" key.
    "health_check_url": "http://api.ipify.org/?format=json",

    # robots.txt — set to False to disable entirely
    "respect_robots": True,

    # Concurrent pages to scrape at once (1 = sequential, backward-compatible)
    "concurrency": 1,

    # Output
    "output_dir": "scraped_data",

    # Comma-separated output formats: json, csv, markdown, sqlite, html, all
    "output_formats": "json,csv,html",

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

    # Crawler rendering & scroll settings
    "spa_delay": 1500,           # ms to wait for SPA load / JS settling
    "scroll_viewport": 1080,     # height step size for dynamic scrolling
    "scroll_delay": 0.3,         # seconds to wait after each scroll step

    # Interactive/Auth delays (seconds/ms)
    "typing_delay": 80,          # ms between keystrokes
    "field_delay": 0.5,          # seconds to pause between auth fields

    # Screenshot settings (CAPTCHA / bot-block pages only)
    "screenshot_on_block": True,
    "screenshots_subdir": "screenshots",

    # VAPT pipeline — disabled until re-enabled from scraper
    "vapt_enabled": False,

    "profile": "scrape",
    "allowed_domains": [],
    "allow_subdomains": False,
    "max_requests": None,
    "exclude_patterns": [],
    "include_patterns": [],

    "collectors": {
        "http": False,
        "html": False,
        "storage": False,
        "network": False,
        "javascript": False,
    },
    "analyzers": {
        "headers": False,
        "cookies": False,
        "auth": False,
        "storage": False,
        "js": False,
        "sourcemap": False,
        "network": False,
        "tech": False,
        "graphql": False,
        "oauth": False,
        "cloud": False,
    },
    "active_recon": False,
    "active_probes": {
        "files": False,
        "graphql": False,
        "swagger": False,
        "git": False,
        "env": False,
    },
    "active_probe_concurrency": 5,
    "active_probe_delay": 0.3,
    "javascript": {
        "download_external": False,
        "fetch_source_maps": False,
        "concurrency": 5,
    },

    # Origin bypass (CF-Hero / manual IP)
    "origin_access": None,  # OriginTarget dict at runtime
    "cf_hero_auto_fallback": True,
    "cf_hero_bin": None,
    "cf_hero_args": "",

    # Download PDF links discovered during crawl
    "download_pdfs": True,
}
