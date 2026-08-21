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

  # Proxies: omit --proxy-file to auto-use ./proxies.txt when present
  python -m webvac --url https://example.com --mode crawl

  # robots.txt is bypassed by default; opt in with --respect-robots
  python -m webvac --url https://example.com --respect-robots
"""

import asyncio
import argparse
import os
import shutil
import sys

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
from webvac.utils.browser_pool import SlotIdentity
from webvac.vapt.decaffeinator import (
    resolve_decaffeinator_root,
    run_decaffeinator_task,
)
from urllib.parse import urlparse

init(autoreset=True)  # colorama


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webvac",
        description="Dynamic web scraper — handles JS, auth, crawling, proxies, robots.txt. Outputs JSON + CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Target
    p.add_argument(
        "--url",
        required=False,
        help="Target URL to scrape or crawl from. Optional when using --doctor.",
    )
    p.add_argument(
        "--doctor",
        action="store_true",
        help="Run environment and config checks, then exit without scraping.",
    )
    p.add_argument(
        "--task",
        choices=["scrape", "vapt"],
        default="scrape",
        help="Run the normal scraper or the opt-in De-Caffeinator VAPT task.",
    )

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
        help="Patchright lifecycle event to wait for on page load. (default: load)",
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
        "--otp-prompt",
        action="store_true",
        default=False,
        help="Prompt for OTP/MFA when an OTP field appears during login.",
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
    p.add_argument(
        "--decaffeinator-root",
        default=None,
        metavar="DIR",
        help="Path to the De-Caffeinator root directory (defaults to ./decaffeinator/blob-unpacker).",
    )
    p.add_argument(
        "--vapt-profile",
        choices=["standard", "quick", "stealth", "deep"],
        default="standard",
        help="Preset profile for the De-Caffeinator VAPT task.",
    )
    p.add_argument(
        "--vapt-format",
        choices=["json", "jsonl"],
        default="json",
        help="Output format for De-Caffeinator artifacts.",
    )
    p.add_argument(
        "--vapt-playwright",
        action="store_true",
        help="Enable De-Caffeinator's Playwright-based SPA asset discovery.",
    )
    p.add_argument(
        "--vapt-wayback",
        action="store_true",
        help="Enable De-Caffeinator's Wayback-based historical asset discovery.",
    )
    p.add_argument(
        "--vapt-no-files",
        action="store_true",
        help="Do not write De-Caffeinator source/deobfuscated files to disk.",
    )

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
            "server  OR  server|username|password. Lines starting with # are ignored. "
            "If omitted, uses ./proxies.txt when that file exists."
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
    p.add_argument(
        "--proxy-playbook",
        choices=["none", "residential", "datacenter"],
        default="none",
        help=(
            "Apply named proxy defaults: residential (sticky=25, long cooldown, "
            "UA+geo+tz pinned per IP) or datacenter (sticky=5, round-robin). "
            "Explicit --sticky-requests / --proxy-strategy / --cooldown-seconds win."
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
        help=(
            "Path to a Python file containing data cleaning pipelines. "
            "If omitted, uses ./pipeline.py or examples/pipeline.example.py when present."
        ),
    )


    # robots.txt (default: bypass)
    p.add_argument(
        "--no-robots",
        action="store_true",
        default=True,
        help="Ignore robots.txt entirely (default: on).",
    )
    p.add_argument(
        "--respect-robots",
        action="store_false",
        dest="no_robots",
        help="Obey robots.txt allow/deny and Crawl-delay.",
    )
    p.add_argument(
        "--ignore-crawl-delay",
        action="store_true",
        help="When respecting robots.txt, ignore its Crawl-delay directive.",
    )

    # Output formats
    p.add_argument(
        "--format",
        default=DEFAULT_CONFIG["output_formats"],
        metavar="FMT[,FMT…]",
        help=(
            "Comma-separated output formats: json, csv, markdown, sqlite, html, all. "
            "(default: json,html)"
        ),
    )

    # Screenshots
    p.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Disable automatic screenshots of CAPTCHA / bot-block pages.",
    )

    p.add_argument(
        "--captcha-solver",
        choices=["none", "capsolver"],
        default=None,
        help=(
            "Auto CAPTCHA provider (default: none). "
            "Requires --captcha-api-key or CAPSOLVER_API_KEY / WEBVAC_CAPSOLVER_KEY."
        ),
    )
    p.add_argument(
        "--captcha-api-key",
        default=None,
        metavar="KEY",
        help="CapSolver (or provider) API key.",
    )
    p.add_argument(
        "--captcha-timeout",
        type=float,
        default=None,
        metavar="SECS",
        help="Max seconds to wait for CapSolver result (default: 120).",
    )

    p.add_argument(
        "--no-humanize",
        action="store_true",
        help=(
            "Disable human-like mouse paths, wheel scroll, per-host warmup, "
            "and post-load settle behaviour (faster, more bot-like)."
        ),
    )

    p.add_argument(
        "--no-humanize-warmup",
        action="store_true",
        help="Skip the once-per-host root-domain warmup visit (keep other humanize).",
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

    p.add_argument(
        "--no-network-debug",
        action="store_true",
        help="Disable per-page network listeners and failure dumps under each scan's network/ folder.",
    )
    p.add_argument(
        "--network-debug-always",
        action="store_true",
        help="Also dump network debug JSON on successful page scrapes (noisy).",
    )

    return p


_DEFAULT_SEC_CH_UA = '"Chromium";v="133", "Google Chrome";v="133", "Not-A.Brand";v="99"'


def _proxy_to_identity(entry) -> SlotIdentity:
    return SlotIdentity(
        proxy=entry.to_patchright(),
        ua=entry.pinned_ua or "",
        platform=entry.pinned_platform or "Windows",
        sec_ch_ua=entry.pinned_sec_ch_ua or _DEFAULT_SEC_CH_UA,
        city=getattr(entry, "pinned_city", "") or "",
        lat=float(getattr(entry, "pinned_lat", 0.0) or 0.0),
        lon=float(getattr(entry, "pinned_lon", 0.0) or 0.0),
        timezone=getattr(entry, "pinned_timezone", "") or "",
    )


def _assign_slot_proxies(proxy_manager, concurrency: int, first_entry=None) -> list:
    """Pick one proxy per concurrent worker slot (unique while the pool lasts)."""
    entries = []
    assigned: list = []
    for i in range(concurrency):
        if i == 0 and first_entry:
            nxt = first_entry
        elif proxy_manager:
            nxt = proxy_manager.get_next(exclude=assigned, quiet=True)
            if nxt is None and assigned:
                nxt = assigned[i % len(assigned)]
        else:
            nxt = None
        entries.append(nxt)
        if nxt is not None and nxt not in assigned:
            assigned.append(nxt)
    return entries


def _apply_default_proxy_file(args) -> None:
    """Auto-use ``./proxies.txt`` when no explicit proxy source was passed."""
    if args.proxy_file or args.proxies:
        return
    default_proxy = os.path.join(os.getcwd(), "proxies.txt")
    if os.path.isfile(default_proxy):
        args.proxy_file = default_proxy
        print(f"{Fore.CYAN}[Proxy] Using default pool: {default_proxy}{Style.RESET_ALL}")


def _apply_default_pipeline_file(args) -> None:
    """Auto-use a nearby pipeline file when none was explicitly passed."""
    if args.pipeline_file:
        return
    for candidate in (
        os.path.join(os.getcwd(), "pipeline.py"),
        os.path.join(os.getcwd(), "examples", "pipeline.example.py"),
    ):
        if os.path.isfile(candidate):
            args.pipeline_file = candidate
            print(f"{Fore.CYAN}[Pipeline] Using {candidate}{Style.RESET_ALL}")
            break


async def _run_doctor(args) -> int:
    """Run environment/config checks without performing a scrape."""
    print(f"\n{Fore.CYAN}{'='*60}")
    print("  WebVac Doctor")
    print(f"{'='*60}{Style.RESET_ALL}\n")

    ok = 0
    warn = 0
    fail = 0

    def _emit(text: str) -> None:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"))

    def _pass(msg: str) -> None:
        nonlocal ok
        ok += 1
        _emit(f"{Fore.GREEN}[OK] {msg}{Style.RESET_ALL}")

    def _warn(msg: str) -> None:
        nonlocal warn
        warn += 1
        _emit(f"{Fore.YELLOW}[WARN] {msg}{Style.RESET_ALL}")

    def _fail(msg: str) -> None:
        nonlocal fail
        fail += 1
        _emit(f"{Fore.RED}[FAIL] {msg}{Style.RESET_ALL}")

    _pass(f"Python {sys.version.split()[0]}")

    _apply_default_proxy_file(args)
    _apply_default_pipeline_file(args)

    try:
        os.makedirs(args.output, exist_ok=True)
        probe = os.path.join(args.output, ".webvac_doctor_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        _pass(f"Output directory writable: {args.output}")
    except Exception as exc:
        _fail(f"Output directory is not writable: {args.output} ({exc})")

    if args.url:
        parsed = urlparse(args.url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            _pass(f"Target URL looks valid: {args.url}")
        else:
            _fail(f"Target URL is invalid: {args.url}")
    else:
        _warn("No --url provided; skipping target-specific checks.")

    if getattr(args, "task", "scrape") == "vapt":
        try:
            root = resolve_decaffeinator_root(getattr(args, "decaffeinator_root", None))
            _pass(f"De-Caffeinator root found: {root}")
        except Exception as exc:
            _fail(str(exc))
        if shutil.which("npx") or shutil.which("npx.cmd"):
            _pass("Node/npx detected for De-Caffeinator.")
        else:
            _fail("Node/npx not found in PATH; De-Caffeinator cannot run.")

    if args.pipeline_file:
        if os.path.isfile(args.pipeline_file):
            _pass(f"Pipeline file found: {args.pipeline_file}")
        else:
            _fail(f"Pipeline file not found: {args.pipeline_file}")
    else:
        _warn("No pipeline file configured.")

    from webvac.captcha.config import CaptchaSolverConfig

    cap = CaptchaSolverConfig.from_mapping(
        {
            "captcha_solver": getattr(args, "captcha_solver", None),
            "captcha_api_key": getattr(args, "captcha_api_key", None),
            "captcha_timeout": getattr(args, "captcha_timeout", None),
        }
    )
    if getattr(args, "captcha_solver", None) == "capsolver":
        if cap.api_key:
            _pass("CapSolver key detected.")
        else:
            _fail("CapSolver requested but no API key found.")
    elif cap.api_key:
        _warn("CapSolver key detected but solver is not enabled.")
    else:
        _warn("No CapSolver key configured.")

    proxy_manager = None
    if args.proxy_file:
        if not os.path.isfile(args.proxy_file):
            _fail(f"Proxy file not found: {args.proxy_file}")
        else:
            try:
                proxy_manager = ProxyManager.from_file(
                    args.proxy_file,
                    strategy=args.proxy_strategy,
                    max_failures=args.max_retries,
                    cooldown_seconds=args.cooldown_seconds,
                    max_cooldown_failures=DEFAULT_CONFIG["max_cooldown_failures"],
                    pin_geo=True,
                )
                _pass(f"Loaded {len(proxy_manager.proxies)} proxies from {args.proxy_file}")
            except Exception as exc:
                _fail(f"Could not load proxy file: {exc}")
    elif args.proxies:
        proxy_list = [p.strip() for p in args.proxies.split(",") if p.strip()]
        try:
            proxy_manager = ProxyManager.from_strings(
                proxy_list,
                strategy=args.proxy_strategy,
                max_failures=args.max_retries,
                cooldown_seconds=args.cooldown_seconds,
                max_cooldown_failures=DEFAULT_CONFIG["max_cooldown_failures"],
                pin_geo=True,
            )
            _pass(f"Loaded {len(proxy_manager.proxies)} inline proxies.")
        except Exception as exc:
            _fail(f"Could not parse inline proxies: {exc}")
    else:
        _warn("No proxies configured; scrapes will use your real IP.")

    if proxy_manager:
        if getattr(args, "no_health_check", False):
            _warn("Proxy health-check disabled; skipping live proxy validation.")
        else:
            try:
                await proxy_manager.benchmark_all(
                    health_check_url=getattr(args, "health_check_url", DEFAULT_CONFIG["health_check_url"])
                )
                healthy = [p for p in proxy_manager.proxies if p.is_active()]
                if healthy:
                    _pass(f"{len(healthy)}/{len(proxy_manager.proxies)} proxies healthy.")
                else:
                    _warn(
                        "All configured proxies failed health-check; runtime will continue direct if needed."
                    )
            except Exception as exc:
                _warn(f"Proxy health-check failed: {exc}")

    needs_patchright = (
        getattr(args, "task", "scrape") == "scrape"
        or getattr(args, "vapt_playwright", False)
    )
    if needs_patchright:
        browser = BrowserManager(
            headless=True,
            locale=DEFAULT_CONFIG.get("locale"),
            timezone_id=DEFAULT_CONFIG.get("timezone_id"),
            accept_language=DEFAULT_CONFIG.get("accept_language"),
            rotate_user_agent=DEFAULT_CONFIG["rotate_user_agent"],
            rotate_geolocation=DEFAULT_CONFIG["rotate_geolocation"],
            rotate_viewport=DEFAULT_CONFIG["rotate_viewport"],
            humanize=False,
        )
        try:
            await browser.start(pool_size=1, slot_identities=[SlotIdentity()])
            _pass("Patchright browser launched successfully.")
        except Exception as exc:
            _fail(f"Patchright browser launch failed: {exc}")
        finally:
            try:
                await browser.stop()
            except Exception:
                pass
    else:
        _warn("Skipping Patchright browser launch check for non-browser VAPT task.")

    _emit(f"\n{Fore.CYAN}Doctor summary: {ok} ok, {warn} warnings, {fail} failures{Style.RESET_ALL}")
    return 1 if fail else 0


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
        if session_config.get("download_pdfs", True) and results:
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
        results or [],
        label=args.label,
        formats=output_formats,
        scan=scan,
        interrupted=interrupted,
        assets_meta=assets_meta,
    )

    label = "Partial save" if interrupted else "Success"
    n = len(results or [])
    print(f"\n{Fore.GREEN}{label}: {n} page(s) saved.{Style.RESET_ALL}")
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
    if getattr(args, "task", "scrape") == "vapt":
        result = run_decaffeinator_task(args)
        if result.return_code != 0:
            raise SystemExit(result.return_code)
        print(f"\n{Fore.GREEN}VAPT task complete.{Style.RESET_ALL}")
        print(f"  Session    -> {result.session_dir}")
        print(f"  Artifacts  -> {result.output_dir}")
        print(f"  Meta       -> {result.meta_path}")
        if result.run_report_path:
            print(f"  Report     -> {result.run_report_path}")
        if result.summary_path:
            print(f"  Summary    -> {result.summary_path}")
        return

    # ── Banner ───────────────────────────────────────────────────────────────
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  Dynamic Web Scraper")
    print(f"  URL         : {args.url}")
    print(f"  Mode        : {args.mode}")
    print(f"  Login       : {'yes' if args.login else 'no'}")
    print(f"  Robots      : {'disabled (bypass)' if args.no_robots else 'enabled'}")
    proxy_label = (
        args.proxy_file or
        (f"{len(args.proxies.split(','))} inline" if args.proxies else "none")
    )
    print(f"  Proxies     : {proxy_label}")
    print(f"  Concurrency : {args.concurrency}")
    print(f"  Wait        : {args.wait_until}")
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
            print(f"{Fore.YELLOW}[Warning] No valid --format values; defaulting to json,html{Style.RESET_ALL}")
            output_formats = ["json", "html"]
    print(f"  Formats     : {', '.join(output_formats)}")
    print(f"{'='*60}{Style.RESET_ALL}\n")

    _apply_default_proxy_file(args)
    _apply_default_pipeline_file(args)

    # Login requires a real browser engine (not lightweight HTTP).
    if args.login:
        if args.engine == "lightweight":
            print(
                f"{Fore.YELLOW}[Auth] Forcing engine=dynamic because login "
                f"requires a browser session.{Style.RESET_ALL}"
            )
            args.engine = "dynamic"

    # ── Proxy playbook (sticky / cooldown / geo pin defaults) ─────────────────
    from webvac.utils.proxy_playbook import apply_proxy_playbook

    playbook = apply_proxy_playbook(
        getattr(args, "proxy_playbook", "none") or "none",
        sticky_requests=args.sticky_requests,
        proxy_strategy=args.proxy_strategy,
        proxy_cooldown_seconds=args.cooldown_seconds,
        sticky_default=DEFAULT_CONFIG["sticky_requests"],
        strategy_default=DEFAULT_CONFIG["proxy_strategy"],
        cooldown_default=DEFAULT_CONFIG["proxy_cooldown_seconds"],
    )
    args.sticky_requests = playbook["sticky_requests"]
    args.proxy_strategy = playbook["proxy_strategy"]
    args.cooldown_seconds = playbook["proxy_cooldown_seconds"]
    rotate_geolocation = bool(playbook.get("rotate_geolocation", True))
    if playbook.get("playbook") and playbook["playbook"] != "none":
        print(
            f"{Fore.CYAN}[Proxy] Playbook={playbook['playbook']}  "
            f"sticky={args.sticky_requests}  strategy={args.proxy_strategy}  "
            f"cooldown={args.cooldown_seconds:.0f}s  "
            f"geo_pin={'on' if playbook.get('pin_proxy_geo') else 'off'}"
            f"{Style.RESET_ALL}"
        )

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
                pin_geo=bool(playbook.get("pin_proxy_geo", True)),
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
                pin_geo=bool(playbook.get("pin_proxy_geo", True)),
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
        if initial_proxy_entry is None:
            print(
                f"{Fore.YELLOW}[Proxy] All configured proxies are currently unavailable. "
                f"Continuing with direct connection (real IP).{Style.RESET_ALL}"
            )


    # ── Browser ───────────────────────────────────────────────────────────────
    browser = BrowserManager(
        headless=not args.no_headless,
        locale=DEFAULT_CONFIG.get("locale"),
        timezone_id=DEFAULT_CONFIG.get("timezone_id"),
        accept_language=DEFAULT_CONFIG.get("accept_language"),
        rotate_user_agent=DEFAULT_CONFIG["rotate_user_agent"],
        rotate_geolocation=rotate_geolocation if proxy_manager else DEFAULT_CONFIG["rotate_geolocation"],
        rotate_viewport=DEFAULT_CONFIG["rotate_viewport"],
        humanize=not bool(getattr(args, "no_humanize", False)),
    )
    slot_entries = _assign_slot_proxies(
        proxy_manager, args.concurrency, initial_proxy_entry,
    )
    slot_identities = [
        _proxy_to_identity(e) if e else SlotIdentity()
        for e in slot_entries
    ]
    await browser.start(
        pool_size=args.concurrency,
        slot_identities=slot_identities,
    )

    try:
        # ── Auth (restore / login) via AuthManager ─────────────────────────────
        needs_auth = bool(
            args.login
            or (args.session_file and os.path.isfile(args.session_file))
            or args.auth_profile
        )
        auth_manager = None
        authenticated = False

        if needs_auth or args.login:
            # --auth-profile with creds implies login
            if args.auth_profile and not args.login:
                profile_peek = build_profile_from_args(args, profile_path=args.auth_profile)
                if profile_peek.has_credentials() or resolve_credentials(
                    profile_peek.username, profile_peek.password
                )[0]:
                    args.login = True

            profile = build_profile_from_args(args, profile_path=args.auth_profile)
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

            restored = False
            # Explicit --login means a fresh login; do not short-circuit on stale session.
            if not args.login and profile.session_file and os.path.isfile(profile.session_file):
                restored = await auth_manager.restore(profile.session_file)
                if restored:
                    print(
                        f"{Fore.GREEN}[Auth] Session restored — skipping login."
                        f"{Style.RESET_ALL}"
                    )
                    authenticated = True
            elif args.login and profile.session_file and os.path.isfile(profile.session_file):
                print(
                    f"{Fore.CYAN}[Auth] --login: ignoring existing session file "
                    f"({profile.session_file}); performing fresh login.{Style.RESET_ALL}"
                )

            if (args.login or (not restored and profile.has_credentials())) and not restored:
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
                            f"{Fore.RED}[Auth] Login failed — aborting. "
                            f"Check --login-url, credentials, and selectors.{Style.RESET_ALL}"
                        )
                        return
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
        session_config["network_debug"] = not bool(getattr(args, "no_network_debug", False))
        session_config["network_debug_always"] = bool(getattr(args, "network_debug_always", False))
        session_config["consent_dismiss"] = not bool(getattr(args, "no_consent_dismiss", False))
        session_config["pause_for_consent"] = bool(getattr(args, "pause_for_consent", False))
        session_config["humanize"] = not bool(getattr(args, "no_humanize", False))
        session_config["humanize_warmup"] = (
            session_config["humanize"]
            and not bool(getattr(args, "no_humanize_warmup", False))
        )
        session_config["humanize_after_goto"] = session_config["humanize"]
        browser.configure_humanize(session_config)
        if getattr(args, "captcha_solver", None):
            session_config["captcha_solver"] = args.captcha_solver
            if args.captcha_solver == "none":
                session_config["captcha_solver_disabled"] = True
        if getattr(args, "captcha_api_key", None):
            session_config["captcha_api_key"] = args.captcha_api_key
        if getattr(args, "captcha_timeout", None) is not None:
            session_config["captcha_solver_timeout_sec"] = float(args.captcha_timeout)
        # Enable solver when provider + key are present (CLI / env / capsolver.key)
        from webvac.captcha.config import CaptchaSolverConfig
        _cap = CaptchaSolverConfig.from_mapping(session_config)
        if _cap.api_key and _cap.enabled:
            session_config["captcha_solver"] = "capsolver"
            session_config["captcha_api_key"] = _cap.api_key
            session_config["captcha_solver_enabled"] = True
            mode = "headed" if getattr(args, "no_headless", False) else "headless"
            print(
                f"{Fore.CYAN}[Captcha] CapSolver enabled "
                f"(browser={mode}, key …{_cap.api_key[-4:]}){Style.RESET_ALL}"
            )
        elif getattr(args, "captcha_solver", None) == "capsolver" and not _cap.api_key:
            print(
                f"{Fore.YELLOW}[Captcha] --captcha-solver capsolver but no API key. "
                f"Put it in capsolver.key, CAPSOLVER_API_KEY, or --captcha-api-key."
                f"{Style.RESET_ALL}"
            )
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

        # Auth crawl policies — only when login actually succeeded
        pin_proxy = bool(authenticated)
        if args.no_auth_proxy_rotate or pin_proxy:
            session_config["auth_pin_proxy"] = True
        if authenticated:
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
            captcha_prompt_enabled=False,
            sticky_requests=sticky_requests,
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
    if not args.doctor and not args.url:
        parser.error("--url is required unless --doctor is used.")
    if args.doctor:
        raise SystemExit(asyncio.run(_run_doctor(args)))
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
