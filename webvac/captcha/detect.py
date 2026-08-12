"""Detect CAPTCHA widgets present on a live page (site-agnostic)."""

from __future__ import annotations

from webvac.captcha.models import CaptchaType

# Returns {type, sitekey, invisible, enterprise, action, cdata, callback, s} or null.
_DETECT_JS = r"""
() => {
  const out = {
    type: 'unknown', sitekey: '', invisible: false, enterprise: false,
    action: '', cdata: '', callback: '', s: '',
  };

  const html = () => document.documentElement ? document.documentElement.innerHTML : '';

  const isEnterprisePage = () => {
    if (document.querySelector('script[src*="recaptcha/enterprise"]')) return true;
    if (typeof grecaptcha !== 'undefined' && grecaptcha && grecaptcha.enterprise) return true;
    const h = html();
    return /grecaptcha\.enterprise|recaptcha\/enterprise/i.test(h);
  };

  const pickTurnstileAction = () => {
    const el = document.querySelector(
      '.cf-turnstile[data-action], [data-action].cf-turnstile, [data-sitekey][data-action]'
    );
    if (el) {
      const a = el.getAttribute('data-action') || '';
      if (a) return a;
    }
    try {
      if (window.Config) {
        const fromCfg = window.Config['turnstile.action']
          || (window.Config.turnstile && window.Config.turnstile.action)
          || '';
        if (fromCfg) return String(fromCfg);
      }
    } catch (e) {}
    // Generic: action inside turnstile.render({...}) options (any site)
    const h = html();
    let m = h.match(/action\s*:\s*[`'"]([^`'"]+)[`'"][^}]{0,120}(?:turnstile|callback)/i);
    if (m) return m[1];
    m = h.match(/(?:turnstile\.render|cf-turnstile)[\s\S]{0,300}?action\s*:\s*[`'"]([^`'"]+)[`'"]/i);
    if (m) return m[1];
    m = h.match(/\{\s*callback\s*:[^}]{0,200}?action\s*:\s*[`'"]([^`'"]+)[`'"]/i);
    if (m) return m[1];
    return '';
  };

  const pickTurnstileSitekey = () => {
    const el = document.querySelector(
      '.cf-turnstile[data-sitekey], [data-sitekey].cf-turnstile'
    );
    if (el) {
      const k = el.getAttribute('data-sitekey') || '';
      if (k) return k;
    }
    try {
      if (window.Config) {
        const fromCfg = window.Config['turnstile.sitekey']
          || (window.Config.turnstile && window.Config.turnstile.sitekey)
          || '';
        if (fromCfg) return String(fromCfg);
      }
    } catch (e) {}
    const h = html();
    let m = h.match(/turnstile\.sitekey["'\s:=]+["']([^"']+)["']/i);
    if (m) return m[1];
    m = h.match(/["']sitekey["']\s*:\s*["'](0x[0-9A-Za-z_-]{10,})["']/i);
    if (m) return m[1];
    const iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
    if (iframe && iframe.src) {
      try {
        const u = new URL(iframe.src);
        return u.searchParams.get('sitekey') || '';
      } catch (e) {}
    }
    return '';
  };

  // ── Turnstile ──────────────────────────────────────────────────────────
  const turnstile = document.querySelector('.cf-turnstile[data-sitekey], [data-sitekey].cf-turnstile');
  if (turnstile) {
    out.type = 'turnstile';
    out.sitekey = turnstile.getAttribute('data-sitekey') || '';
    out.action = turnstile.getAttribute('data-action') || pickTurnstileAction();
    out.cdata = turnstile.getAttribute('data-cdata') || '';
    out.callback = turnstile.getAttribute('data-callback') || '';
    out.invisible = (turnstile.getAttribute('data-size') || '') === 'invisible'
      || (turnstile.getAttribute('data-appearance') || '') === 'interaction-only';
    return out;
  }
  const turnstileIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
  if (turnstileIframe) {
    out.type = 'turnstile';
    out.sitekey = pickTurnstileSitekey();
    out.action = pickTurnstileAction();
    return out;
  }
  const turnstileField = document.querySelector(
    'input[name="cf-turnstile-response"], input[name="turnstile_token"], #turnstile_token, #turnstile-login-form, [id*="turnstile"]'
  );
  const turnstileScript = document.querySelector(
    'script[src*="challenges.cloudflare.com/turnstile"], script[src*="/turnstile/v0/api.js"]'
  );
  const hasTurnstileApi = typeof window.turnstile !== 'undefined';
  if (turnstileField || turnstileScript || hasTurnstileApi) {
    // Avoid false positives: only treat generic [id*=turnstile] + turnstile API/script
    if (turnstileScript || hasTurnstileApi || document.querySelector(
      'input[name="cf-turnstile-response"], input[name="turnstile_token"], #turnstile_token, #turnstile-login-form'
    )) {
      out.type = 'turnstile';
      out.invisible = true;
      out.sitekey = pickTurnstileSitekey();
      out.action = pickTurnstileAction();
      return out;
    }
  }

  // ── hCaptcha ───────────────────────────────────────────────────────────
  const hcap = document.querySelector('.h-captcha[data-sitekey], [data-hcaptcha-sitekey], iframe[src*="hcaptcha.com"]');
  if (hcap) {
    out.type = 'hcaptcha';
    out.sitekey = hcap.getAttribute('data-sitekey')
      || hcap.getAttribute('data-hcaptcha-sitekey')
      || '';
    out.callback = hcap.getAttribute('data-callback') || '';
    if (!out.sitekey && hcap.tagName === 'IFRAME') {
      try {
        const u = new URL(hcap.src);
        out.sitekey = u.searchParams.get('sitekey') || '';
      } catch (e) {}
    }
    return out;
  }

  // ── reCAPTCHA (all six variants) ───────────────────────────────────────
  out.enterprise = isEnterprisePage();

  const fromCfg = (() => {
    try {
      if (typeof ___grecaptcha_cfg === 'undefined' || !___grecaptcha_cfg.clients) return null;
      for (const [cid, client] of Object.entries(___grecaptcha_cfg.clients)) {
        const version = Number(cid) >= 10000 ? 'V3' : 'V2';
        for (const toplevel of Object.values(client)) {
          if (!toplevel || typeof toplevel !== 'object') continue;
          for (const sub of Object.values(toplevel)) {
            if (!(sub && typeof sub === 'object' && 'sitekey' in sub && 'size' in sub)) continue;
            const cb = sub.callback || sub['promise-callback'] || null;
            return {
              sitekey: sub.sitekey || '',
              invisible: String(sub.size || '') === 'invisible',
              action: sub.action || '',
              version,
              hasCallback: typeof cb === 'function' || (typeof cb === 'string' && !!cb),
            };
          }
        }
      }
    } catch (e) {}
    return null;
  })();

  const g = document.querySelector('.g-recaptcha[data-sitekey], [data-sitekey].g-recaptcha');
  const widgetCb = g ? (g.getAttribute('data-callback') || '') : '';
  const widgetAction = g ? (g.getAttribute('data-action') || '') : '';
  const widgetInvisible = g
    ? ((g.getAttribute('data-size') || '') === 'invisible')
    : false;
  const widgetSitekey = g ? (g.getAttribute('data-sitekey') || '') : '';

  // v3: grecaptcha.execute(sitekey, {action}) — often no .g-recaptcha widget
  const h = html();
  const exec = h.match(
    /grecaptcha(?:\.enterprise)?\.execute\(\s*['"]([^'"]+)['"]\s*,\s*\{[^}]*action\s*:\s*['"]([^'"]+)['"]/i
  );
  const hasV3Signal = !!(
    (fromCfg && fromCfg.version === 'V3')
    || exec
    || (window.grecaptcha && window.grecaptcha.execute && !document.querySelector('.g-recaptcha'))
  );

  if (hasV3Signal && (exec || (fromCfg && fromCfg.version === 'V3') || !g)) {
    out.type = out.enterprise ? 'recaptcha_v3_enterprise' : 'recaptcha_v3';
    out.sitekey = (exec && exec[1])
      || (fromCfg && fromCfg.sitekey)
      || widgetSitekey
      || '';
    out.action = (exec && exec[2])
      || (fromCfg && fromCfg.action)
      || widgetAction
      || '';
    out.invisible = true;
    return out;
  }

  // v2 family
  out.sitekey = widgetSitekey || (fromCfg && fromCfg.sitekey) || '';
  out.invisible = widgetInvisible || !!(fromCfg && fromCfg.invisible);
  out.action = widgetAction || (fromCfg && fromCfg.action) || '';
  out.callback = widgetCb;

  const hasCallback = !!widgetCb || !!(fromCfg && fromCfg.hasCallback);

  if (out.sitekey || g || fromCfg) {
    if (out.enterprise) {
      out.type = 'recaptcha_v2_enterprise';
    } else if (out.invisible) {
      out.type = 'recaptcha_v2_invisible';
    } else if (hasCallback) {
      // Explicit callback variant (2captcha "v2 Callback" — no submit, callback only)
      out.type = 'recaptcha_v2_callback';
    } else {
      out.type = 'recaptcha_v2';
    }
    if (!out.sitekey && fromCfg) out.sitekey = fromCfg.sitekey || '';
    return out;
  }

  const grecaptchaIframe = document.querySelector(
    'iframe[src*="recaptcha/api2"], iframe[src*="recaptcha/enterprise"]'
  );
  if (grecaptchaIframe) {
    out.enterprise = out.enterprise || (grecaptchaIframe.src || '').includes('enterprise');
    try {
      const u = new URL(grecaptchaIframe.src);
      out.sitekey = u.searchParams.get('k') || '';
    } catch (e) {}
    out.type = out.enterprise ? 'recaptcha_v2_enterprise' : 'recaptcha_v2';
    return out;
  }

  // enterprise ``s`` parameter sometimes embedded near render
  const sMatch = h.match(/["']s["']\s*:\s*["']([A-Za-z0-9_-]{20,})["']/);
  if (sMatch) out.s = sMatch[1];

  const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src || '');
  if (scripts.some(s => s.includes('recaptcha/enterprise.js') || s.includes('recaptcha/api.js'))) {
    out.enterprise = scripts.some(s => s.includes('enterprise'));
    out.type = out.enterprise ? 'recaptcha_v2_enterprise' : 'recaptcha_v2';
    return out;
  }

  return null;
}
"""


def _map_type(raw: str) -> CaptchaType:
    mapping = {
        "recaptcha_v2": CaptchaType.RECAPTCHA_V2,
        "recaptcha_v2_invisible": CaptchaType.RECAPTCHA_V2_INVISIBLE,
        "recaptcha_v2_callback": CaptchaType.RECAPTCHA_V2_CALLBACK,
        "recaptcha_v2_enterprise": CaptchaType.RECAPTCHA_V2_ENTERPRISE,
        "recaptcha_v3": CaptchaType.RECAPTCHA_V3,
        "recaptcha_v3_enterprise": CaptchaType.RECAPTCHA_V3_ENTERPRISE,
        "hcaptcha": CaptchaType.HCAPTCHA,
        "turnstile": CaptchaType.TURNSTILE,
    }
    return mapping.get((raw or "").lower(), CaptchaType.UNKNOWN)


async def detect_captcha_type(page) -> CaptchaType:
    """Return CAPTCHA type on *page*, or UNKNOWN."""
    try:
        raw = await page.evaluate(_DETECT_JS)
    except Exception:
        return CaptchaType.UNKNOWN
    if not raw or not isinstance(raw, dict):
        return CaptchaType.UNKNOWN
    return _map_type(str(raw.get("type") or ""))


async def detect_captcha_raw(page) -> dict | None:
    """Return raw detection dict from the page, or None."""
    try:
        raw = await page.evaluate(_DETECT_JS)
    except Exception:
        return None
    if not raw or not isinstance(raw, dict):
        return None
    return raw


async def page_has_captcha_signal(page) -> bool:
    """True if any CAPTCHA widget, hidden field, or solver script is present."""
    raw = await detect_captcha_raw(page)
    return bool(raw and raw.get("type"))
