"""
run.py — Interactive launcher and command wrapper for WebVac.
Provides a premium menu-driven CLI interface to construct and execute scraping jobs.
"""

import os
import sys
import subprocess
import shutil
import json
import getpass
from dataclasses import dataclass
from typing import Optional
from colorama import init, Fore, Style

init(autoreset=True)


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    width = 65
    print(Fore.CYAN + "=" * width)
    print(Fore.CYAN + "   _      __     __    _   __            ")
    print(Fore.CYAN + "  | | /| / /__  / /_  | | / /__ _  _____ ")
    print(Fore.CYAN + "  | |/ |/ / -_)/ __/  | |/ / _ `/|/ ___/ ")
    print(Fore.CYAN + "  |__/|__/\\__/ \\__/   |___/\\_,_/ |/      ")
    print(Fore.CYAN + "                                         ")
    print(Fore.CYAN + "     INTERACTIVE WEB SCRAPER MENU   ")
    print(Fore.CYAN + "=" * width)


def prompt_password(prompt_text: str, default: Optional[str] = None) -> Optional[str]:
    """Read a password without echoing characters to the terminal."""
    suffix = f" [{default}]" if default else ""
    try:
        val = getpass.getpass(
            Fore.YELLOW + f"{prompt_text}{suffix}: " + Style.RESET_ALL,
        )
        val = val.strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\n[Launcher] Cancelled.")
        sys.exit(0)


@dataclass
class AuthConfig:
    username: str = ""
    password: str = ""
    login_url: Optional[str] = None
    auth_engine: Optional[str] = None  # patchright | nodriver
    session_file: Optional[str] = None
    username_selector: Optional[str] = None
    password_selector: Optional[str] = None
    submit_selector: Optional[str] = None
    dismiss_selectors: Optional[list[str]] = None
    auth_check_url: Optional[str] = None
    on_auth_wall: Optional[str] = None  # abort | skip | relogin
    session_ttl: Optional[int] = None
    otp_prompt: bool = False
    auth_profile_path: Optional[str] = None


def _load_auth_from_json(path: str) -> AuthConfig:
    """
    Load auth settings from JSON.

    Supported shape (flat or nested under "creds") — see auth_creds.example.json.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and isinstance(data.get("creds"), dict):
        data = data["creds"]

    if not isinstance(data, dict):
        raise ValueError("Credentials JSON must be an object.")

    username = data.get("username") or data.get("user") or ""
    password = data.get("password") or data.get("pass") or ""
    if not username or not password:
        raise ValueError("Credentials JSON must include username and password.")

    engine = data.get("auth_engine") or data.get("engine")
    if engine:
        engine = str(engine).lower()
        if engine not in ("patchright", "nodriver"):
            raise ValueError("auth_engine must be 'patchright' or 'nodriver'.")

    dismiss = data.get("dismiss_selectors") or data.get("dismiss_selector")
    if isinstance(dismiss, str):
        dismiss = [dismiss]
    elif dismiss is not None and not isinstance(dismiss, list):
        raise ValueError("dismiss_selectors must be a string or list of CSS selectors.")

    wall = data.get("on_auth_wall")
    if wall is not None:
        wall = str(wall).lower()
        if wall not in ("abort", "skip", "relogin"):
            raise ValueError("on_auth_wall must be abort, skip, or relogin.")

    ttl_raw = data.get("session_ttl") or data.get("ttl_sec")
    ttl = int(ttl_raw) if ttl_raw not in (None, "") else None

    return AuthConfig(
        username=str(username),
        password=str(password),
        login_url=data.get("login_url") or data.get("login"),
        auth_engine=engine,
        session_file=data.get("session_file") or data.get("session"),
        username_selector=data.get("username_selector"),
        password_selector=data.get("password_selector"),
        submit_selector=data.get("submit_selector"),
        dismiss_selectors=[str(s) for s in dismiss] if dismiss else None,
        auth_check_url=data.get("auth_check_url") or data.get("check_url"),
        on_auth_wall=wall,
        session_ttl=ttl,
        otp_prompt=bool(data.get("otp_prompt", False)),
        auth_profile_path=path,
    )


def _apply_auth_config(cmd_args: list[str], auth: AuthConfig) -> None:
    """Append scraper CLI flags from an AuthConfig."""
    cmd_args.append("--login")
    if auth.auth_profile_path:
        cmd_args += ["--auth-profile", auth.auth_profile_path]
    if auth.login_url:
        cmd_args += ["--login-url", auth.login_url]
    if auth.auth_engine == "nodriver":
        cmd_args += ["--auth-engine", "nodriver"]
    cmd_args += ["--username", auth.username, "--password", auth.password]
    if auth.username_selector and auth.password_selector:
        cmd_args += ["--username-selector", auth.username_selector]
        cmd_args += ["--password-selector", auth.password_selector]
        if auth.submit_selector:
            cmd_args += ["--submit-selector", auth.submit_selector]
    if auth.session_file:
        cmd_args += ["--session-file", auth.session_file]
    if auth.dismiss_selectors:
        for sel in auth.dismiss_selectors:
            cmd_args += ["--dismiss-selector", sel]
    if auth.auth_check_url:
        cmd_args += ["--auth-check-url", auth.auth_check_url]
    if auth.on_auth_wall:
        cmd_args += ["--on-auth-wall", auth.on_auth_wall]
    if auth.session_ttl is not None and auth.session_ttl > 0:
        cmd_args += ["--session-ttl", str(auth.session_ttl)]
    if auth.otp_prompt:
        cmd_args.append("--otp-prompt")


def _redact_cmd_args(cmd_args: list[str]) -> list[str]:
    """Mask secrets before printing the constructed command."""
    from auth.credentials import redact_cmd_args
    return redact_cmd_args(cmd_args)


def prompt_string(prompt_text, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(Fore.YELLOW + f"{prompt_text}{suffix}: " + Style.RESET_ALL).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\n[Launcher] Cancelled.")
        sys.exit(0)


def prompt_choice(prompt_text, choices, default_idx=0):
    print(Fore.YELLOW + f"\n{prompt_text}:" + Style.RESET_ALL)
    for idx, choice in enumerate(choices, 1):
        mark = "->" if idx - 1 == default_idx else "  "
        print(f"  {mark} {idx}. {choice}")

    default_val = str(default_idx + 1)
    while True:
        try:
            choice = input(Fore.GREEN + f"Select option (1-{len(choices)}) [{default_val}]: " + Style.RESET_ALL).strip()
            if not choice:
                return choices[default_idx]
            val = int(choice)
            if 1 <= val <= len(choices):
                return choices[val - 1]
            print(Fore.RED + f"Invalid choice. Please select 1 to {len(choices)}.")
        except ValueError:
            print(Fore.RED + "Please enter a valid number.")
        except (KeyboardInterrupt, EOFError):
            print("\n[Launcher] Cancelled.")
            sys.exit(0)


def select_proxy_file():
    txt_files = [f for f in os.listdir(".") if f.endswith(".txt") and f != "requirements.txt"]
    if not txt_files:
        return None

    print(Fore.YELLOW + "\nFound the following text files in the project folder:" + Style.RESET_ALL)
    choices = ["Enter custom file path", "No proxy (direct connection)"] + txt_files
    choice = prompt_choice("Select a proxy file or enter path", choices, default_idx=1)

    if choice == "No proxy (direct connection)":
        return None
    if choice == "Enter custom file path":
        return prompt_string("Enter path to your proxy file", "proxies.txt")
    return choice


def run_command(cmd_args):
    command = [sys.executable, "-m", "core.scraper"] + cmd_args
    display_args = _redact_cmd_args(cmd_args)
    command_str = " ".join([sys.executable, "-m", "core.scraper"] + display_args)

    print(Fore.CYAN + "\n" + "=" * 65)
    print(Fore.GREEN + "Constructed Command:")
    print(Fore.WHITE + f"  {command_str}")
    print(Fore.CYAN + "=" * 65 + "\n")

    print(Fore.MAGENTA + "[Launcher] Starting scraper subprocess..." + Style.RESET_ALL)
    try:
        # Run with live output streaming to terminal
        process = subprocess.Popen(
            command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True
        )
        process.wait()
        return process.returncode
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n[Launcher] Process interrupted by user." + Style.RESET_ALL)
        if process:
            process.terminate()
        return -1


def select_auth_creds_file() -> Optional[str]:
    """Pick a credentials JSON file from the project folder."""
    json_files = [
        f for f in os.listdir(".")
        if f.endswith(".json") and "session" not in f.lower()
    ]
    if not json_files:
        return prompt_string("Path to credentials JSON file", "auth_creds.json")

    print(Fore.YELLOW + "\nFound JSON files in the project folder:" + Style.RESET_ALL)
    choices = ["Enter custom file path"] + json_files
    choice = prompt_choice("Select credentials JSON file", choices, default_idx=0)
    if choice == "Enter custom file path":
        return prompt_string("Path to credentials JSON file", "auth_creds.json")
    return choice


def main():
    while True:
        clear_screen()
        print_banner()

        print("  1. " + Fore.WHITE + "Quick Scrape (Single Page)" + Style.RESET_ALL)
        print("  2. " + Fore.WHITE + "Recursive Crawler (Full Website)" + Style.RESET_ALL)
        print("  3. " + Fore.WHITE + "View Scan Diff Reports Folder" + Style.RESET_ALL)
        print("  4. " + Fore.WHITE + "Quit Launcher" + Style.RESET_ALL)
        print(Fore.CYAN + "-" * 65)

        action = prompt_choice("What would you like to do?", ["Single Page", "Website Crawler", "View Diff Folder", "Quit"], 0)

        if action == "Quit":
            print(Fore.GREEN + "\nGoodbye! Happy Scraping.\n" + Style.RESET_ALL)
            break

        if action == "View Diff Folder":
            base = "scraped_data"
            if not os.path.exists(base):
                print(Fore.YELLOW + f"\nDirectory {base} does not exist yet (run a scan first)." + Style.RESET_ALL)
            else:
                print(Fore.CYAN + f"\nScan output under {base}:" + Style.RESET_ALL)
                for target_dir in sorted(os.listdir(base)):
                    target_path = os.path.join(base, target_dir)
                    if not os.path.isdir(target_path):
                        continue
                    diffs = os.path.join(target_path, "diffs")
                    scans_root = os.path.join(target_path, "scans")
                    scan_count = 0
                    if os.path.isdir(scans_root):
                        scan_count = len([
                            d for d in os.listdir(scans_root)
                            if os.path.isdir(os.path.join(scans_root, d))
                        ])
                    print(Fore.WHITE + f"\n  {target_dir} ({scan_count} scan(s))" + Style.RESET_ALL)
                    if os.path.isdir(diffs):
                        diff_files = sorted(os.listdir(diffs))
                        if diff_files:
                            print(Fore.CYAN + f"    diffs/ ({len(diff_files)} file(s)):" + Style.RESET_ALL)
                            for f in diff_files[-5:]:
                                print(f"      - {target_dir}/diffs/{f}")
                        else:
                            print("    diffs/ (empty)")
                    if os.path.isdir(scans_root):
                        latest = sorted(os.listdir(scans_root))[-3:]
                        for s in latest:
                            print(Fore.GREEN + f"    scans/{s}/" + Style.RESET_ALL)
                            print("      scrape/report.html  assets/pdfs/")
            input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)
            continue

        # Get target URL
        url = prompt_string("Enter target URL (e.g. https://example.com)")
        if not url:
            print(Fore.RED + "Error: URL is required!")
            input(Fore.YELLOW + "\nPress Enter to return to menu..." + Style.RESET_ALL)
            continue

        cmd_args = ["--url", url]

        # ── Authentication / Login wall ────────────────────────────────
        auth_needed = prompt_choice(
            "Do you need to scrape behind a login wall?",
            ["No", "Yes"],
            0,
        )
        if auth_needed == "Yes":
            session_mode = prompt_choice(
                "Authentication approach:",
                [
                    "Reuse existing session cookie file (skip login)",
                    "Log in now (Patchright or Nodriver)",
                    "Manual OAuth/SSO bootstrap (export session)",
                ],
                0,
            )

            if session_mode.startswith("Reuse"):
                sess_file = prompt_string(
                    "Path to session cookie JSON file",
                    "session.json",
                )
                if sess_file:
                    cmd_args += ["--session-file", sess_file]
                check_url = prompt_string(
                    "Auth check URL to verify session (enter to skip)",
                    "",
                )
                if check_url:
                    cmd_args += ["--auth-check-url", check_url]
                ttl = prompt_string("Session TTL seconds (0 = never expire)", "0")
                if ttl and ttl.isdigit() and int(ttl) > 0:
                    cmd_args += ["--session-ttl", ttl]
                wall = prompt_choice(
                    "On mid-crawl auth wall",
                    ["skip", "abort", "relogin"],
                    0,
                )
                cmd_args += ["--on-auth-wall", wall]

            elif session_mode.startswith("Manual"):
                bootstrap_url = prompt_string(
                    "Bootstrap URL (login / OAuth start page)",
                    url,
                )
                sess_file = prompt_string(
                    "Export session to file",
                    "sessions/bootstrap_session.json",
                )
                if not sess_file:
                    print(Fore.RED + "[Error] Session file is required for bootstrap." + Style.RESET_ALL)
                    input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)
                    continue
                cmd_args += ["--auth-bootstrap", "--session-file", sess_file, "--no-headless"]
                if bootstrap_url:
                    cmd_args += ["--login-url", bootstrap_url]
                wall = prompt_choice(
                    "On mid-crawl auth wall",
                    ["skip", "abort", "relogin"],
                    0,
                )
                cmd_args += ["--on-auth-wall", wall]

            else:
                cred_mode = prompt_choice(
                    "Provide credentials",
                    [
                        "Use credentials JSON file",
                        "Enter username & password now",
                    ],
                    0,
                )

                auth = AuthConfig()

                if "credentials JSON file" in cred_mode:
                    cred_path = select_auth_creds_file()
                    if not cred_path:
                        print(Fore.RED + "[Error] Credentials JSON path is required." + Style.RESET_ALL)
                        input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)
                        continue
                    try:
                        auth = _load_auth_from_json(cred_path)
                        print(
                            Fore.GREEN
                            + f"[Auth] Loaded credentials from {cred_path} "
                            + f"(engine={auth.auth_engine or 'patchright'})"
                            + Style.RESET_ALL
                        )
                    except Exception as exc:
                        print(Fore.RED + f"[Error] Failed to load credentials: {exc}" + Style.RESET_ALL)
                        input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)
                        continue

                    if not auth.login_url:
                        login_url = prompt_string(
                            "Login URL (leave blank to use target URL)",
                            "",
                        )
                        if login_url:
                            auth.login_url = login_url

                    if not auth.auth_engine:
                        auth_engine_choice = prompt_choice(
                            "Choose auth engine",
                            ["patchright (default)", "nodriver (auth-only)"],
                            0,
                        )
                        if "nodriver" in auth_engine_choice.lower():
                            auth.auth_engine = "nodriver"
                        else:
                            auth.auth_engine = "patchright"
                else:
                    login_url = prompt_string(
                        "Login URL (leave blank to use target URL)",
                        "",
                    )
                    if login_url:
                        auth.login_url = login_url

                    auth_engine_choice = prompt_choice(
                        "Choose auth engine",
                        ["patchright (default)", "nodriver (auth-only)"],
                        0,
                    )
                    auth.auth_engine = (
                        "nodriver" if "nodriver" in auth_engine_choice.lower() else "patchright"
                    )

                    auth.username = prompt_string("Username / Email") or ""
                    auth.password = prompt_password("Password") or ""

                if not auth.username or not auth.password:
                    print(Fore.RED + "[Error] Username and password are required." + Style.RESET_ALL)
                    input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)
                    continue

                nodriver_auth = auth.auth_engine == "nodriver"
                if nodriver_auth and not auth.session_file:
                    auth.session_file = prompt_string(
                        "Session cookie file path (required for nodriver auth)",
                        "sessions/nodriver_session.json",
                    )
                    if not auth.session_file:
                        print(Fore.RED + "[Error] Session file path is required for nodriver auth." + Style.RESET_ALL)
                        input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)
                        continue
                elif not nodriver_auth and not auth.session_file:
                    session_file = prompt_string(
                        "Save session cookies to a file? (enter to skip)",
                        "",
                    )
                    if session_file:
                        auth.session_file = session_file

                if not auth.auth_check_url:
                    check_url = prompt_string(
                        "Auth check URL to verify login (enter to skip)",
                        "",
                    )
                    if check_url:
                        auth.auth_check_url = check_url

                if not auth.on_auth_wall:
                    auth.on_auth_wall = prompt_choice(
                        "On mid-crawl auth wall",
                        ["skip", "abort", "relogin"],
                        0,
                    )

                if auth.session_ttl is None:
                    ttl = prompt_string("Session TTL seconds (0 = never expire)", "0")
                    if ttl and ttl.isdigit():
                        auth.session_ttl = int(ttl)

                otp = prompt_choice(
                    "Prompt for OTP/MFA codes during login?",
                    ["No", "Yes"],
                    0,
                )
                if otp == "Yes":
                    auth.otp_prompt = True

                _apply_auth_config(cmd_args, auth)

        # Mode configurations
        if action == "Single Page":
            cmd_args += ["--mode", "single"]
        else:
            cmd_args += ["--mode", "crawl"]
            depth = prompt_string("Max crawl depth", "3")
            max_pages_input = prompt_string("Max pages to scrape [Enter for UNLIMITED \u221e full site crawl]", "")
            concurrency = prompt_string("Parallel concurrency workers", "1")
            cmd_args += ["--depth", depth, "--concurrency", concurrency]

            if max_pages_input and max_pages_input.strip().isdigit():
                cmd_args += ["--max-pages", max_pages_input.strip()]
                n_pages = int(max_pages_input.strip())
                # ETA estimate: avg 2s/page (1s delay_min) ÷ concurrency
                avg_secs = max(1, 2 / max(1, int(concurrency)))
                lo = int(n_pages * avg_secs)
                hi = int(n_pages * max(avg_secs, 5))
                def _fmt(s):
                    m, sec = divmod(s, 60); h, m = divmod(m, 60)
                    return f"{h}h {m}m {sec}s" if h else (f"{m}m {sec}s" if m else f"{sec}s")
                print(Fore.CYAN + f"\n  \u23f1  Estimated crawl time: {_fmt(lo)} \u2013 {_fmt(hi)}  "
                      f"(based on ~{avg_secs:.0f}s avg per page, concurrency={concurrency})" + Style.RESET_ALL)
            else:
                print(Fore.YELLOW + "\n  \u267e  Unlimited mode selected \u2014 crawling until every reachable page is visited." + Style.RESET_ALL)
                print(Fore.CYAN +  "  \u23f1  Estimated time: depends entirely on site size. "
                      "The crawler will keep running until the BFS queue is empty." + Style.RESET_ALL)

        # Output format selection
        fmt_choice = prompt_choice(
            "Select Output formats",
            [
                "JSON, CSV & HTML Report (Default)",
                "All formats (JSON, CSV, Markdown, SQLite, HTML)",
                "HTML Report only",
                "JSON & CSV only",
                "JSON only",
                "CSV only",
                "Markdown only",
                "SQLite only",
            ],
            0,
        )
        fmt_map = {
            "JSON, CSV & HTML Report (Default)":             "json,csv,html",
            "All formats (JSON, CSV, Markdown, SQLite, HTML)": "all",
            "HTML Report only":                              "html",
            "JSON & CSV only":                              "json,csv",
            "JSON only":                                     "json",
            "CSV only":                                      "csv",
            "Markdown only":                                 "markdown",
            "SQLite only":                                   "sqlite",
        }
        cmd_args += ["--format", fmt_map[fmt_choice]]

        # Robots.txt obeying
        robots_choice = prompt_choice("How to handle robots.txt?", ["Respect rules & Crawl-delay (Polite)", "Bypass robots.txt completely (Use responsibly)", "Respect rules but ignore Crawl-delay"], 0)
        if robots_choice == "Bypass robots.txt completely (Use responsibly)":
            cmd_args.append("--no-robots")
        elif robots_choice == "Respect rules but ignore Crawl-delay":
            cmd_args.append("--ignore-crawl-delay")

        # Robust wait-until loading strategy
        wait_choice = prompt_choice("Page loading wait strategy", ["domcontentloaded (Recommended: fast, avoids dynamic connection timeouts)", "networkidle (Wait until full network traffic settles)", "load (Standard document load)"], 0)
        wait_map = {
            "domcontentloaded (Recommended: fast, avoids dynamic connection timeouts)": "domcontentloaded",
            "networkidle (Wait until full network traffic settles)": "networkidle",
            "load (Standard document load)": "load"
        }
        cmd_args += ["--wait-until", wait_map[wait_choice]]

        # Proxy configurations
        use_proxy = prompt_choice("Do you want to use proxies?", ["No (Direct Connection)", "Yes, from a file pool"], 0)
        if use_proxy == "Yes, from a file pool":
            p_file = select_proxy_file()
            if p_file:
                cmd_args += ["--proxy-file", p_file]
                strategy = prompt_choice("Proxy selection strategy", ["latency (Recommended)", "random", "round_robin"], 0)
                strategy_val = "latency" if "latency" in strategy else strategy
                cmd_args += ["--proxy-strategy", strategy_val]


        # Headless mode configurations
        headless_choice = prompt_choice("Run browser in headless mode?", ["Yes (Invisible background, fastest)", "No (Visible headed window, useful to bypass/see captchas)"], 0)
        if headless_choice == "No (Visible headed window, useful to bypass/see captchas)":
            cmd_args.append("--no-headless")

        # Screenshots of blocked/CAPTCHA pages
        screenshot_choice = prompt_choice(
            "Capture screenshots of CAPTCHA / bot-blocked pages?",
            ["Yes (save PNG to scraped_data/screenshots/)", "No (disable screenshots)"],
            0,
        )
        if screenshot_choice == "No (disable screenshots)":
            cmd_args.append("--no-screenshots")

        if action == "Website Crawler":
            allow_sub = prompt_choice(
                "Follow subdomains during crawl?",
                ["Same host only (default)", "Include subdomains (--allow-subdomains)"],
                0,
            )
            if "Include subdomains" in allow_sub:
                cmd_args.append("--allow-subdomains")

        # Run configured command
        run_command(cmd_args)
        input(Fore.YELLOW + "\nPress Enter to return to main menu..." + Style.RESET_ALL)


if __name__ == "__main__":
    main()
