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

from models.origin import OriginTarget

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
  """Confirm origin serves the same site (title match)."""
  status, html, title = await fetch_via_origin(
    origin, seed_url, timeout_sec=timeout_sec, proxy=proxy, user_agent=user_agent,
  )
  if status >= 400 or not html:
    return False
  expected = expected_title or origin.expected_title
  if expected:
    return titles_match(expected, title)
  return len(title) > 0 and "cloudflare" not in title.lower()


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
