"""Detect CAPTCHA widgets present on a live page (site-agnostic).

Collects *all* DOM candidates (no first-match early return) with confidence
scores so network hints can merge and re-rank later.
"""

from __future__ import annotations

from webvac.captcha.models import CaptchaType

# Returns {candidates: [...], best: {...}|null}
_DETECT_CANDIDATES_JS = r"""
() => {
  const candidates = [];
  const html = () => document.documentElement ? document.documentElement.innerHTML : '';

  const push = (c) => {
    if (!c || !c.type) return;
    c.signals = c.signals || [];
    c.confidence = typeof c.confidence === 'number' ? c.confidence : 40;
    c.sitekey = c.sitekey || '';
    c.invisible = !!c.invisible;
    c.enterprise = !!c.enterprise;
    c.action = c.action || '';
    c.cdata = c.cdata || '';
    c.callback = c.callback || '';
    c.s = c.s || '';
    candidates.push(c);
  };

  const isEnterprisePage = () => {
    if (document.querySelector('script[src*="recaptcha/enterprise"]')) return true;
    if (typeof grecaptcha !== 'undefined' && grecaptcha && grecaptcha.enterprise) return true;
    return /grecaptcha\.enterprise|recaptcha\/enterprise/i.test(html());
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
    const h = html();
    let m = h.match(/action\s*:\s*[`'"]([^`'"]+)[`'"][^}]{0,120}(?:turnstile|callback)/i);
    if (m) return m[1];
    m = h.match(/(?:turnstile\.render|cf-turnstile)[\s\S]{0,300}?action\s*:\s*[`'"]([^`'"]+)[`'"]/i);
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

  const hAll = html();
  if (
    !document.querySelector('.cf-turnstile[data-sitekey], [data-sitekey].cf-turnstile')
    && (/just a moment|cf-challenge|__cf_chl|checking your browser/i.test(hAll)
        || /cdn-cgi\/challenge-platform/i.test(hAll))
    && !pickTurnstileSitekey()
  ) {
    push({
      type: 'challenge_page',
      confidence: 60,
      signals: ['dom_cf_challenge_markers'],
    });
  }

  const turnstile = document.querySelector('.cf-turnstile[data-sitekey], [data-sitekey].cf-turnstile');
  if (turnstile) {
    const sk = turnstile.getAttribute('data-sitekey') || '';
    push({
      type: 'turnstile',
      sitekey: sk,
      action: turnstile.getAttribute('data-action') || pickTurnstileAction(),
      cdata: turnstile.getAttribute('data-cdata') || '',
      callback: turnstile.getAttribute('data-callback') || '',
      invisible: (turnstile.getAttribute('data-size') || '') === 'invisible'
        || (turnstile.getAttribute('data-appearance') || '') === 'interaction-only',
      confidence: sk ? 85 : 50,
      signals: ['dom_turnstile_widget'],
    });
  }
  const turnstileIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
  if (turnstileIframe) {
    const sk = pickTurnstileSitekey();
    const isChallenge = /challenge-platform/i.test(turnstileIframe.src || '');
    if (isChallenge && !sk) {
      push({
        type: 'challenge_page',
        confidence: 65,
        signals: ['dom_cf_challenge_iframe'],
      });
    } else if (!turnstile) {
      push({
        type: 'turnstile',
        sitekey: sk,
        action: pickTurnstileAction(),
        confidence: sk ? 70 : 45,
        signals: ['dom_turnstile_iframe'],
      });
    }
  }
  const turnstileScript = document.querySelector(
    'script[src*="challenges.cloudflare.com/turnstile"], script[src*="/turnstile/v0/api.js"]'
  );
  const turnstileField = document.querySelector(
    'input[name="cf-turnstile-response"], input[name="turnstile_token"], #turnstile_token, #turnstile-login-form'
  );
  const hasTurnstileApi = typeof window.turnstile !== 'undefined';
  if ((turnstileScript || hasTurnstileApi || turnstileField) && !turnstile) {
    const sk = pickTurnstileSitekey();
    push({
      type: 'turnstile',
      sitekey: sk,
      invisible: true,
      action: pickTurnstileAction(),
      confidence: sk ? 65 : 35,
      signals: [
        turnstileScript ? 'dom_turnstile_script' : null,
        hasTurnstileApi ? 'dom_turnstile_api' : null,
        turnstileField ? 'dom_turnstile_field' : null,
      ].filter(Boolean),
    });
  }

  const hcaps = document.querySelectorAll(
    '.h-captcha[data-sitekey], [data-hcaptcha-sitekey], iframe[src*="hcaptcha.com"]'
  );
  hcaps.forEach((hcap) => {
    let sk = hcap.getAttribute('data-sitekey')
      || hcap.getAttribute('data-hcaptcha-sitekey')
      || '';
    if (!sk && hcap.tagName === 'IFRAME') {
      try {
        const u = new URL(hcap.src);
        sk = u.searchParams.get('sitekey') || '';
      } catch (e) {}
    }
    push({
      type: 'hcaptcha',
      sitekey: sk,
      callback: hcap.getAttribute('data-callback') || '',
      confidence: sk ? 80 : 45,
      signals: hcap.tagName === 'IFRAME' ? ['dom_hcaptcha_iframe'] : ['dom_hcaptcha_widget'],
    });
  });

  const enterprise = isEnterprisePage();
  const fromCfgList = [];
  try {
    if (typeof ___grecaptcha_cfg !== 'undefined' && ___grecaptcha_cfg.clients) {
      for (const [cid, client] of Object.entries(___grecaptcha_cfg.clients)) {
        const version = Number(cid) >= 10000 ? 'V3' : 'V2';
        for (const toplevel of Object.values(client)) {
          if (!toplevel || typeof toplevel !== 'object') continue;
          for (const sub of Object.values(toplevel)) {
            if (!(sub && typeof sub === 'object' && 'sitekey' in sub && 'size' in sub)) continue;
            const cb = sub.callback || sub['promise-callback'] || null;
            fromCfgList.push({
              sitekey: sub.sitekey || '',
              invisible: String(sub.size || '') === 'invisible',
              action: sub.action || '',
              version,
              hasCallback: typeof cb === 'function' || (typeof cb === 'string' && !!cb),
            });
          }
        }
      }
    }
  } catch (e) {}

  const gNodes = document.querySelectorAll('.g-recaptcha[data-sitekey], [data-sitekey].g-recaptcha');
  const h = html();
  const exec = h.match(
    /grecaptcha(?:\.enterprise)?\.execute\(\s*['"]([^'"]+)['"]\s*,\s*\{[^}]*action\s*:\s*['"]([^'"]+)['"]/i
  );
  const renderScript = document.querySelector(
    'script[src*="recaptcha/api.js"][src*="render="], script[src*="recaptcha/enterprise.js"][src*="render="]'
  );
  let renderKey = '';
  if (renderScript) {
    try {
      const u = new URL(renderScript.src, location.href);
      const r = u.searchParams.get('render') || '';
      if (r && r !== 'explicit' && r !== 'onload') renderKey = r;
    } catch (e) {}
  }

  const emitRecaptcha = (opts) => {
    let type = opts.type;
    if (opts.enterprise || enterprise) {
      if (type === 'recaptcha_v3') type = 'recaptcha_v3_enterprise';
      else if (type.indexOf('v3') < 0) type = 'recaptcha_v2_enterprise';
    }
    push({
      type,
      sitekey: opts.sitekey || '',
      action: opts.action || '',
      callback: opts.callback || '',
      invisible: !!opts.invisible,
      enterprise: !!(opts.enterprise || enterprise),
      s: opts.s || '',
      confidence: opts.confidence || 50,
      signals: opts.signals || ['dom_recaptcha'],
    });
  };

  if (renderKey || exec || fromCfgList.some((c) => c.version === 'V3')) {
    const cfg3 = fromCfgList.find((c) => c.version === 'V3');
    emitRecaptcha({
      type: 'recaptcha_v3',
      sitekey: (exec && exec[1]) || renderKey || (cfg3 && cfg3.sitekey) || '',
      action: (exec && exec[2]) || (cfg3 && cfg3.action) || '',
      invisible: true,
      enterprise,
      confidence: 80,
      signals: [
        renderKey ? 'dom_recaptcha_v3_render' : null,
        exec ? 'dom_recaptcha_execute' : null,
        cfg3 ? 'dom_grecaptcha_cfg_v3' : null,
      ].filter(Boolean),
    });
  }

  gNodes.forEach((g) => {
    const widgetCb = g.getAttribute('data-callback') || '';
    const widgetAction = g.getAttribute('data-action') || '';
    const tag = (g.tagName || '').toUpperCase();
    const isButtonLike = tag === 'BUTTON'
      || (tag === 'INPUT' && /submit|button/i.test(g.getAttribute('type') || ''));
    const v3ButtonBind = !!(widgetAction && (isButtonLike || (g.getAttribute('data-size') || '') === 'invisible'));
    const widgetInvisible = (g.getAttribute('data-size') || '') === 'invisible'
      || !!(g.getAttribute('data-bind') || '').trim()
      || (isButtonLike && !widgetAction);
    const widgetSitekey = g.getAttribute('data-sitekey') || '';

    if (v3ButtonBind) {
      emitRecaptcha({
        type: 'recaptcha_v3',
        sitekey: widgetSitekey,
        action: widgetAction,
        callback: widgetCb,
        invisible: true,
        enterprise,
        confidence: widgetSitekey ? 85 : 50,
        signals: ['dom_recaptcha_v3_button'],
      });
      return;
    }

    let type = 'recaptcha_v2';
    if (widgetInvisible) type = 'recaptcha_v2_invisible';
    else if (widgetCb) type = 'recaptcha_v2_callback';

    emitRecaptcha({
      type,
      sitekey: widgetSitekey,
      action: widgetAction,
      callback: widgetCb,
      invisible: widgetInvisible,
      enterprise,
      confidence: widgetSitekey ? 85 : 50,
      signals: ['dom_recaptcha_widget', type],
    });
  });

  fromCfgList.forEach((cfg) => {
    if (cfg.version === 'V3') return;
    let type = 'recaptcha_v2';
    if (cfg.invisible) type = 'recaptcha_v2_invisible';
    else if (cfg.hasCallback) type = 'recaptcha_v2_callback';
    emitRecaptcha({
      type,
      sitekey: cfg.sitekey,
      action: cfg.action,
      invisible: cfg.invisible,
      enterprise,
      confidence: cfg.sitekey ? 75 : 40,
      signals: ['dom_grecaptcha_cfg'],
    });
  });

  document.querySelectorAll(
    'iframe[src*="recaptcha/api2"], iframe[src*="recaptcha/enterprise"]'
  ).forEach((ifr) => {
    let sk = '';
    let inv = false;
    let ent = enterprise || (ifr.src || '').includes('enterprise');
    try {
      const u = new URL(ifr.src);
      sk = u.searchParams.get('k') || '';
      inv = (u.searchParams.get('size') || '') === 'invisible';
    } catch (e) {}
    emitRecaptcha({
      type: inv ? 'recaptcha_v2_invisible' : 'recaptcha_v2',
      sitekey: sk,
      invisible: inv,
      enterprise: ent,
      confidence: sk ? 70 : 40,
      signals: ['dom_recaptcha_iframe'],
    });
  });

  const scripts = Array.from(document.querySelectorAll('script[src]')).map((s) => s.src || '');
  if (scripts.some((s) => s.includes('recaptcha/api.js') || s.includes('recaptcha/enterprise.js'))) {
    if (!candidates.some((c) => String(c.type || '').startsWith('recaptcha'))) {
      emitRecaptcha({
        type: enterprise ? 'recaptcha_v2_enterprise' : 'recaptcha_v2',
        sitekey: renderKey || '',
        enterprise,
        confidence: renderKey ? 55 : 30,
        signals: ['dom_recaptcha_script'],
      });
    }
  }

  const sMatch = h.match(/["']s["']\s*:\s*["']([A-Za-z0-9_-]{20,})["']/);
  if (sMatch) {
    candidates.forEach((c) => {
      if (String(c.type || '').startsWith('recaptcha') && !c.s) c.s = sMatch[1];
    });
  }

  const bestMap = {};
  for (const c of candidates) {
    const key = (c.type || '') + '|' + (c.sitekey || '');
    if (!bestMap[key] || c.confidence > bestMap[key].confidence) {
      if (bestMap[key]) {
        c.signals = Array.from(new Set([...(bestMap[key].signals || []), ...(c.signals || [])]));
      }
      bestMap[key] = c;
    } else {
      bestMap[key].signals = Array.from(new Set([...(bestMap[key].signals || []), ...(c.signals || [])]));
    }
  }
  const ranked = Object.values(bestMap).sort((a, b) => b.confidence - a.confidence);
  return { candidates: ranked, best: ranked.length ? ranked[0] : null };
}
"""

# Backward-compatible alias used by unit tests / callers expecting a single blob.
_DETECT_JS = _DETECT_CANDIDATES_JS


def _map_type(raw: str) -> CaptchaType:
    mapping = {
        "challenge_page": CaptchaType.CHALLENGE_PAGE,
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


async def detect_captcha_candidates_raw(page) -> list[dict]:
    """Return ranked DOM candidate dicts from the page."""
    try:
        pack = await page.evaluate(_DETECT_CANDIDATES_JS)
    except Exception:
        return []
    if not isinstance(pack, dict):
        return []
    cands = pack.get("candidates")
    if not isinstance(cands, list):
        return []
    return [c for c in cands if isinstance(c, dict)]


async def detect_captcha_raw(page) -> dict | None:
    """Return best DOM detection dict from the page, or None (backward compatible)."""
    cands = await detect_captcha_candidates_raw(page)
    if not cands:
        return None
    for c in cands:
        if c.get("sitekey") and str(c.get("type") or "") != "challenge_page":
            return c
    for c in cands:
        if str(c.get("type") or "") != "challenge_page":
            return c
    return cands[0]
