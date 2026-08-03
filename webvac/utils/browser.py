"""
browser.py — Dual-engine browser manager with automatic stealth fallback.

Engine strategy:
  1. Primary:  Patchright stealth engine (automatically bypasses bot detection)

Anti-detection hardening (all free, no proxy required):
  - WebRTC leak blocking       : prevents real IP leaking through WebRTC
  - US geolocation spoofing    : random major US city per context
  - User-Agent rotation        : realistic Chrome/Windows UA per context
  - Navigator property masking : languages, platform, hardwareConcurrency, etc.
  - Canvas/Audio fingerprint   : subtle noise injection via init script
  - Timezone + locale pinning  : always appears as a US en-US user
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from webvac.config.config import DEFAULT_CONFIG
from webvac.utils.detection import is_bot_detected
from webvac.utils.browser_pool import BrowserSlot, SlotIdentity


# ── User-Agent pool ───────────────────────────────────────────────────────────
# Realistic, recent Chrome on Windows 10/11 + macOS user-agents.
# Rotate per context so each session looks like a different device.
_USER_AGENTS: list[str] = [
    # Chrome 124 — Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 — Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
    # Chrome 122 — Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.129 Safari/537.36",
    # Chrome 121 — Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.185 Safari/537.36",
    # Chrome 124 — macOS Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 — macOS Ventura
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome 124 — Windows 11 (21H2)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Safari/537.36",
    # Edge 124 — Windows 10 (Edge sends same Chromium UA)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome 120 — Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.234 Safari/537.36",
    # Chrome 119 — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.199 Safari/537.36",
]

# ── US city geolocation pool ──────────────────────────────────────────────────
# Each entry: (city_name, latitude, longitude, timezone_id)
_US_LOCATIONS: list[tuple[str, float, float, str]] = [
    ("New York, NY",      40.7128,  -74.0060,  "America/New_York"),
    ("Los Angeles, CA",   34.0522, -118.2437,  "America/Los_Angeles"),
    ("Chicago, IL",       41.8781,  -87.6298,  "America/Chicago"),
    ("Houston, TX",       29.7604,  -95.3698,  "America/Chicago"),
    ("Phoenix, AZ",       33.4484, -112.0740,  "America/Phoenix"),
    ("Philadelphia, PA",  39.9526,  -75.1652,  "America/New_York"),
    ("San Antonio, TX",   29.4241,  -98.4936,  "America/Chicago"),
    ("San Diego, CA",     32.7157, -117.1611,  "America/Los_Angeles"),
    ("Dallas, TX",        32.7767,  -96.7970,  "America/Chicago"),
    ("San Jose, CA",      37.3382, -121.8863,  "America/Los_Angeles"),
    ("Austin, TX",        30.2672,  -97.7431,  "America/Chicago"),
    ("Jacksonville, FL",  30.3322,  -81.6557,  "America/New_York"),
    ("San Francisco, CA", 37.7749, -122.4194,  "America/Los_Angeles"),
    ("Seattle, WA",       47.6062, -122.3321,  "America/Los_Angeles"),
    ("Denver, CO",        39.7392, -104.9903,  "America/Denver"),
    ("Nashville, TN",     36.1627,  -86.7816,  "America/Chicago"),
    ("Portland, OR",      45.5051, -122.6750,  "America/Los_Angeles"),
    ("Las Vegas, NV",     36.1699, -115.1398,  "America/Los_Angeles"),
    ("Atlanta, GA",       33.7490,  -84.3880,  "America/New_York"),
    ("Miami, FL",         25.7617,  -80.1918,  "America/New_York"),
]

# ── Viewport size pool ────────────────────────────────────────────────────────
# Common desktop resolutions used by real Windows/macOS users
_VIEWPORTS: list[dict] = [
    {"width": 1920, "height": 1080},   # Most common desktop
    {"width": 1440, "height": 900},    # MacBook Pro 15"
    {"width": 1366, "height": 768},    # Common laptop
    {"width": 1536, "height": 864},    # Common 14" laptop
    {"width": 2560, "height": 1440},   # 2K monitor
    {"width": 1280, "height": 800},    # Older MacBook
]

# ── JavaScript stealth init script ────────────────────────────────────────────
# Injected into every page before any JS runs. Masks automation fingerprints.
_STEALTH_INIT_SCRIPT = r"""
(function() {
    'use strict';

    // 1. Hide navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. Fix navigator.languages to look like a real US browser
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'language',  { get: () => 'en-US' });

    // 3. Realistic platform
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

    // 4. Realistic hardware fingerprint — prevent fingerprinting via concurrency / memory
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory',        { get: () => 8 });

    // 5. Fix plugins — headless Chrome has 0 plugins which is a giveaway
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const makePlugin = (name, filename, desc) => {
                const plugin = { name, filename, description: desc, length: 1 };
                plugin[0] = { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format', enabledPlugin: plugin };
                return plugin;
            };
            const plugins = [
                makePlugin('Chrome PDF Plugin',        'internal-pdf-viewer', 'Portable Document Format'),
                makePlugin('Chrome PDF Viewer',        'mhjfbmdgcfjbbpaeojofohoefgiehjai', ''),
                makePlugin('Native Client',            'internal-nacl-plugin',  ''),
            ];
            plugins.length = 3;
            return plugins;
        }
    });

    // 6. WebRTC IP Spoofer
    //    Instead of disabling WebRTC (which sites detect as suspicious), we
    //    override RTCPeerConnection so it stays fully functional but replaces
    //    all real IPs in ICE candidates and SDP with a consistent fake US ISP IP.
    //    This satisfies WebRTC-based bot checks while exposing zero real data.
    (function() {
        if (typeof RTCPeerConnection === 'undefined') return;

        // ── Fake US residential ISP IP pool ─────────────────────────────────
        // Plausible IPs from major US ISPs (Comcast, AT&T, Cox, Charter, etc.)
        // One is picked at script load time and used consistently all session.
        const FAKE_US_IPS = [
            '73.42.11.87',    // Comcast (Xfinity)
            '68.183.45.129',  // Charter / Spectrum
            '47.201.130.44',  // AT&T
            '76.167.89.23',   // Cox Communications
            '174.210.33.98',  // Lumen / CenturyLink
            '98.6.127.44',    // Comcast
            '71.194.43.117',  // Comcast
            '50.78.167.45',   // Comcast
            '99.232.45.77',   // AT&T Fiber
            '24.105.30.129',  // Cox Communications
            '96.230.14.55',   // Charter
            '75.65.224.11',   // Comcast
        ];
        const FAKE_IP = FAKE_US_IPS[Math.floor(Math.random() * FAKE_US_IPS.length)];

        // ── IP rewriting helpers ─────────────────────────────────────────────
        const PRIVATE_RE = /^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|169\.254\.|0\.0\.0\.0)/;
        const IPV4_RE    = /\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/g;
        const IPV6_RE    = /\b([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b/g;

        function rewriteIP(ip) {
            // Private/loopback stays as 0.0.0.0 (normal for mDNS candidates)
            if (PRIVATE_RE.test(ip)) return '0.0.0.0';
            // Public IP → our fake US residential IP
            return FAKE_IP;
        }

        function rewriteCandidateStr(str) {
            if (!str) return str;
            return str
                .replace(IPV4_RE, rewriteIP)
                .replace(IPV6_RE, '::1');  // collapse all IPv6 to loopback
        }

        // Rewrite only ICE candidate lines and connection data lines in SDP
        function rewriteSDP(sdp) {
            if (!sdp) return sdp;
            return sdp.split('\n').map(line => {
                if (line.startsWith('a=candidate:') ||
                    line.startsWith('c=IN IP4 ')    ||
                    line.startsWith('c=IN IP6 ')) {
                    return rewriteCandidateStr(line);
                }
                return line;
            }).join('\n');
        }

        // Build a spoofed RTCIceCandidate from a real one
        function spoofCandidate(c) {
            if (!c || !c.candidate) return c;
            try {
                return new RTCIceCandidate({
                    candidate:        rewriteCandidateStr(c.candidate),
                    sdpMid:           c.sdpMid,
                    sdpMLineIndex:    c.sdpMLineIndex,
                    usernameFragment: c.usernameFragment,
                });
            } catch (_) { return c; }
        }

        // ── RTCPeerConnection wrapper ────────────────────────────────────────
        const OrigRTC = window.RTCPeerConnection;

        // Wrap an icecandidate event handler to spoof the candidate inside it
        function wrapIceHandler(fn) {
            if (typeof fn !== 'function') return fn;
            return function(event) {
                if (event && event.candidate) {
                    const spoofed = spoofCandidate(event.candidate);
                    const fakeEvt = Object.create(event);
                    Object.defineProperty(fakeEvt, 'candidate', {
                        get: () => spoofed, configurable: true
                    });
                    return fn.call(this, fakeEvt);
                }
                return fn.call(this, event);
            };
        }

        function RTCPeerConnectionSpoofed(config) {
            const pc = new OrigRTC(config);

            // Intercept addEventListener for 'icecandidate'
            const _origAEL = pc.addEventListener.bind(pc);
            pc.addEventListener = function(type, handler, ...rest) {
                if (type === 'icecandidate') handler = wrapIceHandler(handler);
                return _origAEL(type, handler, ...rest);
            };

            // Wrap localDescription getter to return rewritten SDP
            return new Proxy(pc, {
                get(t, prop) {
                    if (prop === 'localDescription' && t.localDescription) {
                        return { type: t.localDescription.type, sdp: rewriteSDP(t.localDescription.sdp) };
                    }
                    if (prop === 'currentLocalDescription' && t.currentLocalDescription) {
                        return { type: t.currentLocalDescription.type, sdp: rewriteSDP(t.currentLocalDescription.sdp) };
                    }
                    const val = t[prop];
                    return typeof val === 'function' ? val.bind(t) : val;
                },
                set(t, prop, value) {
                    if (prop === 'onicecandidate') value = wrapIceHandler(value);
                    t[prop] = value;
                    return true;
                }
            });
        }

        // Preserve prototype chain so instanceof checks still work
        RTCPeerConnectionSpoofed.prototype = OrigRTC.prototype;
        Object.defineProperty(RTCPeerConnectionSpoofed, 'name', { value: 'RTCPeerConnection' });

        // Spoof SDP from createOffer / createAnswer (called before setLocalDescription)
        const _origOffer  = OrigRTC.prototype.createOffer;
        const _origAnswer = OrigRTC.prototype.createAnswer;

        OrigRTC.prototype.createOffer = async function(...a) {
            const o = await _origOffer.apply(this, a);
            return new RTCSessionDescription({ type: o.type, sdp: rewriteSDP(o.sdp) });
        };
        OrigRTC.prototype.createAnswer = async function(...a) {
            const ans = await _origAnswer.apply(this, a);
            return new RTCSessionDescription({ type: ans.type, sdp: rewriteSDP(ans.sdp) });
        };

        window.RTCPeerConnection = RTCPeerConnectionSpoofed;
        // Cover vendor-prefixed variants for older browsers
        if (window.webkitRTCPeerConnection) window.webkitRTCPeerConnection = RTCPeerConnectionSpoofed;
        if (window.mozRTCPeerConnection)    window.mozRTCPeerConnection    = RTCPeerConnectionSpoofed;
    })();


    // 7. Canvas fingerprint noise — add imperceptible per-session noise
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            const data = imageData.data;
            // Flip one byte per ~1000 pixels — visually unnoticeable but changes fingerprint
            for (let i = 0; i < data.length; i += 997) {
                data[i] ^= 1;
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return origToDataURL.apply(this, arguments);
    };

    // 8. Audio fingerprint noise
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function() {
        const data = origGetChannelData.apply(this, arguments);
        for (let i = 0; i < data.length; i += 500) {
            data[i] += Math.random() * 0.0000001;
        }
        return data;
    };

    // 9. Screen dimensions — match the viewport so screen != window.innerWidth discrepancy
    Object.defineProperty(screen, 'colorDepth',      { get: () => 24 });
    Object.defineProperty(screen, 'pixelDepth',      { get: () => 24 });

    // 10. Remove Playwright/automation-specific properties
    delete window.__playwright;
    delete window.__pw_manual;
    delete window.__pwInitScripts;

})();
"""


class BrowserManager:
    """
    Manages a single Chromium browser instance.

    Uses Patchright's stealth-patched engine by default.

    Anti-detection hardening applied automatically per context:
      - User-Agent rotation from a curated pool
      - Random US city geolocation + matching timezone
      - WebRTC ICE candidate spoofing (replaces real IPs with fake US ISP IPs,
        RTCPeerConnection stays functional — sites' WebRTC checks still pass)
      - Navigator property masking (platform, plugins, hardwareConcurrency)
      - Canvas + Audio fingerprint noise injection
      - Viewport size rotation

    """

    def __init__(
        self,
        headless: bool = True,
        user_agent: Optional[str] = None,
        locale: Optional[str] = None,
        timezone_id: Optional[str] = None,
        accept_language: Optional[str] = None,
        rotate_user_agent: bool = True,
        rotate_geolocation: bool = True,
        rotate_viewport: bool = True,
    ) -> None:
        self.headless = headless
        # If a fixed user_agent is provided, use it; otherwise rotate
        self._fixed_user_agent: Optional[str] = user_agent
        self._fixed_locale: Optional[str] = locale
        self._fixed_timezone: Optional[str] = timezone_id
        self.accept_language = accept_language or DEFAULT_CONFIG["accept_language"]
        self.rotate_user_agent = rotate_user_agent
        self.rotate_geolocation = rotate_geolocation
        self.rotate_viewport = rotate_viewport
        self._host_resolver_rules: Optional[str] = None
        self._pool_size: int = 1
        self._slots: list[BrowserSlot] = []
        self._slot_proxy_configs: list[SlotIdentity] = []
        self._session_platform: str = "Windows"
        self._session_sec_ch_ua: str = (
            '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
        )

        # Active engine state
        self._playwright_handle = None
        self._browser = None
        self._context = None

        # Current session identity (set fresh for each new context)
        self._session_ua: str = self._pick_user_agent()
        self._session_location: tuple = self._pick_location()
        self._session_viewport: dict = self._pick_viewport()

        # Auth session — re-injected after context recreate / proxy rotate
        self._auth_cookies: list[dict] = []
        self._auth_storage_state: Optional[dict] = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(
        self,
        proxy: Optional[dict] = None,
        *,
        host_resolver_rules: Optional[str] = None,
        pool_size: int = 1,
        slot_identities: Optional[list[SlotIdentity]] = None,
    ) -> None:
        """
        Launch the browser using Patchright stealth engine.

        Args:
            proxy: Default proxy for slot 0 when slot_identities omitted.
            host_resolver_rules: Chromium MAP rule(s) for origin bypass.
            pool_size: Isolated browser contexts for concurrent workers.
            slot_identities: Per-slot proxy + pinned UA identity.
        """
        self._pool_size = max(1, pool_size)
        self._host_resolver_rules = host_resolver_rules
        if slot_identities:
            self._slot_proxy_configs = slot_identities
        elif proxy:
            self._slot_proxy_configs = [SlotIdentity(proxy=proxy)]
        else:
            self._slot_proxy_configs = []
        await self._launch("patchright")

    async def check_for_bot(
        self,
        page,
        response=None,
        proxy: Optional[dict] = None,
    ) -> bool:
        """
        Run bot-detection heuristics.

        Returns:
            True  — bot detected.
            False — page looks clean.
        """
        if not await is_bot_detected(page, response):
            return False

        print(
            "[Browser] ⚠  Bot/CAPTCHA detected even with Patchright engine. "
            "Consider rotating proxies or adding delays."
        )

        return True

    async def prompt_captcha_solve(self, url: str, proxy: Optional[dict] = None) -> bool:
        """
        Last-resort manual CAPTCHA solver.

        When all automated evasion steps have been exhausted, this method:
          1. Closes the current hidden browser.
          2. Re-launches a VISIBLE browser window (headless=False) so the
             user can see and interact with the CAPTCHA.
          3. Navigates to the blocked URL in the visible window.
          4. Prints a clear terminal prompt and BLOCKS until the user
             presses Enter (signalling that the CAPTCHA has been solved).
          5. Saves the solved cookies back into the context so subsequent
             pages in the same crawl session are already authenticated.
          6. Re-launches the browser in headless mode (restoring normal
             operation) and injects the saved cookies into the new context.

        Args:
            url:   The URL that triggered the CAPTCHA.
            proxy: Active proxy dict (forwarded to the visible browser).

        Returns:
            True  — user confirmed the CAPTCHA was solved.
            False — an error occurred during the visible browser session.
        """
        print()
        print("[CAPTCHA] " + "═" * 55)
        print("[CAPTCHA]  🚨  CAPTCHA / Bot-block detected!")
        print("[CAPTCHA] " + "═" * 55)
        print(f"[CAPTCHA]  URL: {url}")
        print("[CAPTCHA]  Opening a VISIBLE browser window for you to solve it...")
        print("[CAPTCHA] " + "─" * 55)

        # ── Save cookies from current (headless) session ──────────────
        saved_cookies: list = []
        try:
            saved_cookies = await self.get_cookies()
        except Exception:
            pass

        # ── Relaunch as VISIBLE browser ───────────────────────────────
        await self._shutdown_current()
        was_headless = self.headless
        self.headless = False
        try:
            await self._launch(self.engine)
            # Restore previous session cookies so the user lands in the
            # right session context (e.g. logged-in state is preserved)
            if saved_cookies:
                try:
                    await self.load_cookies(saved_cookies)
                except Exception:
                    pass

            visible_page = await self.new_page()
            try:
                await visible_page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            except Exception as nav_err:
                print(f"[CAPTCHA]  Navigation error (non-fatal): {nav_err}")

            # ── Wait for user ─────────────────────────────────────────
            print("[CAPTCHA]")
            print("[CAPTCHA]  👆  A browser window has opened.")
            print("[CAPTCHA]  Please solve the CAPTCHA in that window.")
            print("[CAPTCHA]  When you are done, come back here and press ENTER.")
            print("[CAPTCHA]")

            # Run the blocking input() in a thread so we don't freeze
            # the entire asyncio event loop (important if other tasks
            # are running, e.g. tqdm refreshes).
            loop = asyncio.get_event_loop()
            prompt = "[CAPTCHA]  ▶  Press ENTER when CAPTCHA is solved: "
            timeout_sec = float(DEFAULT_CONFIG.get("captcha_prompt_timeout_sec", 0) or 0)
            try:
                if timeout_sec > 0:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, input, prompt),
                        timeout=timeout_sec,
                    )
                else:
                    await loop.run_in_executor(None, input, prompt)
            except asyncio.TimeoutError:
                print(f"[CAPTCHA]  ⏱  Timed out after {timeout_sec:.0f}s — continuing without solve.")
                await visible_page.close()
                self.headless = was_headless
                await self._shutdown_current()
                await self._launch(self.engine)
                return False

            print("[CAPTCHA]  ✅  Thank you! Resuming scrape...")
            print("[CAPTCHA] " + "═" * 55)
            print()

            # Save cookies AFTER solving so the bypass token is kept
            post_solve_cookies: list = []
            try:
                post_solve_cookies = await self.get_cookies()
            except Exception:
                pass

            await visible_page.close()

            # ── Restore headless browser with solved cookies ───────────
            self.headless = was_headless
            await self._shutdown_current()
            await self._launch(self.engine)
            if post_solve_cookies:
                try:
                    await self.load_cookies(post_solve_cookies)
                except Exception:
                    pass

            return True

        except Exception as exc:
            print(f"[CAPTCHA]  ❌  Error during visible CAPTCHA session: {exc}")
            # Always restore headless mode even on failure
            self.headless = was_headless
            try:
                await self._shutdown_current()
                await self._launch(self.engine)
            except Exception:
                pass
            return False

    async def rotate_proxy(
        self,
        proxy: Optional[dict],
        *,
        slot: int = 0,
        pinned_ua: Optional[str] = None,
        pinned_platform: Optional[str] = None,
        pinned_sec_ch_ua: Optional[str] = None,
    ) -> None:
        """Recreate one pool slot's context with a new proxy and pinned identity."""
        self._apply_identity(
            pinned_ua=pinned_ua,
            pinned_platform=pinned_platform,
            pinned_sec_ch_ua=pinned_sec_ch_ua,
        )
        await self._recreate_slot(
            slot,
            proxy,
            SlotIdentity(
                proxy=proxy,
                ua=self._session_ua,
                platform=self._session_platform,
                sec_ch_ua=self._session_sec_ch_ua,
            ),
        )
        await self._reinject_auth_into_slot(slot)
        label = proxy["server"] if proxy else "direct (no proxy)"
        print(f"[Browser] Slot {slot} rotated → {label}")

    async def reconfigure_host_resolver(
        self,
        rule: Optional[str],
        slot_identities: Optional[list[SlotIdentity]] = None,
    ) -> None:
        """Restart browser with new host-resolver rules (origin bypass)."""
        self._host_resolver_rules = rule
        if slot_identities is not None:
            self._slot_proxy_configs = slot_identities
        engine = getattr(self, "engine", "patchright")
        await self._shutdown_current()
        await self._launch(engine)
        await self.broadcast_auth_session()

    async def new_page(self, slot: int = 0):
        """Open a new tab in an isolated pool slot."""
        slot_idx = slot % max(1, self._pool_size)
        bs = self._slots[slot_idx]
        async with bs.lock:
            for _ in range(30):
                if bs.context:
                    try:
                        return await bs.context.new_page()
                    except Exception as e:
                        err_str = str(e).lower()
                        if "closed" not in err_str and "destroyed" not in err_str:
                            raise e
                await asyncio.sleep(0.5)
        raise RuntimeError(f"Browser slot {slot_idx} unavailable.")

    @property
    def context(self):
        """Primary context (slot 0) for cookie injection."""
        if self._slots:
            return self._slots[0].context
        return self._context

    async def load_cookies(self, cookies: list, slot: int = 0) -> None:
        """Inject saved cookies into a pool slot."""
        ctx = self.context if not self._slots else self._slots[slot % self._pool_size].context
        if cookies and ctx:
            await ctx.add_cookies(self._normalize_cookies(cookies))

    async def get_cookies(self, slot: int = 0) -> list:
        ctx = self.context if not self._slots else self._slots[slot % self._pool_size].context
        return await ctx.cookies() if ctx else []

    def set_auth_session(
        self,
        cookies: Optional[list] = None,
        storage_state: Optional[dict] = None,
    ) -> None:
        """Remember authenticated session for re-injection after context recreate."""
        if cookies is not None:
            self._auth_cookies = self._normalize_cookies(cookies)
        if storage_state is not None:
            self._auth_storage_state = storage_state

    async def capture_auth_session(self, slot: int = 0) -> list[dict]:
        """Snapshot cookies (+ storage state) from a live authenticated slot."""
        cookies = await self.get_cookies(slot=slot)
        storage_state = None
        try:
            ctx = self._slots[slot % self._pool_size].context if self._slots else self._context
            if ctx:
                storage_state = await ctx.storage_state()
        except Exception:
            pass
        self.set_auth_session(cookies=cookies, storage_state=storage_state)
        return list(self._auth_cookies)

    async def broadcast_auth_session(self) -> int:
        """Inject remembered auth cookies into every pool slot. Returns cookie count."""
        if not self._auth_cookies and not self._auth_storage_state:
            return 0
        n_slots = max(1, self._pool_size if self._slots else 1)
        for slot in range(n_slots):
            await self._reinject_auth_into_slot(slot)
        count = len(self._auth_cookies)
        print(f"[Browser] Auth session broadcast to {n_slots} slot(s) ({count} cookies)")
        return count

    async def _reinject_auth_into_slot(self, slot: int) -> None:
        if not self._slots:
            return
        bs = self._slots[slot % self._pool_size]
        if not bs.context:
            return
        cookies = self._auth_cookies
        if not cookies and self._auth_storage_state:
            cookies = self._auth_storage_state.get("cookies") or []
        if cookies:
            try:
                await bs.context.add_cookies(self._normalize_cookies(cookies))
            except Exception as exc:
                print(f"[Browser] Warning: cookie reinject slot {slot} failed: {exc}")
        # Restore localStorage / sessionStorage origins when available
        origins = (self._auth_storage_state or {}).get("origins") or []
        if origins:
            await self._inject_origins_storage(bs.context, origins)

    async def _inject_origins_storage(self, context, origins: list) -> None:
        """Best-effort restore of localStorage from Playwright storage_state origins."""
        for origin in origins:
            origin_url = origin.get("origin")
            local = (origin.get("localStorage") or [])
            if not origin_url or not local:
                continue
            pairs = [
                (e.get("name"), e.get("value"))
                for e in local
                if e.get("name") is not None
            ]
            if not pairs:
                continue
            page = None
            try:
                page = await context.new_page()
                await page.goto(origin_url, wait_until="domcontentloaded", timeout=15000)
                await page.evaluate(
                    """(items) => {
                        for (const [k, v] of items) {
                          try { localStorage.setItem(k, v); } catch (e) {}
                        }
                    }""",
                    pairs,
                )
            except Exception:
                pass
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

    @staticmethod
    def _normalize_cookies(cookies: list) -> list[dict]:
        """Ensure cookies are Playwright add_cookies()-compatible."""
        out: list[dict] = []
        for c in cookies or []:
            if not isinstance(c, dict):
                continue
            name, value = c.get("name"), c.get("value")
            if not name or value is None:
                continue
            item: dict = {"name": name, "value": str(value)}
            if c.get("domain"):
                item["domain"] = c["domain"]
            if c.get("path"):
                item["path"] = c.get("path") or "/"
            else:
                item["path"] = "/"
            if "url" in c and c["url"]:
                item["url"] = c["url"]
            # Playwright requires url OR domain
            if "domain" not in item and "url" not in item:
                continue
            if "expires" in c and c["expires"] not in (None, -1, "-1"):
                try:
                    item["expires"] = float(c["expires"])
                except (TypeError, ValueError):
                    pass
            if "httpOnly" in c:
                item["httpOnly"] = bool(c["httpOnly"])
            if "secure" in c:
                item["secure"] = bool(c["secure"])
            same = c.get("sameSite")
            if same in ("Strict", "Lax", "None"):
                item["sameSite"] = same
            elif isinstance(same, str):
                mapped = {"strict": "Strict", "lax": "Lax", "none": "None"}.get(same.lower())
                if mapped:
                    item["sameSite"] = mapped
            out.append(item)
        return out

    async def stop(self) -> None:
        """Shut down the browser cleanly."""
        await self._shutdown_current()
        print("[Browser] Chromium closed.")

    async def human_warmup(self, target_url: str) -> None:
        """
        Warm up the browser session by visiting the site's root domain first,
        simulating realistic human arrival behaviour before the actual target
        page is loaded.

        What this does:
          1. Opens a new page.
          2. Navigates to the target's root domain (e.g. https://example.com).
          3. Waits a realistic human read-time (3–8 seconds).
          4. Performs random mouse movements across the viewport.
          5. Scrolls down slowly then back up (as a human would skim the page).
          6. Closes the warmup page.
        After this the browser context has site cookies and a navigation history,
        making subsequent requests look like continued browsing rather than a
        direct cold-start bot hit.

        Args:
            target_url: The URL about to be scraped (used to extract root domain).
        """
        from urllib.parse import urlparse
        parsed = urlparse(target_url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        print(f"[Browser] [Warmup] Visiting root domain {root} to build session...")

        page = await self.new_page()
        try:
            await page.goto(root, wait_until="domcontentloaded", timeout=20000)

            # Realistic dwell time: 3–8 seconds
            await asyncio.sleep(random.uniform(3.0, 8.0))

            # Random mouse movements across the viewport
            vp = self._session_viewport
            for _ in range(random.randint(4, 9)):
                x = random.randint(80, vp["width"]  - 80)
                y = random.randint(80, vp["height"] - 80)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.1, 0.5))

            # Slow scroll down 2–4 viewport heights
            scroll_steps = random.randint(2, 4)
            for i in range(scroll_steps):
                await page.evaluate(f"window.scrollBy(0, {random.randint(200, 500)})")
                await asyncio.sleep(random.uniform(0.4, 1.2))

            # Pause as if reading, then scroll back up
            await asyncio.sleep(random.uniform(1.0, 3.0))
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(random.uniform(0.5, 1.5))

            print(f"[Browser] [Warmup] Done — session warmed on {parsed.netloc}")
        except Exception as exc:
            print(f"[Browser] [Warmup] Non-fatal warmup error: {exc}")
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # ── Identity helpers ──────────────────────────────────────────────────────

    def _pick_user_agent(self) -> str:
        if self._fixed_user_agent:
            return self._fixed_user_agent
        if self.rotate_user_agent:
            return random.choice(_USER_AGENTS)
        return DEFAULT_CONFIG["user_agent"]

    def _pick_location(self) -> tuple:
        """Return a (city, lat, lon, timezone) tuple."""
        if self._fixed_timezone:
            # If timezone is fixed, find a matching location or fall back to NYC
            for loc in _US_LOCATIONS:
                if loc[3] == self._fixed_timezone:
                    return loc
        if self.rotate_geolocation:
            return random.choice(_US_LOCATIONS)
        # Default to New York
        return _US_LOCATIONS[0]

    def _pick_viewport(self) -> dict:
        if self.rotate_viewport:
            return random.choice(_VIEWPORTS)
        return {"width": 1920, "height": 1080}

    def _apply_identity(
        self,
        *,
        pinned_ua: Optional[str] = None,
        pinned_platform: Optional[str] = None,
        pinned_sec_ch_ua: Optional[str] = None,
    ) -> None:
        self._session_ua = pinned_ua or self._pick_user_agent()
        self._session_platform = pinned_platform or "Windows"
        self._session_sec_ch_ua = pinned_sec_ch_ua or (
            '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
        )
        self._session_location = self._pick_location()
        self._session_viewport = self._pick_viewport()

    def _rotate_identity(self, pinned_ua: Optional[str] = None) -> None:
        self._apply_identity(pinned_ua=pinned_ua)
        city = self._session_location[0]
        print(f"[Browser] [Identity] {self._session_ua[:65]}...  location={city}")

    def _navigator_platform(self) -> str:
        return "MacIntel" if "mac" in self._session_platform.lower() else "Win32"

    async def _recreate_slot(
        self, slot: int, proxy: Optional[dict], identity: SlotIdentity,
    ) -> None:
        slot_idx = slot % max(1, self._pool_size)
        while len(self._slots) <= slot_idx:
            self._slots.append(BrowserSlot(index=len(self._slots)))
        bs = self._slots[slot_idx]
        self._apply_identity(
            pinned_ua=identity.ua or None,
            pinned_platform=identity.platform,
            pinned_sec_ch_ua=identity.sec_ch_ua,
        )
        await bs.close()
        bs.identity = identity
        bs.context = await self._new_context(
            proxy or identity.proxy,
            ignore_https_errors=bool(self._host_resolver_rules),
        )
        if slot_idx == 0:
            self._context = bs.context
        await self._reinject_auth_into_slot(slot_idx)

    async def _init_pool(self) -> None:
        self._slots = []
        for i in range(self._pool_size):
            ident = (
                self._slot_proxy_configs[i]
                if i < len(self._slot_proxy_configs)
                else SlotIdentity()
            )
            if ident.ua:
                self._apply_identity(
                    pinned_ua=ident.ua,
                    pinned_platform=ident.platform,
                    pinned_sec_ch_ua=ident.sec_ch_ua,
                )
            else:
                self._rotate_identity()
            bs = BrowserSlot(index=i, identity=ident)
            bs.context = await self._new_context(
                ident.proxy,
                ignore_https_errors=bool(self._host_resolver_rules),
            )
            self._slots.append(bs)
        self._context = self._slots[0].context if self._slots else None

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _launch(self, engine: str) -> None:
        """Launch browser and initialize the context pool."""
        from patchright.async_api import async_playwright

        self.engine = engine
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            f"--window-size={self._session_viewport['width']},{self._session_viewport['height']}",
        ]
        if self._host_resolver_rules:
            launch_args.append(f"--host-resolver-rules={self._host_resolver_rules}")
            launch_args.append("--ignore-certificate-errors")

        self._playwright_handle = await async_playwright().start()
        self._browser = await self._playwright_handle.chromium.launch(
            headless=self.headless,
            args=launch_args,
        )
        await self._init_pool()

        resolver = f"  resolver={self._host_resolver_rules}" if self._host_resolver_rules else ""
        print(
            f"[Browser] Chromium launched  engine={engine}  "
            f"pool={self._pool_size}{resolver}"
        )

    async def _shutdown_current(self) -> None:
        """Close all pool contexts, browser, and playwright handle."""
        for bs in self._slots:
            await bs.close()
        self._slots = []
        try:
            if self._context:
                await self._context.close()
                self._context = None
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
                self._browser = None
        except Exception:
            pass
        try:
            if self._playwright_handle:
                await self._playwright_handle.stop()
                self._playwright_handle = None
        except Exception:
            pass

    async def _new_context(
        self,
        proxy: Optional[dict] = None,
        *,
        ignore_https_errors: bool = False,
    ):
        """
        Create a hardened browser context with full anti-detection profile:
          - Rotated User-Agent (real Chrome/Windows/macOS strings)
          - Random US city geolocation + matching timezone
          - Matching viewport size
          - WebRTC leak blocking (both browser args + JS override)
          - Full navigator property masking via init script
          - Canvas + Audio fingerprint noise
        """
        city, lat, lon, timezone = self._session_location
        locale = self._fixed_locale or DEFAULT_CONFIG["locale"]   # always en-US

        kwargs: dict = dict(
            user_agent=self._session_ua,
            viewport=self._session_viewport,
            locale=locale,
            timezone_id=timezone,
            color_scheme="light",
            device_scale_factor=1,
            geolocation={"latitude": lat, "longitude": lon, "accuracy": 10},
            permissions=["geolocation"],
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-CH-UA-Platform": f'"{self._session_platform}"',
                "Sec-CH-UA": self._session_sec_ch_ua,
                "Sec-CH-UA-Mobile": "?0",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
            ignore_https_errors=ignore_https_errors,
        )

        if proxy:
            kwargs["proxy"] = proxy

        context = await self._browser.new_context(**kwargs)

        # Inject full stealth init script (WebRTC block, navigator masking,
        # canvas/audio noise, plugin spoofing) — runs before any page JS
        await context.add_init_script(_STEALTH_INIT_SCRIPT)
        await context.add_init_script(
            f"Object.defineProperty(navigator, 'platform', "
            f"{{ get: () => '{self._navigator_platform()}' }});"
        )

        return context
