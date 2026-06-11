"""
scraper.py — Main entry point for the dynamic web scraper.

Usage examples:

  # Scrape a single page
  python scraper.py --url https://example.com --mode single

  # Crawl an entire site (max 50 pages, depth 3)
  python scraper.py --url https://example.com --mode crawl --max-pages 50 --depth 3

  # Login first, then scrape
  python scraper.py --url https://example.com/dashboard --mode single \\
      --login --login-url https://example.com/login \\
      --username myuser@email.com --password mypassword

  # Custom output directory
  python scraper.py --url https://example.com --mode crawl --output ./my_data

  # Visible browser (not headless) for debugging
  python scraper.py --url https://example.com --mode single --no-headless

  # Use a proxy list file
  python scraper.py --url https://example.com --mode crawl --proxy-file proxies.txt

  # Inline proxies (comma-separated; format: server or server|user|pass)
  python scraper.py --url https://example.com --proxies "http://1.2.3.4:8080,http://5.6.7.8:3128"

  # Disable robots.txt checks (use responsibly)
  python scraper.py --url https://example.com --no-robots

  # Obey robots.txt allow/deny but ignore its Crawl-delay directive
  python scraper.py --url https://example.com --ignore-crawl-delay
"""

import asyncio
import argparse
import os
import sys

from colorama import init, Fore, Style
from utils.browser import BrowserManager
from core.crawler import Crawler
from auth.auth import AuthHandler
from data.storage import Storage
from config.config import DEFAULT_CONFIG
from utils.robots import RobotsHandler
from utils.proxy import ProxyManager
from utils.screenshot import ScreenshotModule
from core.pipeline import PipelineManager

init(autoreset=True)  # colorama


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scraper",
        description="Dynamic web scraper — handles JS, auth, crawling, proxies, robots.txt. Outputs JSON + CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required
    p.add_argument("--url", required=True, help="Target URL to scrape or crawl from.")

    # Mode
    p.add_argument(
        "--mode",
        choices=["single", "crawl"],
        default="single",
        help="'single' scrapes one page; 'crawl' follows all internal links. (default: single)",
    )

    # Engine
    p.add_argument(
        "--engine",
        choices=["dynamic", "lightweight"],
        default="dynamic",
        help="Engine to use. dynamic uses Playwright, lightweight uses aiohttp. (default: dynamic)",
    )

    # Crawl limits
    p.add_argument("--depth",     type=int, default=DEFAULT_CONFIG["max_depth"],  help="Max crawl depth (crawl mode only).")
    p.add_argument("--max-pages", type=int, default=None, help="Max pages to scrape (crawl mode only). Omit to crawl the entire site with no page limit.")

    # Browser
    p.add_argument("--no-headless", action="store_true", help="Show the browser window (useful for debugging).")
    p.add_argument("--timeout",   type=int, default=DEFAULT_CONFIG["timeout"],    help="Page-load timeout in milliseconds. (default: 30000)")
    p.add_argument(
        "--wait-until",
        choices=["domcontentloaded", "load", "networkidle"],
        default=DEFAULT_CONFIG["wait_until"],
        help="Playwright lifecycle event to wait for on page load. (default: networkidle)",
    )

    # Login / Auth
    p.add_argument("--login",      action="store_true", help="Enable login before scraping.")
    p.add_argument("--login-url",  default=None,        help="URL of the login page (defaults to --url).")
    p.add_argument("--username",   default=None,        help="Login username or email.")
    p.add_argument("--password",   default=None,        help="Login password.")
    p.add_argument("--username-selector", default=None, help="CSS selector for username field (optional override).")
    p.add_argument("--password-selector", default=None, help="CSS selector for password field (optional override).")
    p.add_argument("--submit-selector",   default=None, help="CSS selector for submit button (optional override).")
    p.add_argument(
        "--session-file",
        default=None,
        metavar="FILE",
        help=(
            "Path to a session cookie file. If the file exists, cookies are loaded "
            "and login is skipped. After a successful --login the session is saved here "
            "for future runs."
        ),
    )

    # Output
    p.add_argument("--output", default=DEFAULT_CONFIG["output_dir"], help="Output directory for JSON/CSV files.")
    p.add_argument("--label",  default=None, help="Custom label for output file names.")

    # Politeness
    p.add_argument("--delay-min", type=float, default=DEFAULT_CONFIG["delay_min"], help="Min delay between requests (seconds).")
    p.add_argument("--delay-max", type=float, default=DEFAULT_CONFIG["delay_max"], help="Max delay between requests (seconds).")

    # Proxy rotation
    p.add_argument(
        "--proxy-file",
        default=None,
        metavar="FILE",
        help=(
            "Path to a proxy list file. One proxy per line, format: "
            "server  OR  server|username|password. Lines starting with # are ignored."
        ),
    )
    p.add_argument(
        "--proxies",
        default=None,
        metavar="PROXY[,PROXY…]",
        help=(
            "Comma-separated list of proxies (same format as --proxy-file lines). "
            "Example: http://1.2.3.4:8080,http://5.6.7.8:3128"
        ),
    )
    p.add_argument(
        "--proxy-strategy",
        choices=["random", "round_robin"],
        default=DEFAULT_CONFIG["proxy_strategy"],
        help="How to pick the next proxy from the pool. (default: random)",
    )
    p.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_CONFIG["max_retries"],
        help="Max retry attempts on HTTP 429 or network errors. (default: 3)",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONFIG["concurrency"],
        help="Number of pages to scrape in parallel (crawl mode). (default: 1)",
    )

    # Targeted Extraction
    p.add_argument(
        "--extract-css",
        nargs="+",
        default=None,
        metavar="KEY=SELECTOR",
        help="Extract specific data using CSS selectors (e.g. title=h1.title price=.price)",
    )
    p.add_argument(
        "--extract-xpath",
        nargs="+",
        default=None,
        metavar="KEY=XPATH",
        help="Extract specific data using XPath (e.g. author=//span[@id='author'])",
    )

    # Link Rules
    p.add_argument(
        "--allow-url-regex",
        default=None,
        help="Regex pattern; only URLs matching this will be added to the crawl queue.",
    )
    p.add_argument(
        "--deny-url-regex",
        default=None,
        help="Regex pattern; URLs matching this will be ignored in the crawl queue.",
    )

    # Pipeline
    p.add_argument(
        "--pipeline-file",
        default=None,
        help="Path to a Python file containing data cleaning pipelines.",
    )


    # robots.txt
    p.add_argument(
        "--no-robots",
        action="store_true",
        help="Ignore robots.txt entirely (use responsibly).",
    )
    p.add_argument(
        "--ignore-crawl-delay",
        action="store_true",
        help="Obey robots.txt allow/deny rules but ignore its Crawl-delay directive.",
    )

    # Output formats
    p.add_argument(
        "--format",
        default=DEFAULT_CONFIG["output_formats"],
        metavar="FMT[,FMT…]",
        help=(
            "Comma-separated output formats: json, csv, markdown, sqlite, html, all. "
            "(default: json,csv,html)"
        ),
    )

    # Screenshots
    p.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Disable automatic screenshots of CAPTCHA / bot-block pages.",
    )

    return p


async def run(args):
    # ── Banner ───────────────────────────────────────────────────────────────
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  Dynamic Web Scraper")
    print(f"  URL         : {args.url}")
    print(f"  Mode        : {args.mode}")
    print(f"  Login       : {'yes' if args.login else 'no'}")
    print(f"  Robots      : {'disabled (--no-robots)' if args.no_robots else 'enabled'}")
    proxy_label = (
        args.proxy_file or
        (f"{len(args.proxies.split(','))} inline" if args.proxies else "none")
    )
    print(f"  Proxies     : {proxy_label}")
    print(f"  Concurrency : {args.concurrency}")
    print(f"{'='*60}{Style.RESET_ALL}\n")

    screenshots_enabled = not getattr(args, "no_screenshots", False)
    print(f"  Screenshots : {'enabled (CAPTCHA pages only)' if screenshots_enabled else 'disabled'}")
    print(f"{'='*60}{Style.RESET_ALL}\n")

    # ── Output formats ────────────────────────────────────────────────────────
    _valid_formats = {"json", "csv", "markdown", "sqlite", "html"}
    raw_fmt = [f.strip().lower() for f in args.format.split(",")]
    if "all" in raw_fmt:
        output_formats = ["json", "csv", "markdown", "sqlite", "html"]
    else:
        output_formats = [f for f in raw_fmt if f in _valid_formats]
        if not output_formats:
            print(f"{Fore.YELLOW}[Warning] No valid --format values; defaulting to json,csv,html{Style.RESET_ALL}")
            output_formats = ["json", "csv", "html"]
    print(f"  Formats     : {', '.join(output_formats)}")
    print(f"{'='*60}{Style.RESET_ALL}\n")

    # ── robots.txt handler ───────────────────────────────────────────────────
    robots = None
    if not args.no_robots:
        robots = RobotsHandler(
            user_agent="*",
            respect_robots=True,
            respect_crawl_delay=not args.ignore_crawl_delay,
        )

    # ── Proxy manager ─────────────────────────────────────────────────────────
    proxy_manager = None
    initial_proxy_entry = None
    initial_proxy_dict = None

    if args.proxy_file:
        try:
            proxy_manager = ProxyManager.from_file(
                args.proxy_file, strategy=args.proxy_strategy,
                max_failures=args.max_retries,
            )
        except Exception as exc:
            print(f"{Fore.RED}[Error] Could not load proxy file: {exc}{Style.RESET_ALL}")
            return
    elif args.proxies:
        proxy_list = [p.strip() for p in args.proxies.split(",") if p.strip()]
        try:
            proxy_manager = ProxyManager.from_strings(
                proxy_list, strategy=args.proxy_strategy,
                max_failures=args.max_retries,
            )
        except Exception as exc:
            print(f"{Fore.RED}[Error] Could not parse proxies: {exc}{Style.RESET_ALL}")
            return

    if proxy_manager:
        initial_proxy_entry = proxy_manager.get_next()
        if initial_proxy_entry:
            initial_proxy_dict = initial_proxy_entry.to_playwright()

    # ── Browser ───────────────────────────────────────────────────────────────
    browser = BrowserManager(
        headless=not args.no_headless,
        rotate_user_agent=DEFAULT_CONFIG["rotate_user_agent"],
        rotate_geolocation=DEFAULT_CONFIG["rotate_geolocation"],
        rotate_viewport=DEFAULT_CONFIG["rotate_viewport"],
    )
    await browser.start(proxy=initial_proxy_dict)

    try:
        # ── Session restore (skips re-login if cookie file exists) ───────────
        auth = AuthHandler()
        session_restored = False
        if args.session_file and os.path.isfile(args.session_file):
            session_restored = await auth.restore_session(
                browser.context, args.session_file
            )
            if session_restored:
                print(f"{Fore.GREEN}[Auth] Session restored from {args.session_file} — skipping login.{Style.RESET_ALL}")

        # ── Login ─────────────────────────────────────────────────────────────
        if args.login and not session_restored:
            if not args.username or not args.password:
                print(f"{Fore.RED}[Error] --username and --password are required with --login{Style.RESET_ALL}")
                return

            login_page = await browser.new_page()
            login_url = args.login_url or args.url

            if args.username_selector and args.password_selector:
                success = await auth.login_with_selectors(
                    login_page, login_url,
                    args.username, args.password,
                    args.username_selector, args.password_selector,
                    args.submit_selector,
                    timeout=args.timeout,
                    wait_until=args.wait_until,
                )
            else:
                success = await auth.login(
                    login_page, login_url,
                    args.username, args.password,
                    timeout=args.timeout,
                    wait_until=args.wait_until,
                )

            await login_page.close()

            if success and args.session_file:
                await auth.save_session(browser.context, args.session_file)

            if not success:
                print(f"{Fore.YELLOW}[Warning] Login may have failed -- continuing anyway.{Style.RESET_ALL}")

        # ── Crawl / Scrape ────────────────────────────────────────────────────
        # ScreenshotModule (CAPTCHA pages only)
        screenshot_module = None
        if screenshots_enabled:
            screenshot_module = ScreenshotModule(
                output_dir=args.output,
                screenshots_subdir=DEFAULT_CONFIG["screenshots_subdir"],
            )

        pipeline_manager = PipelineManager(args.pipeline_file) if args.pipeline_file else None

        crawler = Crawler(
            browser=browser,
            max_depth=args.depth,
            max_pages=args.max_pages,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            timeout=args.timeout,
            robots_handler=robots,
            proxy_manager=proxy_manager,
            max_retries=args.max_retries,
            concurrency=args.concurrency,
            wait_until=args.wait_until,
            screenshot_module=screenshot_module,
            output_dir=args.output,
            extract_css=args.extract_css,
            extract_xpath=args.extract_xpath,
            allow_url_regex=args.allow_url_regex,
            deny_url_regex=args.deny_url_regex,
            pipeline_manager=pipeline_manager,
            engine=args.engine,
        )

        # Tell the crawler which proxy is currently wired into the browser
        if initial_proxy_entry:
            crawler._current_proxy = initial_proxy_entry

        if args.mode == "single":
            results = await crawler.scrape_single(args.url)
        else:
            results = await crawler.scrape_site(args.url)

        # ── Save ──────────────────────────────────────────────────────────────
        if results:
            storage = Storage(output_dir=args.output)
            paths = storage.save(results, label=args.label, formats=output_formats)
            print(f"\n{Fore.GREEN}Success: Scrape complete! {len(results)} page(s) saved.{Style.RESET_ALL}")
            for fmt, path in paths.items():
                print(f"  {fmt.upper():8s} -> {path}")
        else:
            print(f"\n{Fore.YELLOW}No data was collected.{Style.RESET_ALL}")

    finally:
        await browser.stop()


def main():
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
