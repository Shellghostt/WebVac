"""Extract CAPTCHA parameters from a live page into CaptchaInfo."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from webvac.captcha.detect import detect_captcha_raw, _map_type
from webvac.captcha.models import CaptchaInfo, CaptchaType

# Optional last-resort Turnstile action when the page never exposes data-action
# or render options in readable form. Prefer page detection over this map.
_HOST_TURNSTILE_ACTION_FALLBACK: dict[str, str] = {
    "chess.com": "login-form",
}

_SITEKEY_FALLBACK_JS = r"""
() => {
  const keys = new Set();
  document.querySelectorAll('[data-sitekey]').forEach(el => {
    const k = el.getAttribute('data-sitekey');
    if (k) keys.add(k);
  });
  document.querySelectorAll('[data-hcaptcha-sitekey]').forEach(el => {
    const k = el.getAttribute('data-hcaptcha-sitekey');
    if (k) keys.add(k);
  });
  try {
    if (window.Config) {
      const cfg = window.Config['turnstile.sitekey']
        || (window.Config.turnstile && window.Config.turnstile.sitekey);
      if (cfg) keys.add(String(cfg));
    }
  } catch (e) {}
  try {
    if (typeof ___grecaptcha_cfg !== 'undefined' && ___grecaptcha_cfg.clients) {
      for (const client of Object.values(___grecaptcha_cfg.clients)) {
        for (const toplevel of Object.values(client || {})) {
          if (!toplevel || typeof toplevel !== 'object') continue;
          for (const sub of Object.values(toplevel)) {
            if (sub && typeof sub === 'object' && sub.sitekey) keys.add(String(sub.sitekey));
          }
        }
      }
    }
  } catch (e) {}
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  const re = /sitekey['"\s:=]+['"]([0-9A-Za-z_-]{20,})['"]/gi;
  let m;
  while ((m = re.exec(html)) !== null) keys.add(m[1]);
  const re2 = /['"]sitekey['"]\s*:\s*['"]([^'"]+)['"]/gi;
  while ((m = re2.exec(html)) !== null) keys.add(m[1]);
  const re3 = /turnstile\.sitekey["'\s:=]+["']([^"']+)["']/gi;
  while ((m = re3.exec(html)) !== null) keys.add(m[1]);
  return Array.from(keys);
}
"""

_ENTERPRISE_S_JS = r"""
() => {
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  const m = html.match(/["']s["']\s*:\s*["']([A-Za-z0-9_-]{20,})["']/);
  return m ? m[1] : '';
}
"""

_ACTION_FALLBACK_JS = r"""
() => {
  const el = document.querySelector('[data-action]');
  if (el) {
    const a = el.getAttribute('data-action') || '';
    if (a) return a;
  }
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  let m = html.match(/grecaptcha(?:\.enterprise)?\.execute\(\s*['"][^'"]+['"]\s*,\s*\{[^}]*action\s*:\s*['"]([^'"]+)['"]/i);
  if (m) return m[1];
  m = html.match(/action\s*:\s*[`'"]([^`'"]+)[`'"][^}]{0,120}(?:turnstile|callback)/i);
  if (m) return m[1];
  m = html.match(/(?:turnstile\.render|cf-turnstile)[\s\S]{0,300}?action\s*:\s*[`'"]([^`'"]+)[`'"]/i);
  if (m) return m[1];
  return '';
}
"""


async def extract_captcha_info(
    page,
    *,
    website_url: str = "",
    user_agent: str = "",
    proxy: Optional[str] = None,
) -> Optional[CaptchaInfo]:
    """
    Build CaptchaInfo from the current page.

    Returns None when no CAPTCHA widget / sitekey can be found.
    """
    raw = await detect_captcha_raw(page)
    if not raw:
        return None

    captcha_type = _map_type(str(raw.get("type") or ""))
    sitekey = str(raw.get("sitekey") or "").strip()

    if not sitekey:
        try:
            keys = await page.evaluate(_SITEKEY_FALLBACK_JS)
            if isinstance(keys, list) and keys:
                sitekey = str(keys[0]).strip()
        except Exception:
            pass

    if captcha_type == CaptchaType.UNKNOWN and not sitekey:
        return None

    page_url = website_url or getattr(page, "url", "") or ""
    try:
        parsed = urlparse(page_url)
        page_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            page_url += f"?{parsed.query}"
    except Exception:
        pass

    if not user_agent:
        try:
            user_agent = await page.evaluate("navigator.userAgent") or ""
        except Exception:
            user_agent = ""

    page_action = str(raw.get("action") or "").strip()
    if not page_action:
        try:
            page_action = str(await page.evaluate(_ACTION_FALLBACK_JS) or "").strip()
        except Exception:
            page_action = ""

    is_enterprise = bool(raw.get("enterprise")) or captcha_type in (
        CaptchaType.RECAPTCHA_V2_ENTERPRISE,
        CaptchaType.RECAPTCHA_V3_ENTERPRISE,
    )
    is_invisible = bool(raw.get("invisible")) or captcha_type in (
        CaptchaType.RECAPTCHA_V2_INVISIBLE,
        CaptchaType.RECAPTCHA_V3,
        CaptchaType.RECAPTCHA_V3_ENTERPRISE,
    )

    # Normalize: enterprise flag on v3 detection → enterprise type
    if captcha_type == CaptchaType.RECAPTCHA_V3 and is_enterprise:
        captcha_type = CaptchaType.RECAPTCHA_V3_ENTERPRISE
    if captcha_type == CaptchaType.RECAPTCHA_V2 and is_enterprise:
        captcha_type = CaptchaType.RECAPTCHA_V2_ENTERPRISE

    if captcha_type == CaptchaType.UNKNOWN:
        captcha_type = CaptchaType.RECAPTCHA_V2

    info = CaptchaInfo(
        captcha_type=captcha_type,
        website_url=page_url,
        website_key=sitekey,
        page_action=page_action,
        is_invisible=is_invisible,
        is_enterprise=is_enterprise,
        user_agent=user_agent,
        proxy=proxy,
    )

    cdata = str(raw.get("cdata") or "").strip()
    if cdata:
        info.extra["cdata"] = cdata
    callback = str(raw.get("callback") or "").strip()
    if callback:
        info.extra["callback"] = callback

    s_val = str(raw.get("s") or "").strip()
    if not s_val:
        try:
            s_val = str(await page.evaluate(_ENTERPRISE_S_JS) or "").strip()
        except Exception:
            s_val = ""
    if s_val:
        info.extra["s"] = s_val

    # Last-resort host map for Turnstile action only (page detect is preferred)
    if info.captcha_type == CaptchaType.TURNSTILE and not info.page_action:
        host = (urlparse(page_url).hostname or "").lower().removeprefix("www.")
        if host in _HOST_TURNSTILE_ACTION_FALLBACK:
            info.page_action = _HOST_TURNSTILE_ACTION_FALLBACK[host]

    if not info.website_key:
        return None
    return info
