"""
CF-Hero integration — discover origin IPs and validate for WebVac scraping.

CF-Hero: https://github.com/musana/CF-Hero
Install: go install -v github.com/musana/cf-hero/cmd/cf-hero@latest
"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import Optional

from models.origin import OriginTarget
from utils.origin_probe import fetch_vanity_title, probe_ip_candidates

_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# Cloudflare edge ranges — skip as origin candidates
_CF_PREFIXES = (
  "104.16.", "104.17.", "104.18.", "104.19.", "104.20.", "104.21.", "104.22.",
  "104.23.", "104.24.", "104.25.", "172.64.", "172.65.", "172.66.", "172.67.",
  "173.245.", "188.114.", "190.93.", "197.234.", "198.41.",
)

_FOUND_LINE_RE = re.compile(
  r"(?:real\s*ip|origin|found|validated|success)[^\d]*(\d{1,3}(?:\.\d{1,3}){3})",
  re.I,
)


def find_cf_hero_bin(custom: Optional[str] = None) -> Optional[str]:
  if custom and shutil.which(custom):
    return custom
  return shutil.which("cf-hero")


def is_cloudflare_ip(ip: str) -> bool:
  return any(ip.startswith(p) for p in _CF_PREFIXES)


def parse_ips_from_output(text: str) -> list[str]:
  """Extract candidate origin IPs from CF-Hero stdout."""
  ordered: list[str] = []
  seen: set[str] = set()

  def _add(ip: str) -> None:
    if ip in seen or is_cloudflare_ip(ip):
      return
    parts = ip.split(".")
    if not all(0 <= int(p) <= 255 for p in parts):
      return
    seen.add(ip)
    ordered.append(ip)

  for line in text.splitlines():
    for m in _FOUND_LINE_RE.finditer(line):
      _add(m.group(1))
    if re.search(r"real\s*ip|origin|validated|found", line, re.I):
      for m in _IPV4_RE.finditer(line):
        _add(m.group(1))

  for m in _IPV4_RE.finditer(text):
    _add(m.group(1))

  return ordered


async def run_cf_hero(
  domain: str,
  *,
  bin_path: Optional[str] = None,
  extra_args: Optional[list[str]] = None,
  timeout_sec: float = 300.0,
) -> tuple[int, str, str]:
  """Run cf-hero CLI. Returns (exit_code, stdout, stderr)."""
  exe = find_cf_hero_bin(bin_path)
  if not exe:
    raise FileNotFoundError(
      "cf-hero not found on PATH. Install with: "
      "go install -v github.com/musana/cf-hero/cmd/cf-hero@latest"
    )

  cmd = [exe, domain]
  if extra_args:
    cmd.extend(extra_args)

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

  return (
    proc.returncode or 0,
    stdout_b.decode(errors="replace"),
    stderr_b.decode(errors="replace"),
  )


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
) -> Optional[OriginTarget]:
  """
  Run CF-Hero, parse IPs, validate via Host-header probe.
  """
  code, stdout, stderr = await run_cf_hero(
    hostname,
    bin_path=bin_path,
    extra_args=extra_args,
    timeout_sec=timeout_sec,
  )
  combined = stdout + "\n" + stderr
  candidates = parse_ips_from_output(combined)
  if not candidates:
    print(f"[CF-Hero] No candidate IPs parsed (exit={code})")
    return None

  print(f"[CF-Hero] Parsed {len(candidates)} candidate IP(s)")

  if not validate:
    ip = candidates[0]
    return OriginTarget(
      hostname=hostname,
      origin_ip=ip,
      expected_title=expected_title,
      validated=False,
      source="cf-hero",
    )

  title = expected_title
  if not title:
    title = await fetch_vanity_title(seed_url, proxy=proxy)

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
    print(f"[CF-Hero] Validated origin {origin.origin_ip} for {hostname}")
  else:
    print("[CF-Hero] No candidate IP passed title validation")
  return origin
