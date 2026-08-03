"""
CF-Hero integration — discover origin IPs behind Cloudflare and validate for scraping.

Upstream: https://github.com/musana/CF-Hero
Install:  go install -v github.com/musana/cf-hero/cmd/cf-hero@latest

CF-Hero CLI accepts domains via ``-f file`` or stdin (not a positional domain arg).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from webvac.models.origin import OriginTarget
from webvac.utils.origin_probe import fetch_vanity_title, probe_ip_candidates

_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# Cloudflare published IPv4 prefixes (edge) — never treat as origin candidates.
# Source: https://www.cloudflare.com/ips/ (subset as dotted prefixes for fast checks)
_CF_PREFIXES = (
    "103.21.244.", "103.22.200.", "103.31.4.",
    "104.16.", "104.17.", "104.18.", "104.19.", "104.20.", "104.21.",
    "104.22.", "104.23.", "104.24.", "104.25.", "104.26.", "104.27.",
    "104.28.", "131.0.72.",
    "141.101.", "162.158.", "172.64.", "172.65.", "172.66.", "172.67.",
    "172.68.", "172.69.", "172.70.", "172.71.",
    "173.245.", "188.114.", "190.93.", "197.234.", "198.41.",
)

_FOUND_LINE_RE = re.compile(
    r"(?:real\s*ip|origin\s*ip|found|validated|success|unmasked)"
    r"[^\d]*(\d{1,3}(?:\.\d{1,3}){3})",
    re.I,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class CFHeroRunResult:
    """Raw + parsed result of a CF-Hero CLI invocation."""

    domain: str
    exit_code: int
    stdout: str
    stderr: str
    candidates: list[str] = field(default_factory=list)
    cmd: list[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


def find_cf_hero_bin(custom: Optional[str] = None) -> Optional[str]:
    """Locate cf-hero binary. Accepts absolute/relative path or PATH name."""
    if custom:
        custom = custom.strip().strip('"').strip("'")
        if custom and os.path.isfile(custom):
            return os.path.abspath(custom)
        which_custom = shutil.which(custom)
        if which_custom:
            return which_custom
    # Common Go install locations beyond PATH
    for candidate in (
        shutil.which("cf-hero"),
        os.path.expanduser("~/go/bin/cf-hero"),
        os.path.expanduser("~/go/bin/cf-hero.exe"),
        "/usr/local/bin/cf-hero",
        os.path.join(os.environ.get("GOPATH", ""), "bin", "cf-hero") if os.environ.get("GOPATH") else "",
        os.path.join(os.environ.get("GOPATH", ""), "bin", "cf-hero.exe") if os.environ.get("GOPATH") else "",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def is_cloudflare_ip(ip: str) -> bool:
    return any(ip.startswith(p) for p in _CF_PREFIXES)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def parse_ips_from_output(text: str) -> list[str]:
    """Extract candidate origin IPs from CF-Hero stdout/stderr (ANSI-safe)."""
    text = strip_ansi(text)
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(ip: str) -> None:
        if ip in seen or is_cloudflare_ip(ip):
            return
        parts = ip.split(".")
        try:
            if not all(0 <= int(p) <= 255 for p in parts):
                return
        except ValueError:
            return
        # Skip obviously private/reserved unless user explicitly needs them
        # (still allow — some origins are RFC1918 behind VPN; keep them)
        seen.add(ip)
        ordered.append(ip)

    for line in text.splitlines():
        for m in _FOUND_LINE_RE.finditer(line):
            _add(m.group(1))
        if re.search(r"real\s*ip|origin|validated|found|unmasked|success", line, re.I):
            for m in _IPV4_RE.finditer(line):
                _add(m.group(1))

    # Fallback: collect all non-CF IPs mentioned (prefer lines with keywords already added)
    if not ordered:
        for m in _IPV4_RE.finditer(text):
            _add(m.group(1))

    return ordered


def build_cf_hero_cmd(
    *,
    bin_path: str,
    domain_file: str,
    title: Optional[str] = None,
    proxy: Optional[str] = None,
    verbose: bool = True,
    workers: Optional[int] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """
    Build argv for CF-Hero.

    Domains MUST be supplied via ``-f`` (or stdin). Positional domain args are invalid.
    """
    cmd = [bin_path, "-f", domain_file]
    if verbose and not (extra_args and "-v" in extra_args):
        cmd.append("-v")
    if title:
        cmd.extend(["-title", title])
    if proxy:
        cmd.extend(["-px", proxy])
    if workers and workers > 0:
        cmd.extend(["-w", str(workers)])
    if extra_args:
        # Avoid duplicating -f / -title / -px if caller already set them via extra
        skip_next = False
        filtered: list[str] = []
        for i, arg in enumerate(extra_args):
            if skip_next:
                skip_next = False
                continue
            if arg in ("-f", "-title", "-px", "-w") and i + 1 < len(extra_args):
                skip_next = True
                continue
            if arg == "-v" and verbose:
                continue
            filtered.append(arg)
        cmd.extend(filtered)
    return cmd


async def run_cf_hero(
    domain: str,
    *,
    bin_path: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
    title: Optional[str] = None,
    proxy: Optional[str] = None,
    verbose: bool = True,
    workers: Optional[int] = None,
    timeout_sec: float = 300.0,
    log_path: Optional[str] = None,
) -> CFHeroRunResult:
    """
    Run cf-hero for a single domain via ``-f`` tempfile.
    Returns structured CFHeroRunResult.
    """
    exe = find_cf_hero_bin(bin_path)
    if not exe:
        raise FileNotFoundError(
            "cf-hero not found on PATH. Install with: "
            "go install -v github.com/musana/cf-hero/cmd/cf-hero@latest"
        )

    domain = (domain or "").strip().lower()
    if not domain:
        raise ValueError("domain is required for CF-Hero")
    # Strip scheme / path if a URL slipped through
    if "://" in domain:
        domain = urlparse(domain).netloc.split("@")[-1]
    domain = domain.split("/")[0].split(":")[0]

    fd, domain_file = tempfile.mkstemp(prefix="webvac_cfhero_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(domain + "\n")

        cmd = build_cf_hero_cmd(
            bin_path=exe,
            domain_file=domain_file,
            title=title,
            proxy=proxy,
            verbose=verbose,
            workers=workers,
            extra_args=extra_args,
        )
        print(f"[CF-Hero] Running: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"cf-hero timed out after {timeout_sec}s")

        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")
        result = CFHeroRunResult(
            domain=domain,
            exit_code=proc.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            candidates=parse_ips_from_output(stdout + "\n" + stderr),
            cmd=cmd,
        )

        if log_path:
            try:
                os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
                with open(log_path, "w", encoding="utf-8") as lf:
                    lf.write(f"# cmd: {' '.join(cmd)}\n")
                    lf.write(f"# exit: {result.exit_code}\n\n")
                    lf.write("--- STDOUT ---\n")
                    lf.write(strip_ansi(stdout))
                    lf.write("\n--- STDERR ---\n")
                    lf.write(strip_ansi(stderr))
                print(f"[CF-Hero] Raw log saved → {log_path}")
            except Exception as exc:
                print(f"[CF-Hero] Could not write log {log_path}: {exc}")

        return result
    finally:
        try:
            os.unlink(domain_file)
        except OSError:
            pass


async def discover_origin(
    seed_url: str,
    hostname: str,
    *,
    bin_path: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
    expected_title: str = "",
    timeout_sec: float = 300.0,
    proxy: Optional[str] = None,
    validate: bool = True,
    verbose: bool = True,
    workers: Optional[int] = None,
    log_path: Optional[str] = None,
) -> Optional[OriginTarget]:
    """
    Run CF-Hero, parse candidate IPs, validate via Host-header probe.
    """
    hostname = (hostname or "").split(":")[0].lower().strip()
    if not hostname:
        print("[CF-Hero] Empty hostname")
        return None

    # Prefer passing title into CF-Hero so it can skip CDN title fetch when blocked
    title = (expected_title or "").strip()
    if not title and validate:
        title = await fetch_vanity_title(seed_url, proxy=proxy) or ""

    try:
        run = await run_cf_hero(
            hostname,
            bin_path=bin_path,
            extra_args=extra_args,
            title=title or None,
            proxy=proxy,
            verbose=verbose,
            workers=workers,
            timeout_sec=timeout_sec,
            log_path=log_path,
        )
    except FileNotFoundError:
        raise
    except Exception as exc:
        print(f"[CF-Hero] Execution failed: {exc}")
        return None

    candidates = list(run.candidates)
    if not candidates:
        print(
            f"[CF-Hero] No candidate IPs parsed for {hostname} "
            f"(exit={run.exit_code})"
        )
        if run.exit_code != 0:
            err_snip = strip_ansi(run.stderr or run.stdout).strip()[:400]
            if err_snip:
                print(f"[CF-Hero] stderr: {err_snip}")
        return None

    print(
        f"[CF-Hero] Parsed {len(candidates)} candidate IP(s) for {hostname}: "
        f"{', '.join(candidates[:8])}{'…' if len(candidates) > 8 else ''}"
    )

    parsed = urlparse(seed_url)
    scheme = parsed.scheme or "https"
    port = parsed.port or (443 if scheme == "https" else 80)

    if not validate:
        ip = candidates[0]
        return OriginTarget(
            hostname=hostname,
            origin_ip=ip,
            scheme=scheme,
            port=port,
            expected_title=title,
            validated=False,
            source="cf-hero",
        )

    origin = await probe_ip_candidates(
        hostname,
        candidates,
        seed_url,
        expected_title=title,
        proxy=proxy,
    )
    if origin:
        origin.source = "cf-hero"
        origin.expected_title = title
        print(
            f"[CF-Hero] Validated origin {origin.origin_ip} for {hostname} "
            f"(title match)"
        )
    else:
        print("[CF-Hero] No candidate IP passed title validation")
        # Soft fallback: return first candidate marked unvalidated so caller
        # can decide (scraper aborts unless --skip-origin-validate)
    return origin


async def apply_origin_to_browser(browser, origin: OriginTarget, slot_identities=None) -> None:
    """Reconfigure Chromium host-resolver so vanity hostname maps to origin IP."""
    await browser.reconfigure_host_resolver(
        origin.host_resolver_rule(),
        slot_identities=slot_identities,
    )
    print(
        f"[CF-Hero] Browser host-resolver active: "
        f"{origin.hostname} → {origin.origin_ip}"
    )
