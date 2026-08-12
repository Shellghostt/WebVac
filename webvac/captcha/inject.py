"""Inject solved CAPTCHA tokens into the live page DOM.

Patterns follow public solver demos (2captcha / CapSolver):
- Turnstile → ``cf-turnstile-response`` (+ ``g-recaptcha-response`` compat) + callback
- reCAPTCHA → ``g-recaptcha-response`` + ``___grecaptcha_cfg`` callback
- hCaptcha → ``h-captcha-response`` + callback
"""

from __future__ import annotations

from webvac.captcha.models import CaptchaInfo, CaptchaType, SolverResult

# Mirrors 2captcha's documented inject steps + their ___grecaptcha_cfg callback finder.
_INJECT_JS = r"""
([token, captchaType, knownCallback]) => {
  const setVal = (el, value) => {
    if (!el) return false;
    try {
      const proto = el.tagName === 'TEXTAREA'
        ? Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')
        : Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      if (proto && proto.set) proto.set.call(el, value);
      else el.value = value;
    } catch (e) {
      try { el.value = value; } catch (e2) { return false; }
    }
    try { el.innerHTML = value; } catch (e) {}
    try {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e) {}
    return true;
  };

  const ensureInput = (name, id, tag) => {
    let el = document.querySelector(`[name="${name}"]`)
      || (id ? document.getElementById(id) : null);
    if (el) return el;
    const form = document.querySelector(
      '#authentication-login-form, form.authentication-login-form, form.login-form, form'
    ) || document.body;
    el = document.createElement(tag || 'input');
    if (tag !== 'textarea') el.type = 'hidden';
    el.name = name;
    if (id) el.id = id;
    el.style.cssText = 'display:none !important';
    form.appendChild(el);
    return el;
  };

  const callFn = (fn, value) => {
    if (typeof fn === 'function') {
      try { fn(value); return true; } catch (e) { return false; }
    }
    if (typeof fn === 'string' && fn && typeof window[fn] === 'function') {
      try { window[fn](value); return true; } catch (e) { return false; }
    }
    return false;
  };

  // 2captcha gist: findRecaptchaClients — walk ___grecaptcha_cfg for callbacks
  const fireRecaptchaCallbacks = (value) => {
    let fired = 0;
    try {
      if (typeof ___grecaptcha_cfg === 'undefined' || !___grecaptcha_cfg.clients) return 0;
      for (const [cid, client] of Object.entries(___grecaptcha_cfg.clients)) {
        const version = Number(cid) >= 10000 ? 'V3' : 'V2';
        const objects = Object.entries(client).filter(([, v]) => v && typeof v === 'object');
        for (const [, toplevel] of objects) {
          if (!toplevel || typeof toplevel !== 'object') continue;
          const found = Object.entries(toplevel).find(([, v]) => (
            v && typeof v === 'object' && 'sitekey' in v && 'size' in v
          ));
          if (!found) continue;
          const [, sublevel] = found;
          const callbackKey = version === 'V2' ? 'callback' : 'promise-callback';
          const cb = sublevel[callbackKey];
          if (callFn(cb, value)) fired++;
        }
      }
    } catch (e) {}
    return fired;
  };

  const fireDataCallbacks = (value) => {
    let fired = 0;
    document.querySelectorAll(
      '.g-recaptcha[data-callback], .cf-turnstile[data-callback], .h-captcha[data-callback], [data-callback][data-sitekey]'
    ).forEach((widget) => {
      const name = widget.getAttribute('data-callback');
      if (callFn(name, value)) fired++;
    });
    return fired;
  };

  let injected = 0;
  let callbackFired = 0;
  const type = String(captchaType || '');

  document.querySelectorAll(
    'textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"], #g-recaptcha-response'
  ).forEach((el) => { if (setVal(el, token)) injected++; });

  document.querySelectorAll(
    'textarea[name="h-captcha-response"], input[name="h-captcha-response"], [name="h-captcha-response"]'
  ).forEach((el) => { if (setVal(el, token)) injected++; });
  document.querySelectorAll('[name="h-captcha-response-data"]').forEach((el) => {
    if (setVal(el, token)) injected++;
  });

  document.querySelectorAll(
    '[name="cf-turnstile-response"], input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
  ).forEach((el) => { if (setVal(el, token)) injected++; });

  document.querySelectorAll(
    '#turnstile_token, input[name="turnstile_token"], textarea[name="turnstile_token"]'
  ).forEach((el) => { if (setVal(el, token)) injected++; });

  if (type.includes('turnstile') || document.querySelector(
    '#turnstile-login-form, .cf-turnstile, script[src*="challenges.cloudflare.com/turnstile"], script[src*="turnstile/v0"]'
  )) {
    if (setVal(ensureInput('cf-turnstile-response'), token)) injected++;
    if (setVal(ensureInput('turnstile_token', 'turnstile_token'), token)) injected++;
    if (setVal(ensureInput('g-recaptcha-response', 'g-recaptcha-response', 'textarea'), token)) {
      injected++;
    }
  }

  // All reCAPTCHA variants need the response textarea (incl. callback-only demos)
  if (type.startsWith('recaptcha')) {
    if (setVal(ensureInput('g-recaptcha-response', 'g-recaptcha-response', 'textarea'), token)) {
      injected++;
    }
  }

  // Named callback from data-callback / extract (v2 Callback demos)
  if (knownCallback && callFn(knownCallback, token)) callbackFired++;

  callbackFired += fireDataCallbacks(token);
  callbackFired += fireRecaptchaCallbacks(token);

  if (!callbackFired) {
    if (callFn(window.onTurnstileCallback, token)) callbackFired++;
    for (const name of Object.getOwnPropertyNames(window)) {
      if (!/^(verify|onCaptcha|onRecaptcha|.*[Cc]allback)$/.test(name)) continue;
      if (name === 'onloadTurnstileCallback') continue;
      if (callFn(window[name], token)) {
        callbackFired++;
        break;
      }
    }
  }

  return {
    injected,
    callbackFired: callbackFired > 0,
    callbacks: callbackFired,
    tokenLength: (token || '').length,
    hasCf: !!document.querySelector('[name="cf-turnstile-response"]'),
    hasGrecaptcha: !!document.querySelector('[name="g-recaptcha-response"], #g-recaptcha-response'),
    hasMirror: !!document.querySelector('#turnstile_token, [name="turnstile_token"]'),
  };
}
"""


async def inject_solution(page, result: SolverResult, info: CaptchaInfo | None = None) -> bool:
    """
    Write the solver token into common CAPTCHA response fields and fire callbacks.

    Returns True only when at least one DOM field was updated OR a callback fired.
    """
    if not result.success or not result.token:
        return False
    captcha_type = info.captcha_type.value if info else "recaptcha_v2"
    known_cb = ""
    if info and isinstance(info.extra, dict):
        known_cb = str(info.extra.get("callback") or "").strip()
    try:
        out = await page.evaluate(
            _INJECT_JS,
            [result.token, captcha_type, known_cb],
        )
    except Exception as exc:
        print(f"[Captcha] DOM inject evaluate failed: {exc}")
        return False
    if not isinstance(out, dict):
        return False
    injected = int(out.get("injected") or 0)
    callback = bool(out.get("callbackFired"))
    if injected or callback:
        print(
            f"[Captcha] Inject OK fields={injected} callback={callback} "
            f"token_len={out.get('tokenLength')} type={captcha_type}"
        )
    else:
        print(
            f"[Captcha] Inject wrote nothing "
            f"(hasCf={out.get('hasCf')} hasG={out.get('hasGrecaptcha')} "
            f"hasMirror={out.get('hasMirror')}) type={captcha_type}"
        )
    return injected > 0 or callback


async def should_reload_after_inject(
    info: CaptchaInfo | None,
    page=None,
) -> bool:
    """Decide whether the page needs a reload after token injection.

    Cloudflare interstitial Turnstile may need a reload for clearance cookies.
    Form-embedded Turnstile / all reCAPTCHA / hCaptcha: no reload.
    """
    if info is None:
        return True
    if info.captcha_type != CaptchaType.TURNSTILE:
        return False
    if page is not None:
        try:
            embedded = await page.evaluate(
                """() => {
                  const form = document.querySelector('form');
                  if (!form) return false;
                  const tok = form.querySelector(
                    '[name="cf-turnstile-response"], [name="turnstile_token"], #turnstile_token'
                  );
                  const pwd = form.querySelector('input[type="password"]');
                  return !!(tok && pwd);
                }"""
            )
            if embedded:
                return False
        except Exception:
            pass
    return True
