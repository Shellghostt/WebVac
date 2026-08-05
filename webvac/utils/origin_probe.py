"""
HTTP origin probing — fetch pages via real IP + Host header (CF bypass path).
"""

from __future__ import annotations

import re
import ssl
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from webvac.models.origin import OriginTarget

_CF_PREFIXES = (
    "103.21.244.", "103.22.200.", "103.31.4.",
    "104.16.", "104.17.", "104.18.", "104.19.", "104.20.", "104.21.",
    "104.22.", "104.23.", "104.24.", "104.25.", "104.26.", "104.27.",
    "104.28.", "131.0.72.",
    "141.101.", "162.158.", "172.64.", "172.65.", "172.66.", "172.67.",
    "172.68.", "172.69.", "172.70.", "172.71.",
    "173.245.", "188.114.", "190.93.", "197.234.", "198.41.",
)


def is_cloudflare_ip(ip: str) -> bool:
    return any(ip.startswith(p) for p in _CF_PREFIXES)


_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)


def extract_title(html: str) -> str:
  if not html:
    return ""
  m = _TITLE_RE.search(html)
  if m:
    return m.group(1).strip()
  try:
    tag = BeautifulSoup(html, "html.parser").find("title")
    return tag.get_text(strip=True) if tag else ""
  except Exception:
    return ""


def titles_match(expected: str, actual: str, *, min_ratio: float = 0.6) -> bool:
  if not expected or not actual:
    return bool(actual) and not expected
  a = expected.lower().strip()
  b = actual.lower().strip()
  if a == b or a in b or b in a:
    return True
  # loose word overlap
  aw = set(re.findall(r"\w+", a))
  bw = set(re.findall(r"\w+", b))
  if not aw:
    return False
  return len(aw & bw) / len(aw) >= min_ratio


async def fetch_via_origin(
  origin: OriginTarget,
  url: str,
  *,
  timeout_sec: float = 30.0,
  proxy: Optional[str] = None,
  user_agent: str = "",
) -> tuple[int, str, str]:
  """
  GET url through origin IP with Host header.
  Returns (status, html, title).
  """
  fetch_url = origin.resolve_fetch_url(url)
  headers = {
    "Host": origin.host_header(),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
  }
  if user_agent:
    headers["User-Agent"] = user_agent

  ssl_ctx = ssl.create_default_context()
  ssl_ctx.check_hostname = False
  ssl_ctx.verify_mode = ssl.CERT_NONE

  timeout = aiohttp.ClientTimeout(total=timeout_sec)
  connector = aiohttp.TCPConnector(ssl=ssl_ctx)
  async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
    async with session.get(fetch_url, headers=headers, proxy=proxy, allow_redirects=True) as resp:
      html = await resp.text(errors="replace")
      return resp.status, html, extract_title(html)


async def validate_origin(
  origin: OriginTarget,
  seed_url: str,
  *,
  expected_title: str = "",
  timeout_sec: float = 30.0,
  proxy: Optional[str] = None,
  user_agent: str = "",
) -> bool:
  """Confirm origin serves the same site (title match). Tries HTTPS then HTTP."""
  expected = expected_title or origin.expected_title
  schemes = []
  primary = origin.scheme or "https"
  schemes.append(primary)
  alt = "http" if primary == "https" else "https"
  if alt not in schemes:
    schemes.append(alt)

  for scheme in schemes:
    trial = OriginTarget(
      hostname=origin.hostname,
      origin_ip=origin.origin_ip,
      scheme=scheme,
      port=443 if scheme == "https" else 80 if origin.port in (80, 443, 0) else origin.port,
      expected_title=expected,
      source=origin.source,
    )
    try:
      status, html, title = await fetch_via_origin(
        trial, seed_url, timeout_sec=timeout_sec, proxy=proxy, user_agent=user_agent,
      )
    except Exception:
      continue
    if status >= 400 or not html:
      continue
    # Reject obvious Cloudflare interstitial / challenge pages
    lower = (html[:4000] + " " + title).lower()
    if "cf-ray" in lower and "cloudflare" in lower and "just a moment" in lower:
      continue
    if expected:
      if titles_match(expected, title):
        origin.scheme = trial.scheme
        origin.port = trial.port
        return True
      continue
    if len(title) > 0 and "cloudflare" not in title.lower() and "attention required" not in title.lower():
      origin.scheme = trial.scheme
      origin.port = trial.port
      return True
  return False


async def probe_ip_candidates(
  hostname: str,
  ips: list[str],
  seed_url: str,
  *,
  expected_title: str = "",
  timeout_sec: float = 30.0,
  proxy: Optional[str] = None,
) -> Optional[OriginTarget]:
  """Try each IP; return first validated OriginTarget."""
  parsed = urlparse(seed_url)
  scheme = parsed.scheme or "https"
  port = parsed.port or (443 if scheme == "https" else 80)

  seen: set[str] = set()
  for ip in ips:
    ip = ip.strip()
    if not ip or ip in seen:
      continue
    seen.add(ip)
    if is_cloudflare_ip(ip):
      continue
    origin = OriginTarget(
      hostname=hostname,
      origin_ip=ip,
      scheme=scheme,
      port=port,
      expected_title=expected_title,
      source="probe",
    )
    try:
      if await validate_origin(
        origin, seed_url, expected_title=expected_title,
        timeout_sec=timeout_sec, proxy=proxy,
      ):
        origin.validated = True
        return origin
    except Exception:
      continue
  return None


async def fetch_vanity_title(
  url: str,
  *,
  timeout_sec: float = 20.0,
  proxy: Optional[str] = None,
  user_agent: str = "",
) -> str:
  """Best-effort title from vanity URL (through CDN) for comparison."""
  headers = {"User-Agent": user_agent} if user_agent else {}
  timeout = aiohttp.ClientTimeout(total=timeout_sec)
  try:
    async with aiohttp.ClientSession(timeout=timeout) as session:
      async with session.get(url, headers=headers, proxy=proxy) as resp:
        html = await resp.text(errors="replace")
        return extract_title(html)
  except Exception:
    return ""
