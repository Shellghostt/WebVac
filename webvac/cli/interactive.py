"""
webvac.cli.interactive — Interactive launcher and command wrapper for WebVac.
Provides a menu-driven CLI interface to construct and execute scraping jobs.
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

# Prefer UTF-8 so box-drawing / symbols render on modern Windows terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# ── Visual system ─────────────────────────────────────────────────────────────
# Teal brand + amber accents (readable on dark/light terminals; avoids purple clichés)

_C = Fore.CYAN
_B = Fore.LIGHTCYAN_EX          # brand / emphasis
_A = Fore.LIGHTYELLOW_EX        # accent / prompts
_M = Fore.LIGHTBLACK_EX         # muted / meta
_OK = Fore.LIGHTGREEN_EX
_ERR = Fore.LIGHTRED_EX
_W = Fore.WHITE
_RST = Style.RESET_ALL
_DIM = Style.DIM
_BRIGHT = Style.BRIGHT

_UI_WIDTH = 68


def _unicode_ok() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in enc


def _box() -> dict[str, str]:
    if _unicode_ok():
        return {
            "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
            "h": "─", "v": "│", "dot": "·", "ptr": "▸",
            "ok": "✓", "err": "✗", "info": "›", "warn": "!",
            "q": "?", "bullet": "·",
        }
    return {
        "tl": "+", "tr": "+", "bl": "+", "br": "+",
        "h": "-", "v": "|", "dot": ".", "ptr": ">",
        "ok": "+", "err": "x", "info": ">", "warn": "!",
        "q": "?", "bullet": "*",
    }


def _term_width() -> int:
    try:
        return max(56, min(shutil.get_terminal_size(fallback=(80, 24)).columns, 100))
    except Exception:
        return _UI_WIDTH


def _rule(char: str | None = None, color: str = _M) -> None:
    b = _box()
    print(color + (char or b["h"]) * _term_width() + _RST)


def _blank() -> None:
    print()


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def _version() -> str:
    try:
        from webvac import __version__
        return __version__
    except Exception:
        return "?"


def print_banner():
    """Brand-forward hero for the interactive launcher."""
    w = _term_width()
    ver = _version()
    b = _box()

    print()
    print(_B + b["tl"] + b["h"] * (w - 2) + b["tr"] + _RST)

    logo = [
        r"  __        __   _    __  __          ",
        r"  \ \      / /__| |__ \ \/ /_ _  ___  ",
        r"   \ \ /\ / / _ \ '_ \ \  / _` |/ __| ",
        r"    \ V  V /  __/ |_) |/ \ (_| | (__  ",
        r"     \_/\_/ \___|_.__/_/\_\__,_|\___| ",
    ]
    for line in logo:
        pad = max(0, (w - 2 - len(line)) // 2)
        print(
            _B + b["v"] + _RST
            + " " * pad + _BRIGHT + _B + line + _RST
            + " " * max(0, w - 2 - pad - len(line))
            + _B + b["v"] + _RST
        )

    tag = "asyncio scraper  ·  crawl  ·  recon" if _unicode_ok() else "asyncio scraper | crawl | recon"
    pad = max(0, (w - 2 - len(tag)) // 2)
    print(
        _B + b["v"] + _RST
        + " " * pad + _M + tag + _RST
        + " " * max(0, w - 2 - pad - len(tag))
        + _B + b["v"] + _RST
    )

    meta = f"v{ver}  ·  interactive launcher" if _unicode_ok() else f"v{ver}  |  interactive launcher"
    pad = max(0, (w - 2 - len(meta)) // 2)
    print(
        _B + b["v"] + _RST
        + " " * pad + _A + meta + _RST
        + " " * max(0, w - 2 - pad - len(meta))
        + _B + b["v"] + _RST
    )

    print(_B + b["bl"] + b["h"] * (w - 2) + b["br"] + _RST)
    _blank()


def print_menu(items: list[tuple[str, str, str]]) -> None:
    """
    Render the main action menu.

    items: list of (key, title, description)
    """
    print(_M + "  Choose an action" + _RST)
    _rule(_box()["dot"])
    for key, title, desc in items:
        print(
            f"  {_A}{_BRIGHT}{key}{_RST}"
            f"  {_W}{_BRIGHT}{title}{_RST}"
        )
        print(f"     {_M}{desc}{_RST}")
    _rule(_box()["dot"])
    _blank()


def section(title: str) -> None:
    """Wizard step header."""
    b = _box()
    _blank()
    print(_B + b["ptr"] + " " + _BRIGHT + _W + title + _RST)
    print(_M + "  " + b["h"] * min(40, _term_width() - 4) + _RST)


def ui_ok(text: str) -> None:
    b = _box()
    print(f"  {_OK}{b['ok']}{_RST}  {text}")


def ui_err(text: str) -> None:
    b = _box()
    print(f"  {_ERR}{b['err']}{_RST}  {_ERR}{text}{_RST}")


def ui_info(text: str) -> None:
    b = _box()
    print(f"  {_C}{b['info']}{_RST}  {text}")


def ui_warn(text: str) -> None:
    b = _box()
    print(f"  {_A}{b['warn']}{_RST}  {_A}{text}{_RST}")


def prompt_password(prompt_text: str, default: Optional[str] = None) -> Optional[str]:
    """Read a password without echoing characters to the terminal."""
    b = _box()
    suffix = f" {_M}[{default}]{_RST}" if default else ""
    try:
        val = getpass.getpass(
            f"  {_A}{b['q']}{_RST}  {prompt_text}{suffix}: ",
        )
        val = val.strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\n[Launcher] Cancelled.")
        sys.exit(0)


def prompt_string(prompt_text, default=None):
    b = _box()
    suffix = f" {_M}[{default}]{_RST}" if default else ""
    try:
        val = input(f"  {_A}{b['q']}{_RST}  {prompt_text}{suffix}: ").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\n[Launcher] Cancelled.")
        sys.exit(0)


def prompt_choice(prompt_text, choices, default_idx=0):
    b = _box()
    _blank()
    print(f"  {_W}{_BRIGHT}{prompt_text}{_RST}")
    for idx, choice in enumerate(choices, 1):
        if idx - 1 == default_idx:
            print(f"  {_A}{_BRIGHT}{idx}{_RST}  {_OK}{b['ptr']}{_RST} {_W}{choice}{_RST}")
        else:
            print(f"  {_M}{idx}{_RST}    {_M}{choice}{_RST}")

    default_val = str(default_idx + 1)
    while True:
        try:
            choice = input(
                f"  {_A}{b['q']}{_RST}  Select {_M}(1-{len(choices)}) [{default_val}]{_RST}: "
            ).strip()
            if not choice:
                return choices[default_idx]
            val = int(choice)
            if 1 <= val <= len(choices):
                return choices[val - 1]
            ui_err(f"Invalid choice. Pick 1-{len(choices)}.")
        except ValueError:
            ui_err("Enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\n[Launcher] Cancelled.")
            sys.exit(0)


def _hint(text: str) -> None:
    print(f"  {_M}i  {text}{_RST}")


@dataclass
class AuthConfig:
    username: str = ""
    password: str = ""
    login_url: Optional[str] = None
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

    Supported shape (flat or nested under "creds") — see examples/auth_creds.example.json.
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
    if engine and str(engine).lower() == "nodriver":
        raise ValueError(
            "Nodriver auth has been removed from WebVac. "
            "Use Patchright login or a session file."
        )

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
    from webvac.auth.credentials import redact_cmd_args
    return redact_cmd_args(cmd_args)


EXAMPLES_DIR = "examples"


def _list_candidate_files(
    *,
    suffixes: tuple[str, ...],
    name_contains: Optional[str] = None,
    name_excludes: Optional[tuple[str, ...]] = None,
    prefer_examples: bool = True,
) -> list[str]:
    """Collect matching files from cwd and examples/ (relative paths)."""
    found: list[str] = []
    seen: set[str] = set()

    def _maybe_add(path: str) -> None:
        base = os.path.basename(path).lower()
        if name_contains and name_contains.lower() not in base:
            return
        if name_excludes and any(x.lower() in base for x in name_excludes):
            return
        if not any(base.endswith(s) for s in suffixes):
            return
        if path in seen or not os.path.isfile(path):
            return
        seen.add(path)
        found.append(path)

    search_roots = []
    if prefer_examples and os.path.isdir(EXAMPLES_DIR):
        search_roots.append(EXAMPLES_DIR)
    search_roots.append(".")

    for root in search_roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in sorted(names):
            if name in ("requirements.txt",):
                continue
            rel = name if root == "." else os.path.join(root, name)
            _maybe_add(rel)
    return found


def select_proxy_file() -> Optional[str]:
    _hint("Format: one proxy per line — http://host:port or http://host:port|user|pass")
    _hint(f"Template: {EXAMPLES_DIR}/proxies.example.txt  →  copy to proxies.txt")
    txt_files = _list_candidate_files(
        suffixes=(".txt",),
        name_excludes=("requirements",),
    )
    choices = ["Enter custom file path", "No proxy (direct connection)"] + txt_files
    default_idx = 0
    for i, c in enumerate(choices):
        if c.endswith("proxies.example.txt") or c == "proxies.txt":
            default_idx = i
            break
    choice = prompt_choice("Select a proxy file", choices, default_idx=default_idx)
    if choice == "No proxy (direct connection)":
        return None
    if choice == "Enter custom file path":
        return prompt_string(
            "Path to proxy file",
            os.path.join(EXAMPLES_DIR, "proxies.example.txt"),
        )
    return choice


def select_session_file(*, default: str = "") -> Optional[str]:
    _hint("Preferred: Playwright storage_state JSON (cookies + origins)")
    _hint(f"Templates: {EXAMPLES_DIR}/session.example.json  |  session_cookies_legacy.example.json")
    files = _list_candidate_files(
        suffixes=(".json",),
        name_contains="session",
    )
    # Also offer sessions/ directory files
    if os.path.isdir("sessions"):
        for name in sorted(os.listdir("sessions")):
            if name.endswith(".json"):
                path = os.path.join("sessions", name)
                if path not in files:
                    files.append(path)
    default_path = default or os.path.join(EXAMPLES_DIR, "session.example.json")
    choices = ["Enter custom file path"] + files
    default_idx = 0
    for i, c in enumerate(choices):
        if c.replace("\\", "/").endswith("session.example.json"):
            default_idx = i
            break
    choice = prompt_choice("Select session file", choices, default_idx=default_idx)
    if choice == "Enter custom file path":
        return prompt_string("Path to session JSON file", default_path)
    return choice


def select_pipeline_file() -> Optional[str]:
    _hint("Python file with PIPELINES = [...] or process_item(item)")
    _hint(f"Template: {EXAMPLES_DIR}/pipeline.example.py")
    files = _list_candidate_files(
        suffixes=(".py",),
        name_contains="pipeline",
    )
    choices = ["Skip (no pipeline)", "Enter custom file path"] + files
    choice = prompt_choice("Use a custom data pipeline?", choices, default_idx=0)
    if choice.startswith("Skip"):
        return None
    if choice == "Enter custom file path":
        return prompt_string(
            "Path to pipeline Python file",
            os.path.join(EXAMPLES_DIR, "pipeline.example.py"),
        )
    return choice


def run_command(cmd_args):
    command = [sys.executable, "-m", "webvac"] + cmd_args
    display_args = _redact_cmd_args(cmd_args)
    command_str = " ".join([sys.executable, "-m", "webvac"] + display_args)

    w = _term_width()
    b = _box()
    _blank()
    print(_B + b["tl"] + b["h"] * (w - 2) + b["tr"] + _RST)
    label = " ready to launch "
    fill = max(0, w - 2 - len(label))
    print(_B + b["v"] + _RST + _OK + _BRIGHT + label + _RST + _M + b["h"] * fill + _RST + _B + b["v"] + _RST)
    print(_B + b["v"] + _RST + " " + _M + "command" + _RST + " " * max(0, w - 10) + _B + b["v"] + _RST)
    max_inner = w - 4
    remaining = command_str
    while remaining:
        chunk = remaining[:max_inner]
        remaining = remaining[max_inner:]
        pad = max(0, max_inner - len(chunk))
        print(_B + b["v"] + _RST + " " + _W + chunk + _RST + " " * pad + " " + _B + b["v"] + _RST)
    print(_B + b["bl"] + b["h"] * (w - 2) + b["br"] + _RST)
    _blank()
    ui_info("Starting scraper - live output below")
    _rule()
    _blank()

    process = None
    try:
        process = subprocess.Popen(
            command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True,
        )
        process.wait()
        _blank()
        _rule()
        return process.returncode
    except KeyboardInterrupt:
        _blank()
        ui_warn("Interrupted - stopping scraper")
        if process:
            process.terminate()
        return -1


def select_auth_creds_file() -> Optional[str]:
    """Pick a credentials / auth-profile JSON file from cwd or examples/."""
    _hint("JSON with username, password, login_url, selectors, optional steps/TOTP")
    _hint(f"Template: {EXAMPLES_DIR}/auth_creds.example.json  →  copy to auth_creds.json")
    json_files = _list_candidate_files(
        suffixes=(".json",),
        name_excludes=("session",),
    )
    # Prefer example / auth_creds.json as default
    default_path = "auth_creds.json"
    if os.path.isfile(os.path.join(EXAMPLES_DIR, "auth_creds.example.json")):
        default_path = os.path.join(EXAMPLES_DIR, "auth_creds.example.json")
    if not json_files:
        return prompt_string("Path to credentials JSON file", default_path)

    choices = ["Enter custom file path"] + json_files
    default_idx = 0
    for i, c in enumerate(choices):
        if "auth_creds" in c.replace("\\", "/"):
            default_idx = i
            break
    choice = prompt_choice("Select credentials / auth-profile JSON", choices, default_idx=default_idx)
    if choice == "Enter custom file path":
        return prompt_string("Path to credentials JSON file", default_path)
    return choice


def main():
    while True:
        clear_screen()
        print_banner()
        print_menu([
            ("1", "Quick scrape", "Single page — fast extract & report"),
            ("2", "Site crawler", "BFS crawl — depth, limits, concurrency"),
            ("3", "Scan library", "Browse scraped_data / diffs / reports"),
            ("4", "Quit", "Exit the launcher"),
        ])

        action = prompt_choice(
            "What would you like to do?",
            ["Single Page", "Website Crawler", "View Diff Folder", "Quit"],
            0,
        )

        if action == "Quit":
            _blank()
            print(f"  {_OK}Thanks for using WebVac.{_RST} {_M}See you next crawl.{_RST}\n")
            break

        if action == "View Diff Folder":
            section("Scan library")
            base = "scraped_data"
            if not os.path.exists(base):
                ui_warn(f"{base}/ does not exist yet — run a scan first.")
            else:
                ui_info(f"Output under {_W}{base}/{_RST}")
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
                    _blank()
                    print(f"  {_B}{_BRIGHT}{target_dir}{_RST}  {_M}{scan_count} scan(s){_RST}")
                    if os.path.isdir(diffs):
                        diff_files = sorted(os.listdir(diffs))
                        if diff_files:
                            print(f"    {_M}diffs/{_RST} {_C}{len(diff_files)} file(s){_RST}")
                            for f in diff_files[-5:]:
                                print(f"      {_M}·{_RST} {f}")
                        else:
                            print(f"    {_M}diffs/ (empty){_RST}")
                    if os.path.isdir(scans_root):
                        latest = sorted(os.listdir(scans_root))[-3:]
                        for s in latest:
                            print(f"    {_OK}scans/{s}/{_RST}")
                            print(f"      {_M}scrape/report.html · assets/pdfs/{_RST}")
            _blank()
            input(f"  {_A}?{_RST}  Press Enter to return to menu… ")
            continue

        section("Target")
        url = prompt_string("Enter target URL (e.g. https://example.com)")
        if not url:
            ui_err("URL is required.")
            input(f"  {_A}?{_RST}  Press Enter to return to menu… ")
            continue

        cmd_args = ["--url", url]

        section("Authentication")
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
                    "Log in now (Patchright)",
                    "Manual OAuth/SSO bootstrap (export session)",
                ],
                0,
            )

            if session_mode.startswith("Reuse"):
                sess_file = select_session_file(
                    default=os.path.join(EXAMPLES_DIR, "session.example.json"),
                )
                if sess_file:
                    cmd_args += ["--session-file", sess_file]
                cmd_args += ["--on-auth-wall", "skip"]
                ui_info("Defaults: on-auth-wall=skip, session-ttl=0 (no check URL)")

            elif session_mode.startswith("Manual"):
                _hint("After you finish SSO in the browser, press ENTER to export storage_state")
                _hint(f"See format: {EXAMPLES_DIR}/session.example.json")
                bootstrap_url = prompt_string(
                    "Bootstrap URL (login / OAuth start page)",
                    url,
                )
                sess_file = prompt_string(
                    "Export session to file",
                    "sessions/bootstrap_session.json",
                )
                if not sess_file:
                    ui_err("Session file is required for bootstrap.")
                    input(f"  {_A}?{_RST}  Press Enter to return to menu… ")
                    continue
                cmd_args += ["--auth-bootstrap", "--session-file", sess_file, "--no-headless"]
                if bootstrap_url:
                    cmd_args += ["--login-url", bootstrap_url]
                cmd_args += ["--on-auth-wall", "skip"]

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
                        ui_err("Credentials JSON path is required.")
                        input(f"  {_A}?{_RST}  Press Enter to return to menu… ")
                        continue
                    try:
                        auth = _load_auth_from_json(cred_path)
                        ui_ok(f"Loaded credentials from {cred_path}")
                    except Exception as exc:
                        ui_err(f"Failed to load credentials: {exc}")
                        input(f"  {_A}?{_RST}  Press Enter to return to menu… ")
                        continue
                else:
                    auth.username = prompt_string("Username / Email") or ""
                    auth.password = prompt_password("Password") or ""

                if not auth.username or not auth.password:
                    ui_err("Username and password are required.")
                    input(f"  {_A}?{_RST}  Press Enter to return to menu… ")
                    continue

                if not auth.login_url:
                    auth.login_url = url
                if not auth.session_file:
                    auth.session_file = "sessions/patchright_session.json"
                if not auth.on_auth_wall:
                    auth.on_auth_wall = "skip"
                if auth.session_ttl is None:
                    auth.session_ttl = 0

                ui_info(
                    f"login_url={auth.login_url} · session={auth.session_file} · "
                    f"on-auth-wall={auth.on_auth_wall} · ttl=0 · otp=off"
                    + (f" · check={auth.auth_check_url}" if auth.auth_check_url else "")
                )

                _apply_auth_config(cmd_args, auth)

        section("Crawl settings" if action != "Single Page" else "Mode")
        if action == "Single Page":
            cmd_args += ["--mode", "single"]
            ui_info("Single-page mode")
        else:
            cmd_args += ["--mode", "crawl"]
            depth = prompt_string("Max crawl depth", "3")
            max_pages_input = prompt_string(
                "Max pages to scrape [Enter for UNLIMITED ∞ full site crawl]", ""
            )
            concurrency = prompt_string("Parallel concurrency workers", "1")
            cmd_args += ["--depth", depth, "--concurrency", concurrency]

            if max_pages_input and max_pages_input.strip().isdigit():
                cmd_args += ["--max-pages", max_pages_input.strip()]
                n_pages = int(max_pages_input.strip())
                avg_secs = max(1, 2 / max(1, int(concurrency)))
                lo = int(n_pages * avg_secs)
                hi = int(n_pages * max(avg_secs, 5))

                def _fmt(s):
                    m, sec = divmod(s, 60)
                    h, m = divmod(m, 60)
                    return f"{h}h {m}m {sec}s" if h else (f"{m}m {sec}s" if m else f"{sec}s")

                ui_info(
                    f"Estimated time: {_fmt(lo)} – {_fmt(hi)} "
                    f"(~{avg_secs:.0f}s/page, concurrency={concurrency})"
                )
            else:
                ui_warn("Unlimited mode — crawls until the BFS queue is empty.")
                ui_info("ETA depends on site size.")

        section("Output")
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
            "JSON, CSV & HTML Report (Default)": "json,csv,html",
            "All formats (JSON, CSV, Markdown, SQLite, HTML)": "all",
            "HTML Report only": "html",
            "JSON & CSV only": "json,csv",
            "JSON only": "json",
            "CSV only": "csv",
            "Markdown only": "markdown",
            "SQLite only": "sqlite",
        }
        cmd_args += ["--format", fmt_map[fmt_choice]]

        section("Politeness & loading")
        robots_choice = prompt_choice(
            "How to handle robots.txt?",
            [
                "Respect rules & Crawl-delay (Polite)",
                "Bypass robots.txt completely (Use responsibly)",
                "Respect rules but ignore Crawl-delay",
            ],
            0,
        )
        if robots_choice == "Bypass robots.txt completely (Use responsibly)":
            cmd_args.append("--no-robots")
        elif robots_choice == "Respect rules but ignore Crawl-delay":
            cmd_args.append("--ignore-crawl-delay")

        wait_choice = prompt_choice(
            "Page loading wait strategy",
            [
                "domcontentloaded (Recommended: fast, avoids dynamic connection timeouts)",
                "networkidle (Wait until full network traffic settles)",
                "load (Standard document load)",
            ],
            0,
        )
        wait_map = {
            "domcontentloaded (Recommended: fast, avoids dynamic connection timeouts)": "domcontentloaded",
            "networkidle (Wait until full network traffic settles)": "networkidle",
            "load (Standard document load)": "load",
        }
        cmd_args += ["--wait-until", wait_map[wait_choice]]

        section("Network")
        origin_mode = prompt_choice(
            "Origin IP bypass?",
            ["No (default)", "Enter origin IP (--origin-ip)"],
            0,
        )
        if origin_mode.startswith("Enter origin"):
            oip = prompt_string("Origin IP address")
            if oip:
                cmd_args += ["--origin-ip", oip]
                title = prompt_string(
                    "Expected HTML title for validation (enter to auto-detect)",
                    "",
                )
                if title:
                    cmd_args += ["--origin-title", title]
                skip_val = prompt_choice(
                    "Skip title validation?",
                    ["No (safer)", "Yes (--skip-origin-validate)"],
                    0,
                )
                if skip_val.startswith("Yes"):
                    cmd_args.append("--skip-origin-validate")

        use_proxy = prompt_choice(
            "Do you want to use proxies?",
            ["No (Direct Connection)", "Yes, from a file pool (--proxy-file)"],
            0,
        )
        if use_proxy.startswith("Yes"):
            p_file = select_proxy_file()
            if p_file:
                cmd_args += ["--proxy-file", p_file]
                playbook = prompt_choice(
                    "Proxy playbook",
                    [
                        "residential (sticky=25, UA+geo+tz pin) — Recommended for ISP proxies",
                        "datacenter (sticky=5, round-robin)",
                        "none (manual sticky / strategy)",
                    ],
                    0,
                )
                if playbook.startswith("residential"):
                    cmd_args += ["--proxy-playbook", "residential"]
                elif playbook.startswith("datacenter"):
                    cmd_args += ["--proxy-playbook", "datacenter"]
                else:
                    strategy = prompt_choice(
                        "Proxy selection strategy",
                        ["latency (Recommended)", "random", "round_robin"],
                        0,
                    )
                    strategy_val = "latency" if "latency" in strategy else strategy
                    cmd_args += ["--proxy-strategy", strategy_val]
                    sticky = prompt_string(
                        "Sticky requests per proxy before rotate (0 = disable voluntary rotate)", "10"
                    )
                    if sticky and sticky.isdigit():
                        cmd_args += ["--sticky-requests", sticky]

        pipe = select_pipeline_file()
        if pipe:
            cmd_args += ["--pipeline-file", pipe]

        section("Browser")
        headless_choice = prompt_choice(
            "Run browser in headless mode?",
            [
                "Yes (Invisible background, fastest)",
                "No (Visible headed window, useful to bypass/see captchas)",
            ],
            0,
        )
        if headless_choice.startswith("No"):
            cmd_args.append("--no-headless")
            pause_consent = prompt_choice(
                "Pause after first page so you can Accept cookie banners?",
                [
                    "No (auto-dismiss only — default)",
                    "Yes (--pause-for-consent, wait for ENTER)",
                ],
                0,
            )
            if pause_consent.startswith("Yes"):
                cmd_args.append("--pause-for-consent")
        else:
            ui_info("Auto-dismiss CMP on every page (headed + pause if you need manual Accept)")

        screenshot_choice = prompt_choice(
            "Capture screenshots of CAPTCHA / bot-blocked pages?",
            [
                "Yes (save PNG to scraped_data/screenshots/)",
                "No (disable screenshots)",
            ],
            0,
        )
        if screenshot_choice.startswith("No"):
            cmd_args.append("--no-screenshots")

        if action == "Website Crawler":
            cmd_args.append("--allow-subdomains")
            ui_info("Including subdomains (--allow-subdomains)")

        rc = run_command(cmd_args)
        status_note = "completed" if rc == 0 else f"finished (exit code {rc})"
        if rc == 0:
            ui_ok(f"Scan {status_note}.")
        else:
            ui_warn(f"Scan {status_note}.")

        next_action = prompt_choice(
            "What next?",
            ["Quit", "Return to main menu (another scan)"],
            0,
        )
        if next_action == "Quit":
            _blank()
            print(f"  {_OK}Thanks for using WebVac.{_RST} {_M}See you next crawl.{_RST}\n")
            break



if __name__ == "__main__":
    main()
