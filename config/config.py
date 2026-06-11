"""
config.py — Default settings for the dynamic scraper.
Edit these or override via CLI flags.
"""

DEFAULT_CONFIG = {
    # Browser
    "headless": True,
    "timeout": 30000,            # ms to wait for page load
    "wait_until": "networkidle", # domcontentloaded | load | networkidle
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),

    # Crawl limits
    "max_depth": 3,
    "max_pages": 100,

    # Politeness delays (seconds)
    "delay_min": 1.0,
    "delay_max": 3.0,

    # Retry behaviour (on HTTP 429 or network failure)
    "max_retries": 3,

    # Proxy rotation strategy: "random" or "round_robin"
    "proxy_strategy": "random",

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
    "screenshot_on_block": True,        # Capture screenshot when block is detected
    "screenshots_subdir": "screenshots", # Subfolder inside output_dir
}
