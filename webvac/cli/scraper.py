"""
scraper.py — Main entry point for the dynamic web scraper.

Usage examples:

  # Scrape a single page
  python -m webvac --url https://example.com --mode single

  # Crawl an entire site (max 50 pages, depth 3)
  python -m webvac --url https://example.com --mode crawl --max-pages 50 --depth 3

  # Login first, then scrape
  python -m webvac --url https://example.com/dashboard --mode single \\
      --login --login-url https://example.com/login \\
      --username myuser@email.com --password mypassword

  # Custom output directory
  python -m webvac --url https://example.com --mode crawl --output ./my_data

  # Visible browser (not headless) for debugging
  python -m webvac --url https://example.com --mode single --no-headless

  # Use a proxy list file
  python -m webvac --url https://example.com --mode crawl --proxy-file proxies.txt

  # Inline proxies (comma-separated; format: server or server|user|pass)
  python -m webvac --url https://example.com --proxies "http://1.2.3.4:8080,http://5.6.7.8:3128"

  # Disable robots.txt checks (use responsibly)
  python -m webvac --url https://example.com --no-robots

  # Obey robots.txt allow/deny but ignore its Crawl-delay directive
  python -m webvac --url https://example.com --ignore-crawl-delay
"""

import asyncio
import argparse
import os
import sys
from typing import Optional

from colorama import init, Fore, Style
from webvac.utils.browser import BrowserManager
from webvac.core.crawler import Crawler
from webvac.auth.manager import AuthManager, build_profile_from_args
from webvac.auth.credentials import resolve_credentials
from webvac.data.storage import Storage
from webvac.config.config import DEFAULT_CONFIG
from webvac.utils.robots import RobotsHandler
from webvac.utils.proxy import ProxyManager
from webvac.utils.screenshot import ScreenshotModule
from webvac.core.pipeline import PipelineManager
from webvac.store.scan_session import ScanSession
from webvac.utils.asset_downloader import AssetDownloader, collect_pdf_urls
from webvac.models.origin import OriginTarget
from webvac.utils.origin_probe import validate_origin, fetch_vanity_title
from webvac.utils.cf_hero import discover_origin, find_cf_hero_bin
from webvac.utils.browser_pool import SlotIdentity
from urllib.parse import urlparse

init(autoreset=True)  # colorama


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webvac",
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
        help="Engine to use. dynamic uses Patchright, lightweight uses aiohttp. (default: dynamic)",
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
        help="Patchright lifecycle event to wait for on page load. (default: domcontentloaded)",
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
        "--dismiss-selector",
        action="append",
        default=None,
        metavar="CSS",
        help=(
            "Extra CSS selector for cookie/privacy Accept buttons (can repeat). "
            "Tried before built-in OneTrust/Cookiebot/etc. patterns on login AND every scrape."
        ),
    )
    p.add_argument(
        "--pause-for-consent",
        action="store_true",
        help=(
            "After each host's first page load, wait for ENTER so you can Accept a CMP "
            "in a headed browser (--no-headless). Auto-dismiss still runs first."
        ),
    )
    p.add_argument(
        "--no-consent-dismiss",
        action="store_true",
        help="Disable automatic cookie/CMP Accept clicks on scraped pages.",
    )
    p.add_argument(
        "--session-file",
        default=None,
        metavar="FILE",
        help=(
            "Path to a session storage_state file. If the file exists, cookies are loaded "
            "and login is skipped. After a successful --login the session is saved here "
            "for future runs."
        ),
    )
    p.add_argument(
        "--auth-check-url",
        default=None,
        metavar="URL",
        help="Protected URL used to verify login/session is authenticated.",
    )
    p.add_argument(
        "--on-auth-wall",
        choices=["abort", "skip", "relogin"],
        default="skip",
        help="When a login wall is hit mid-crawl: abort, skip page, or relogin (default: skip).",
    )
    p.add_argument(
        "--session-ttl",
        type=int,
        default=0,
        metavar="SECS",
        help="Session TTL in seconds (0 = never expire). Checked on restore.",
    )
    p.add_argument(
        "--auth-bootstrap",
        action="store_true",
        help="Open a visible browser for manual OAuth/SSO login, then export --session-file.",
    )
    p.add_argument(
        "--otp-prompt",
        action="store_true",
        help="Prompt for OTP/MFA codes during login when an OTP field appears.",
    )
    p.add_argument(
        "--auth-profile",
        default=None,
        metavar="FILE",
        help="Rich auth credentials/profile JSON (steps, totp, selectors, policies).",
    )
    p.add_argument(
        "--no-auth-proxy-rotate",
        action="store_true",
        default=False,
        help="When logging in, disable voluntary proxy rotation to keep the session IP stable.",
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

    # Proxy rotation strategy
    p.add_argument(
        "--proxy-strategy",
        choices=["latency", "random", "round_robin"],
        default=DEFAULT_CONFIG["proxy_strategy"],
        help="How to select the next proxy. 'latency' (default) benchmarks all proxies at startup and always picks the fastest.",
    )

    # Sticky sessions
    p.add_argument(
        "--sticky-requests",
        type=int,
        default=DEFAULT_CONFIG["sticky_requests"],
        metavar="N",
        help=(
            "Number of successful requests to make on one proxy before voluntarily "
            "rotating to the next. 0 disables sticky sessions. (default: 10)"
        ),
    )

    # Proxy cool-down
    p.add_argument(
        "--cooldown-seconds",
        type=float,
        default=DEFAULT_CONFIG["proxy_cooldown_seconds"],
        metavar="SECS",
        help=(
            "Seconds to put a proxy on cool-down after a 429 or timeout before "
            "retrying it. (default: 300)"
        ),
    )

    # Health-check
    p.add_argument(
        "--health-check-url",
        default=DEFAULT_CONFIG["health_check_url"],
        metavar="URL",
        help=(
            "URL used to benchmark proxies at startup. Must return JSON with an "
            "'origin' or 'ip' key. (default: http://httpbin.org/ip)"
        ),
    )
    p.add_argument(
        "--no-health-check",
        action="store_true",
        help="Skip the proxy benchmark / health-check at startup.",
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

    # Manual CAPTCHA solver
    p.add_argument(
        "--no-captcha-prompt",
        action="store_true",
        help=(
            "Disable the interactive manual CAPTCHA prompt. When set, WebVac will "
            "skip the page instead of pausing to ask you to solve the CAPTCHA. "
            "Use this flag in automated / CI environments."
        ),
    )

    p.add_argument(
        "--parent-scan-id",
        default=None,
        metavar="SCAN_ID",
        help="Link this scan to a parent session (default: latest prior scan for target).",
    )

    p.add_argument(
        "--allow-subdomains",
        action="store_true",
        help="Follow subdomains of the target during crawl.",
    )

    # Cloudflare origin bypass (CF-Hero)
    p.add_argument(
        "--origin-ip",
        default=None,
        metavar="IP",
        help="Scrape via origin IP with Host header (bypass CDN edge).",
    )
    p.add_argument(
        "--cf-hero",
        action="store_true",
        help="Run CF-Hero to discover origin IP before scraping (requires cf-hero on PATH).",
    )
    p.add_argument(
        "--cf-hero-bin",
        default=None,
        metavar="PATH",
        help="Path to cf-hero binary (default: search PATH / ~/go/bin).",
    )
    p.add_argument(
        "--cf-hero-args",
        default="",
        metavar="ARGS",
        help='Extra cf-hero flags, e.g. "-shodan -censys -securitytrails -zoomeye".',
    )
    p.add_argument(
        "--cf-hero-timeout",
        type=int,
        default=300,
        metavar="SECS",
        help="CF-Hero process timeout in seconds (default: 300).",
    )
    p.add_argument(
        "--cf-hero-workers",
        type=int,
        default=0,
        metavar="N",
        help="CF-Hero worker count (-w). 0 = tool default.",
    )
    p.add_argument(
        "--cf-hero-quiet",
        action="store_true",
        help="Do not pass -v to CF-Hero.",
    )
    p.add_argument(
        "--origin-title",
        default=None,
        metavar="TITLE",
        help="Expected HTML title for origin validation (also passed to CF-Hero -title).",
    )
    p.add_argument(
        "--skip-origin-validate",
        action="store_true",
        help="Use first CF-Hero/manual IP without title validation (use responsibly).",
    )
    p.add_argument(
        "--no-cf-hero-auto",
        action="store_true",
        help="Disable automatic CF-Hero origin discovery when bot/WAF blocks are detected.",
    )
    p.add_argument(
        "--cf-hero-log",
        default=None,
        metavar="FILE",
        help="Write raw CF-Hero stdout/stderr to this file.",
    )

    return p


_DEFAULT_SEC_CH_UA = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'


def _proxy_to_identity(entry) -> SlotIdentity:
    return SlotIdentity(
        proxy=entry.to_patchright(),
        ua=entry.pinned_ua or "",
        platform=entry.pinned_platform or "Windows",
        sec_ch_ua=entry.pinned_sec_ch_ua or _DEFAULT_SEC_CH_UA,
    )


def _assign_slot_proxies(proxy_manager, concurrency: int, first_entry=None) -> list:
    """Pick one proxy per concurrent worker slot."""
    entries = []
    for i in range(concurrency):
        if i == 0 and first_entry:
            entries.append(first_entry)
        elif proxy_manager:
            entries.append(proxy_manager.get_next())
        else:
            entries.append(None)
    return entries


async def _resolve_origin_access(args, seed_url: str, proxy_url: str | None):
    """Resolve OriginTarget from --origin-ip or --cf-hero."""
    hostname = urlparse(seed_url).netloc.split("@")[-1].split(":")[0].lower()
    if not hostname:
        print(f"{Fore.RED}[Origin] Invalid URL — no hostname{Style.RESET_ALL}")
        return None

    if args.origin_ip:
        parsed = urlparse(seed_url)
        scheme = parsed.scheme or "https"
        port = parsed.port or (443 if scheme == "https" else 80)
        origin = OriginTarget(
            hostname=hostname,
            origin_ip=args.origin_ip.strip(),
            scheme=scheme,
            port=port,
            source="manual",
        )
        if args.skip_origin_validate:
            origin.validated = True
            print(f"{Fore.CYAN}[Origin] Using manual IP {origin.origin_ip} (validation skipped){Style.RESET_ALL}")
            return origin

        title = args.origin_title or await fetch_vanity_title(seed_url, proxy=proxy_url)
        origin.expected_title = title or ""
        if await validate_origin(
            origin, seed_url, expected_title=title, proxy=proxy_url,
        ):
            origin.validated = True
            print(f"{Fore.GREEN}[Origin] Validated manual IP {origin.origin_ip}{Style.RESET_ALL}")
            return origin
        print(f"{Fore.YELLOW}[Origin] Manual IP {origin.origin_ip} failed title validation{Style.RESET_ALL}")
        return None

    if args.cf_hero:
        if not find_cf_hero_bin(args.cf_hero_bin):
            print(
                f"{Fore.RED}[CF-Hero] cf-hero not found. Install: "
                f"go install -v github.com/musana/cf-hero/cmd/cf-hero@latest{Style.RESET_ALL}"
            )
            return None
        extra = [a for a in args.cf_hero_args.split() if a] if args.cf_hero_args else None
        log_path = args.cf_hero_log
        if not log_path:
            # Default log next to output root for auditability
            log_path = os.path.join(args.output or "scraped_data", "_cf_hero", f"{hostname}.log")
        origin = await discover_origin(
            seed_url,
            hostname,
            bin_path=args.cf_hero_bin,
            extra_args=extra,
            expected_title=args.origin_title or "",
            proxy=proxy_url,
            validate=not args.skip_origin_validate,
            verbose=not args.cf_hero_quiet,
            workers=args.cf_hero_workers or None,
            timeout_sec=float(args.cf_hero_timeout or 300),
            log_path=log_path,
        )
        if origin and args.skip_origin_validate and not origin.validated:
            origin.validated = True
            print(
                f"{Fore.YELLOW}[CF-Hero] Using unvalidated IP {origin.origin_ip} "
                f"(--skip-origin-validate){Style.RESET_ALL}"
            )
        return origin

    return None


async def _persist_run(
    args,
    crawler,
    results: list,
    session_config: dict,
    output_formats: list,
    *,
    interrupted: bool = False,
) -> None:
    """Download assets and write scrape output files."""
    if not results:
        print(f"\n{Fore.YELLOW}No data was collected.{Style.RESET_ALL}")
        return

    scan = crawler._scan if crawler else None
    if scan:
        ScanSession(args.output, scan).apply_parent_chain(args.parent_scan_id)

    assets_meta: dict = {}
    origin = session_config.get("origin_access")
    if origin:
        assets_meta["origin_access"] = origin
    if scan:
        sess = ScanSession(args.output, scan)
        sess.ensure_dirs()
        layout = sess.layout_paths()
        if session_config.get("download_pdfs", True):
            pdf_urls = collect_pdf_urls(results)
            if pdf_urls:
                dl = AssetDownloader(layout["assets_pdfs"])
                proxy = session_config.get("_proxy_url")
                pdf_results = await dl.download_pdfs(pdf_urls, proxy=proxy)
                assets_meta["pdfs_downloaded"] = sum(
                    1 for r in pdf_results if r.get("status") in ("ok", "cached")
                )
                assets_meta["pdf_results"] = pdf_results

    storage = Storage(output_dir=args.output)
    paths = storage.save(
        results,
        label=args.label,
        formats=output_formats,
        scan=scan,
        interrupted=interrupted,
        assets_meta=assets_meta,
    )

    label = "Partial save" if interrupted else "Success"
    print(f"\n{Fore.GREEN}{label}: {len(results)} page(s) saved.{Style.RESET_ALL}")
    for fmt, path in paths.items():
        if fmt == "session_dir":
            continue
        print(f"  {fmt.upper():8s} -> {path}")
    if scan:
        print(f"\n{Fore.CYAN}Scan ID: {scan.scan_id}{Style.RESET_ALL}")
        if scan.parent_scan_id:
            print(f"  Parent:  {scan.parent_scan_id}")
    if interrupted:
        print(f"\n{Fore.YELLOW}Run was interrupted — open scrape/report.html for partial results.{Style.RESET_ALL}")


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
                args.proxy_file,
                strategy=args.proxy_strategy,
                max_failures=args.max_retries,
                cooldown_seconds=args.cooldown_seconds,
                max_cooldown_failures=DEFAULT_CONFIG["max_cooldown_failures"],
            )
        except Exception as exc:
            print(f"{Fore.RED}[Error] Could not load proxy file: {exc}{Style.RESET_ALL}")
            return
    elif args.proxies:
        proxy_list = [p.strip() for p in args.proxies.split(",") if p.strip()]
        try:
            proxy_manager = ProxyManager.from_strings(
                proxy_list,
                strategy=args.proxy_strategy,
                max_failures=args.max_retries,
                cooldown_seconds=args.cooldown_seconds,
                max_cooldown_failures=DEFAULT_CONFIG["max_cooldown_failures"],
            )
        except Exception as exc:
            print(f"{Fore.RED}[Error] Could not parse proxies: {exc}{Style.RESET_ALL}")
            return

    if proxy_manager:
        initial_proxy_entry = proxy_manager.get_next()
        if initial_proxy_entry:
            initial_proxy_dict = initial_proxy_entry.to_patchright()

    # ── Proxy health-check / benchmark ────────────────────────────────────────
    if proxy_manager and not getattr(args, "no_health_check", False):
        health_url = getattr(args, "health_check_url", DEFAULT_CONFIG["health_check_url"])
        await proxy_manager.benchmark_all(health_check_url=health_url)
        # Re-pick initial proxy after benchmark (dead ones are now retired)
        initial_proxy_entry = proxy_manager.get_next()
        initial_proxy_dict  = initial_proxy_entry.to_patchright() if initial_proxy_entry else None


    # ── Origin resolution (before browser — uses aiohttp / cf-hero CLI) ───────
    proxy_url = initial_proxy_entry.server if initial_proxy_entry else None
    origin_target = None
    if args.origin_ip or args.cf_hero:
        try:
            origin_target = await _resolve_origin_access(args, args.url, proxy_url)
        except Exception as exc:
            print(f"{Fore.RED}[Origin] Setup failed: {exc}{Style.RESET_ALL}")
            return
        if not origin_target:
            print(f"{Fore.RED}[Origin] No validated origin — aborting.{Style.RESET_ALL}")
            return
        print(
            f"{Fore.CYAN}[Origin] Scraping {origin_target.hostname} via "
            f"{origin_target.origin_ip} ({origin_target.source}){Style.RESET_ALL}"
        )

    # ── Browser ───────────────────────────────────────────────────────────────
    browser = BrowserManager(
        headless=not args.no_headless,
        rotate_user_agent=DEFAULT_CONFIG["rotate_user_agent"],
        rotate_geolocation=DEFAULT_CONFIG["rotate_geolocation"],
        rotate_viewport=DEFAULT_CONFIG["rotate_viewport"],
    )
    resolver = origin_target.host_resolver_rule() if origin_target else None
    slot_entries = _assign_slot_proxies(
        proxy_manager, args.concurrency, initial_proxy_entry,
    )
    slot_identities = [
        _proxy_to_identity(e) if e else SlotIdentity()
        for e in slot_entries
    ]
    await browser.start(
        host_resolver_rules=resolver,
        pool_size=args.concurrency,
        slot_identities=slot_identities,
    )

    try:
        # ── Auth (restore / login / bootstrap) via AuthManager ───────────────
        needs_auth = bool(
            args.login
            or args.auth_bootstrap
            or (args.session_file and os.path.isfile(args.session_file))
            or args.auth_profile
        )
        auth_manager = None
        authenticated = False

        if needs_auth or args.login or args.auth_bootstrap:
            # Force dynamic engine when authenticating
            if args.login or args.auth_bootstrap:
                if args.engine == "lightweight":
                    print(
                        f"{Fore.YELLOW}[Auth] Forcing engine=dynamic because login/bootstrap "
                        f"requires a browser session.{Style.RESET_ALL}"
                    )
                    args.engine = "dynamic"

            profile = build_profile_from_args(args, profile_path=args.auth_profile)
            # Env credential fallback already applied in build_profile_from_args
            if args.otp_prompt:
                profile.otp_prompt = True
            if args.on_auth_wall:
                profile.on_auth_wall = args.on_auth_wall
            if args.session_ttl:
                profile.session_ttl = args.session_ttl
            if args.auth_check_url:
                profile.auth_check_url = args.auth_check_url

            auth_manager = AuthManager(
                browser,
                profile=profile,
                concurrency=args.concurrency,
                headless=not args.no_headless,
                timeout=args.timeout,
                wait_until=args.wait_until,
            )

            if args.auth_bootstrap:
                if not args.session_file:
                    print(f"{Fore.RED}[Auth] --auth-bootstrap requires --session-file{Style.RESET_ALL}")
                    return
                if not args.no_headless:
                    print(
                        f"{Fore.YELLOW}[Auth] Tip: use --no-headless with --auth-bootstrap "
                        f"so you can complete OAuth visually.{Style.RESET_ALL}"
                    )
                bootstrap_url = args.login_url or args.url
                ok = await auth_manager.bootstrap_manual(
                    url=bootstrap_url, session_file=args.session_file,
                )
                if not ok:
                    print(f"{Fore.RED}[Auth] Bootstrap failed.{Style.RESET_ALL}")
                    return
                authenticated = True
            else:
                restored = False
                if profile.session_file and os.path.isfile(profile.session_file):
                    restored = await auth_manager.restore(profile.session_file)
                    if restored:
                        print(
                            f"{Fore.GREEN}[Auth] Session restored — skipping login."
                            f"{Style.RESET_ALL}"
                        )
                        authenticated = True

                if args.login and not restored:
                    user, pw = resolve_credentials(profile.username, profile.password)
                    if not user or not pw:
                        print(
                            f"{Fore.RED}[Error] Username/password required "
                            f"(--username/--password, auth profile, or WEBVAC_USER/WEBVAC_PASS)"
                            f"{Style.RESET_ALL}"
                        )
                        return
                    profile.username = user
                    profile.password = pw
                    ok = await auth_manager.login(seed_url=args.url)
                    if not ok:
                        print(
                            f"{Fore.YELLOW}[Warning] Login may have failed — continuing anyway."
                            f"{Style.RESET_ALL}"
                        )
                    else:
                        authenticated = True
                        print(f"{Fore.GREEN}[Auth] Login successful.{Style.RESET_ALL}")

        # ── Crawl / Scrape ────────────────────────────────────────────────────
        # ScreenshotModule (CAPTCHA pages only)
        screenshot_module = None
        if screenshots_enabled:
            screenshot_module = ScreenshotModule(
                output_dir=args.output,
                screenshots_subdir=DEFAULT_CONFIG["screenshots_subdir"],
            )

        pipeline_manager = PipelineManager(args.pipeline_file) if args.pipeline_file else None

        session_config = dict(DEFAULT_CONFIG)
        session_config["max_depth"] = args.depth
        session_config["max_pages"] = args.max_pages
        session_config["cf_hero_auto_fallback"] = not args.no_cf_hero_auto
        session_config["cf_hero_bin"] = args.cf_hero_bin
        session_config["cf_hero_args"] = args.cf_hero_args
        session_config["cf_hero_timeout"] = int(getattr(args, "cf_hero_timeout", 300) or 300)
        session_config["cf_hero_workers"] = int(getattr(args, "cf_hero_workers", 0) or 0)
        session_config["cf_hero_quiet"] = bool(getattr(args, "cf_hero_quiet", False))
        session_config["cf_hero_log"] = getattr(args, "cf_hero_log", None)
        session_config["skip_origin_validate"] = bool(getattr(args, "skip_origin_validate", False))
        if args.origin_title:
            session_config["origin_title"] = args.origin_title
        session_config["consent_dismiss"] = not bool(getattr(args, "no_consent_dismiss", False))
        session_config["pause_for_consent"] = bool(getattr(args, "pause_for_consent", False))
        if getattr(args, "dismiss_selector", None):
            session_config["dismiss_selectors"] = list(args.dismiss_selector)
        if session_config["pause_for_consent"] and not getattr(args, "no_headless", False):
            print(
                f"{Fore.YELLOW}[Consent] --pause-for-consent needs a visible browser; "
                f"add --no-headless or the pause will be skipped.{Style.RESET_ALL}"
            )
        if initial_proxy_entry:
            session_config["_proxy_url"] = initial_proxy_entry.server
        if args.allow_subdomains:
            session_config["allow_subdomains"] = True
        if origin_target:
            session_config["origin_access"] = origin_target.to_dict()

        # Auth crawl policies
        pin_proxy = bool(args.login or args.auth_bootstrap or authenticated)
        if args.no_auth_proxy_rotate or pin_proxy:
            # Default: pin proxy when authenticated unless user overrides later
            session_config["auth_pin_proxy"] = True
        if authenticated or args.login:
            session_config["authenticated"] = True
            session_config["on_auth_wall"] = args.on_auth_wall
            session_config["auth_check_url"] = args.auth_check_url
            session_config["deny_logout_urls"] = True
            # Avoid voluntary sticky rotate killing the session IP
            if session_config.get("auth_pin_proxy"):
                sticky_requests = 0
            else:
                sticky_requests = args.sticky_requests
        else:
            sticky_requests = args.sticky_requests

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
            captcha_prompt_enabled=not args.no_captcha_prompt,
            sticky_requests=sticky_requests,
            recon_config=session_config,
            auth_manager=auth_manager,
        )

        crawler.init_slot_proxies(slot_entries)

        interrupted = False
        results: list = []
        try:
            if args.mode == "single":
                results = await crawler.scrape_single(args.url)
            else:
                results = await crawler.scrape_site(args.url)
        except KeyboardInterrupt:
            interrupted = True
            results = crawler.partial_results
            print(
                f"\n{Fore.YELLOW}[Scraper] Interrupted — saving "
                f"{len(results)} partial result(s)...{Style.RESET_ALL}"
            )

        await _persist_run(
            args,
            crawler,
            results,
            session_config,
            output_formats,
            interrupted=interrupted,
        )

    finally:
        await browser.stop()

def main():
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
