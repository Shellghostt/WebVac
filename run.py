"""
run.py — Interactive launcher and command wrapper for WebVac.
Provides a premium menu-driven CLI interface to construct and execute scraping jobs.
"""

import os
import sys
import subprocess
import shutil
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
    command_str = " ".join(command)

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
