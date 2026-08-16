"""Extract CAPTCHA parameters from a live page into CaptchaInfo candidates."""

from __future__ import annotations

from typing import Optional, Sequence
from urllib.parse import urlparse

from webvac.captcha.detect import (
    _map_type,
    detect_captcha_candidates_raw,
    detect_captcha_raw,
)
from webvac.captcha.models import CaptchaInfo, CaptchaType
from webvac.captcha.network_watch import NetworkHint

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

_NETWORK_BOOST = 30.0


def _normalize_page_url(website_url: str, page) -> str:
    page_url = website_url or getattr(page, "url", "") or ""
    try:
        parsed = urlparse(page_url)
        page_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            page_url += f"?{parsed.query}"
    except Exception:
        pass
    return page_url


def _raw_to_info(
    raw: dict,
    *,
    page_url: str,
    user_agent: str,
    proxy: Optional[str],
    fallback_keys: Sequence[str] = (),
    fallback_action: str = "",
    fallback_s: str = "",
) -> Optional[CaptchaInfo]:
    captcha_type = _map_type(str(raw.get("type") or ""))
    sitekey = str(raw.get("sitekey") or "").strip()
    if not sitekey and fallback_keys:
        sitekey = str(fallback_keys[0]).strip()

    if captcha_type == CaptchaType.CHALLENGE_PAGE:
        return CaptchaInfo(
            captcha_type=CaptchaType.CHALLENGE_PAGE,
            website_url=page_url,
            website_key="",
            user_agent=user_agent,
            proxy=proxy,
            confidence=float(raw.get("confidence") or 60),
            signals=list(raw.get("signals") or ["challenge_page"]),
        )

    if captcha_type == CaptchaType.UNKNOWN and not sitekey:
        return None

    page_action = str(raw.get("action") or "").strip() or fallback_action
    is_enterprise = bool(raw.get("enterprise")) or captcha_type in (
        CaptchaType.RECAPTCHA_V2_ENTERPRISE,
        CaptchaType.RECAPTCHA_V3_ENTERPRISE,
    )
    is_invisible = bool(raw.get("invisible")) or captcha_type in (
        CaptchaType.RECAPTCHA_V2_INVISIBLE,
        CaptchaType.RECAPTCHA_V3,
        CaptchaType.RECAPTCHA_V3_ENTERPRISE,
    )

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
        confidence=float(raw.get("confidence") or 50),
        signals=list(raw.get("signals") or []),
    )

    cdata = str(raw.get("cdata") or "").strip()
    if cdata:
        info.extra["cdata"] = cdata
    callback = str(raw.get("callback") or "").strip()
    if callback:
        info.extra["callback"] = callback
    s_val = str(raw.get("s") or "").strip() or fallback_s
    if s_val:
        info.extra["s"] = s_val

    if info.captcha_type == CaptchaType.TURNSTILE and not info.page_action:
        host = (urlparse(page_url).hostname or "").lower().removeprefix("www.")
        if host in _HOST_TURNSTILE_ACTION_FALLBACK:
            info.page_action = _HOST_TURNSTILE_ACTION_FALLBACK[host]

    if not info.website_key and info.captcha_type != CaptchaType.CHALLENGE_PAGE:
        return None
    return info


def _network_hint_to_raw(hint: NetworkHint) -> dict:
    if hint.family == "challenge_page":
        return {
            "type": "challenge_page",
            "sitekey": "",
            "confidence": hint.confidence,
            "signals": list(hint.signals),
        }
    if hint.family == "turnstile":
        return {
            "type": "turnstile",
            "sitekey": hint.sitekey,
            "confidence": hint.confidence,
            "signals": list(hint.signals),
            "action": hint.action,
        }
    if hint.family == "hcaptcha":
        return {
            "type": "hcaptcha",
            "sitekey": hint.sitekey,
            "confidence": hint.confidence,
            "signals": list(hint.signals),
        }
    # recaptcha
    if hint.v3:
        typ = "recaptcha_v3_enterprise" if hint.enterprise else "recaptcha_v3"
    elif hint.enterprise:
        typ = "recaptcha_v2_enterprise"
    elif hint.invisible:
        typ = "recaptcha_v2_invisible"
    else:
        typ = "recaptcha_v2"
    return {
        "type": typ,
        "sitekey": hint.sitekey,
        "confidence": hint.confidence,
        "signals": list(hint.signals),
        "invisible": hint.invisible or hint.v3,
        "enterprise": hint.enterprise,
        "action": hint.action,
    }


def _family_of(ctype: CaptchaType) -> str:
    if ctype == CaptchaType.TURNSTILE:
        return "turnstile"
    if ctype == CaptchaType.HCAPTCHA:
        return "hcaptcha"
    if ctype == CaptchaType.CHALLENGE_PAGE:
        return "challenge_page"
    if ctype.value.startswith("recaptcha"):
        return "recaptcha"
    return "unknown"


def merge_dom_and_network(
    dom_infos: list[CaptchaInfo],
    network_hints: Sequence[NetworkHint],
    *,
    page_url: str,
    user_agent: str = "",
    proxy: Optional[str] = None,
) -> list[CaptchaInfo]:
    """Merge DOM + network candidates; boost matching families; add pure-network ones."""
    by_key: dict[tuple[str, str], CaptchaInfo] = {}

    def _key(info: CaptchaInfo) -> tuple[str, str]:
        return (_family_of(info.captcha_type), info.website_key or "")

    for info in dom_infos:
        by_key[_key(info)] = info

    for hint in network_hints:
        raw = _network_hint_to_raw(hint)
        net_info = _raw_to_info(
            raw, page_url=page_url, user_agent=user_agent, proxy=proxy,
        )
        if net_info is None:
            continue

        # Boost matching DOM candidates (same family, same or empty key)
        boosted = False
        for dk, dom in list(by_key.items()):
            fam, key = dk
            if fam != hint.family and not (
                hint.family == "recaptcha" and fam == "recaptcha"
            ):
                continue
            if hint.family == "challenge_page":
                continue
            if key and hint.sitekey and key != hint.sitekey:
                continue
            # merge
            dom.confidence = min(99.0, dom.confidence + _NETWORK_BOOST)
            dom.signals = list(dict.fromkeys(dom.signals + list(hint.signals)))
            if not dom.website_key and hint.sitekey:
                dom.website_key = hint.sitekey
            if hint.invisible:
                dom.is_invisible = True
            if hint.enterprise:
                dom.is_enterprise = True
            if hint.v3 and dom.captcha_type in (
                CaptchaType.RECAPTCHA_V2,
                CaptchaType.RECAPTCHA_V2_INVISIBLE,
                CaptchaType.RECAPTCHA_V2_CALLBACK,
            ):
                dom.captcha_type = (
                    CaptchaType.RECAPTCHA_V3_ENTERPRISE
                    if hint.enterprise
                    else CaptchaType.RECAPTCHA_V3
                )
            if hint.action and not dom.page_action:
                dom.page_action = hint.action
            # re-key if sitekey filled
            new_k = _key(dom)
            if new_k != dk:
                by_key.pop(dk, None)
                by_key[new_k] = dom
            boosted = True

        if not boosted and net_info.solvable:
            net_info.signals = list(dict.fromkeys(net_info.signals + ["network_only"]))
            by_key[_key(net_info)] = net_info
        elif not boosted and net_info.captcha_type == CaptchaType.CHALLENGE_PAGE:
            # Keep challenge marker only if no solvable candidates yet
            if not any(i.solvable for i in by_key.values()):
                by_key[_key(net_info)] = net_info

    ranked = sorted(by_key.values(), key=lambda i: (-i.confidence, -len(i.website_key)))
    # Drop challenge_page if any solvable exists
    if any(i.solvable for i in ranked):
        ranked = [i for i in ranked if i.captcha_type != CaptchaType.CHALLENGE_PAGE]
    return ranked


def variant_remaps(info: CaptchaInfo) -> list[CaptchaInfo]:
    """Alternate CaptchaInfo types to try when CapSolver rejects the primary mapping."""
    alts: list[CaptchaInfo] = []
    ctype = info.captcha_type

    def _clone(new_type: CaptchaType, *, invisible: Optional[bool] = None, enterprise: Optional[bool] = None) -> CaptchaInfo:
        return CaptchaInfo(
            captcha_type=new_type,
            website_url=info.website_url,
            website_key=info.website_key,
            page_action=info.page_action,
            is_invisible=info.is_invisible if invisible is None else invisible,
            is_enterprise=info.is_enterprise if enterprise is None else enterprise,
            user_agent=info.user_agent,
            proxy=info.proxy,
            confidence=info.confidence * 0.9,
            signals=list(info.signals) + [f"remap:{new_type.value}"],
            extra=dict(info.extra),
        )

    if ctype in (
        CaptchaType.RECAPTCHA_V2,
        CaptchaType.RECAPTCHA_V2_CALLBACK,
        CaptchaType.RECAPTCHA_V2_INVISIBLE,
    ):
        for t, inv in (
            (CaptchaType.RECAPTCHA_V2, False),
            (CaptchaType.RECAPTCHA_V2_INVISIBLE, True),
            (CaptchaType.RECAPTCHA_V2_CALLBACK, False),
        ):
            if t != ctype:
                alts.append(_clone(t, invisible=inv))
        if info.is_enterprise or "enterprise" in " ".join(info.signals):
            alts.append(_clone(CaptchaType.RECAPTCHA_V2_ENTERPRISE, enterprise=True))
    elif ctype == CaptchaType.RECAPTCHA_V2_ENTERPRISE:
        alts.append(_clone(CaptchaType.RECAPTCHA_V2, enterprise=False))
        alts.append(_clone(CaptchaType.RECAPTCHA_V2_INVISIBLE, invisible=True, enterprise=False))
    elif ctype == CaptchaType.RECAPTCHA_V3:
        alts.append(_clone(CaptchaType.RECAPTCHA_V3_ENTERPRISE, enterprise=True, invisible=True))
    elif ctype == CaptchaType.RECAPTCHA_V3_ENTERPRISE:
        alts.append(_clone(CaptchaType.RECAPTCHA_V3, enterprise=False, invisible=True))

    return alts


def is_type_mismatch_error(error: Optional[str]) -> bool:
    """True when CapSolver failure suggests wrong task type / flags."""
    err = (error or "").lower()
    needles = (
        "sitekey is not supported",
        "invalid input",
        "invalid websitekey",
        "check captcha type",
        "invisible",
        "pageurl",
        "enterprise",
        "unsupported",
    )
    return any(n in err for n in needles)


async def extract_captcha_candidates(
    page,
    *,
    website_url: str = "",
    user_agent: str = "",
    proxy: Optional[str] = None,
    network_hints: Optional[Sequence[NetworkHint]] = None,
) -> list[CaptchaInfo]:
    """Build ranked CaptchaInfo list from DOM + optional network hints."""
    page_url = _normalize_page_url(website_url, page)
    if not user_agent:
        try:
            user_agent = await page.evaluate("navigator.userAgent") or ""
        except Exception:
            user_agent = ""

    fallback_keys: list[str] = []
    try:
        keys = await page.evaluate(_SITEKEY_FALLBACK_JS)
        if isinstance(keys, list):
            fallback_keys = [str(k).strip() for k in keys if k]
    except Exception:
        pass

    fallback_action = ""
    try:
        fallback_action = str(await page.evaluate(_ACTION_FALLBACK_JS) or "").strip()
    except Exception:
        pass

    fallback_s = ""
    try:
        fallback_s = str(await page.evaluate(_ENTERPRISE_S_JS) or "").strip()
    except Exception:
        pass

    dom_raw = await detect_captcha_candidates_raw(page)
    dom_infos: list[CaptchaInfo] = []
    for raw in dom_raw:
        info = _raw_to_info(
            raw,
            page_url=page_url,
            user_agent=user_agent,
            proxy=proxy,
            fallback_keys=fallback_keys,
            fallback_action=fallback_action,
            fallback_s=fallback_s,
        )
        if info is not None:
            dom_infos.append(info)

    return merge_dom_and_network(
        dom_infos,
        network_hints or [],
        page_url=page_url,
        user_agent=user_agent,
        proxy=proxy,
    )


async def extract_captcha_info(
    page,
    *,
    website_url: str = "",
    user_agent: str = "",
    proxy: Optional[str] = None,
    network_hints: Optional[Sequence[NetworkHint]] = None,
) -> Optional[CaptchaInfo]:
    """
    Build best CaptchaInfo from the current page.

    Returns None when no CAPTCHA widget / sitekey can be found.
    Challenge-only pages return None for CapSolver (use candidates for logging).
    """
    cands = await extract_captcha_candidates(
        page,
        website_url=website_url,
        user_agent=user_agent,
        proxy=proxy,
        network_hints=network_hints,
    )
    for c in cands:
        if c.solvable:
            return c
    return None
