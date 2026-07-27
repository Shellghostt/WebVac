"""
Dismiss cookie banners and privacy / consent popups before login.

Used by both Patchright and Nodriver auth flows.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

# Common CMP / cookie-banner Accept buttons
COOKIE_ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#accept-cookie",
    "#acceptCookies",
    "#cookie-accept",
    "#cookies-accept",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    ".cc-btn.cc-dismiss",
    ".cc-allow",
    ".cc-accept",
    ".cc-accept-all",
    ".cookie-accept",
    ".cookies-accept",
    ".accept-cookies",
    ".accept-all-cookies",
    "[data-testid='cookie-policy-dialog-accept-button']",
    "[data-testid='uc-accept-all-button']",
    "[aria-label*='Accept all' i]",
    "[aria-label*='Accept cookies' i]",
    "button[id*='accept' i][id*='cookie' i]",
    "button[class*='accept' i][class*='cookie' i]",
    "button[id*='onetrust' i]",
    "button[class*='onetrust' i][class*='accept' i]",
]

# Privacy / terms / policy modal Accept / Agree / Continue buttons
PRIVACY_ACCEPT_SELECTORS = [
    "button[id*='privacy' i][id*='accept' i]",
    "button[class*='privacy' i][class*='accept' i]",
    "button[id*='consent' i][id*='accept' i]",
    "button[class*='consent' i][class*='accept' i]",
    "button[id*='terms' i][id*='accept' i]",
    "[data-testid*='accept' i]",
    "[data-action='accept']",
    "[data-consent='accept']",
]

# Text labels (clicked via Playwright :has-text or nodriver find)
ACCEPT_TEXT_LABELS = [
    "Accept all cookies",
    "Accept All Cookies",
    "Accept all",
    "Accept All",
    "Accept cookies",
    "Accept Cookies",
    "I accept",
    "I Accept",
    "I agree",
    "I Agree",
    "Agree and continue",
    "Agree & Continue",
    "Agree and Continu",
    "Allow all",
    "Allow All",
    "Allow cookies",
    "Got it",
    "Got It",
    "OK, got it",
    "Understood",
    "Continue",
    "Agree",
    "Accept",
    "OK",
]

# Never click these when dismissing popups (SSO / reject / settings)
_SKIP_TEXT_RE = re.compile(
    r"google|facebook|github|apple|microsoft|linkedin|"
    r"reject|decline|deny|necessary only|manage|settings|"
    r"customize|preferences|learn more|sign in with|continue with",
    re.I,
)


def _text_looks_safe(text: str) -> bool:
    if not text or not text.strip():
        return False
    if _SKIP_TEXT_RE.search(text):
        return False
    # Prefer short action buttons, not whole paragraphs
    if len(text.strip()) > 80:
        return False
    return True


async def dismiss_popups_patchright(
    page,
    *,
    extra_selectors: Optional[list[str]] = None,
    rounds: int = 3,
) -> int:
    """
    Click Accept / Agree on cookie + privacy overlays (Patchright Page).
    Returns how many controls were clicked.
    """
    clicked = 0
    selectors = list(COOKIE_ACCEPT_SELECTORS) + list(PRIVACY_ACCEPT_SELECTORS)
    if extra_selectors:
        selectors = list(extra_selectors) + selectors

    for _ in range(max(1, rounds)):
        round_hits = 0

        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                for i in range(min(count, 3)):
                    el = loc.nth(i)
                    if not await el.is_visible(timeout=400):
                        continue
                    try:
                        text = (await el.inner_text(timeout=300) or "").strip()
                    except Exception:
                        text = ""
                    if text and not _text_looks_safe(text) and "accept" not in text.lower():
                        continue
                    await el.click(timeout=2000)
                    clicked += 1
                    round_hits += 1
                    print(f"[Auth] Dismissed popup via CSS: {sel}")
                    await asyncio.sleep(0.4)
                    break
            except Exception:
                continue

        for label in ACCEPT_TEXT_LABELS:
            try:
                loc = page.get_by_role("button", name=re.compile(re.escape(label), re.I))
                if await loc.count() == 0:
                    loc = page.locator(f"button:has-text('{label}'), [role='button']:has-text('{label}')")
                if await loc.count() == 0:
                    continue
                el = loc.first
                if not await el.is_visible(timeout=400):
                    continue
                text = (await el.inner_text(timeout=300) or label).strip()
                if not _text_looks_safe(text) and label.lower() not in text.lower():
                    continue
                # Extra guard: "Continue" alone can be a login step — only if in dialog/modal
                if label.lower() in ("continue", "ok", "agree", "accept"):
                    try:
                        in_dialog = await el.evaluate(
                            """el => !!(
                              el.closest('[role="dialog"], [role="alertdialog"], .modal, '
                              + '.cookie, .consent, .privacy, #onetrust, .cc-window, '
                              + '[class*="cookie" i], [class*="consent" i], [id*="consent" i]')
                            )"""
                        )
                        if not in_dialog and label.lower() in ("continue", "ok"):
                            continue
                    except Exception:
                        pass
                await el.click(timeout=2000)
                clicked += 1
                round_hits += 1
                print(f"[Auth] Dismissed popup via text: '{label}'")
                await asyncio.sleep(0.4)
                break
            except Exception:
                continue

        if round_hits == 0:
            break
        await asyncio.sleep(0.3)

    return clicked


async def dismiss_popups_nodriver(
    tab,
    *,
    extra_selectors: Optional[list[str]] = None,
    rounds: int = 3,
) -> int:
    """
    Click Accept / Agree on cookie + privacy overlays (nodriver Tab).
    Returns how many controls were clicked.
    """
    clicked = 0
    selectors = list(COOKIE_ACCEPT_SELECTORS) + list(PRIVACY_ACCEPT_SELECTORS)
    if extra_selectors:
        selectors = list(extra_selectors) + selectors

    for _ in range(max(1, rounds)):
        round_hits = 0

        for sel in selectors:
            try:
                el = await tab.select(sel, timeout=1)
            except Exception:
                el = None
            if not el:
                continue
            try:
                text = str(getattr(el, "text", "") or "")
            except Exception:
                text = ""
            if text and _SKIP_TEXT_RE.search(text) and "accept" not in text.lower():
                continue
            try:
                await el.click()
                clicked += 1
                round_hits += 1
                print(f"[Auth/Nodriver] Dismissed popup via CSS: {sel}")
                await tab.sleep(0.4)
                break
            except Exception:
                continue

        for label in ACCEPT_TEXT_LABELS:
            try:
                el = await tab.find(label, best_match=True)
            except Exception:
                el = None
            if not el:
                continue
            try:
                text = str(getattr(el, "text", "") or label)
            except Exception:
                text = label
            if _SKIP_TEXT_RE.search(text) and "accept" not in text.lower():
                continue
            if len(text.strip()) > 80:
                continue
            # Avoid clicking main login "Continue" unless it looks like a consent control
            if label.lower() in ("continue", "ok"):
                blob = text.lower()
                if "cookie" not in blob and "privacy" not in blob and "consent" not in blob and "agree" not in blob:
                    # Still allow short dialog OK/Continue via surrounding attrs
                    try:
                        html = str(getattr(el, "html", "") or "")[:400].lower()
                    except Exception:
                        html = ""
                    if not any(k in html for k in ("cookie", "consent", "privacy", "modal", "dialog", "onetrust")):
                        continue
            try:
                await el.click()
                clicked += 1
                round_hits += 1
                print(f"[Auth/Nodriver] Dismissed popup via text: '{label}'")
                await tab.sleep(0.4)
                break
            except Exception:
                continue

        if round_hits == 0:
            break
        await tab.sleep(0.3)

    return clicked
