# WebVac → BAS MCP Agent (Linux Remote) — Deep Dive

**Audience:** product/engineering planning  
**Target:** Breach & Attack Simulation orchestrator calling WebVac over MCP  
**Runtime:** headless Linux remote server  

---

## 1. Where WebVac stands today

| Layer | Maturity | Fit for BAS |
|-------|----------|-------------|
| Patchright crawl + concurrency | Strong | **Keep — core** |
| AuthManager / sessions / MFA-TOTP | Strong | **Keep — core** (server-safe subset) |
| Proxies / robots / anti-bot | Strong | **Keep**, tighten defaults |
| Page JSON / scan sessions | Strong | **Keep JSON**; demote pretty exports |
| VAPT collectors → analyzers → findings | Built | **Essential — currently unwired** |
| Interactive `run.py` / CAPTCHA ENTER | Strong as desktop UX | **Remove from server path** |
| OAuth bootstrap (optional) | Useful locally | **Demote** for remote BAS |
| Manual origin IP bypass | Supported | **Gate hard** (ethics/scope) |

**Biggest gap:** the VAPT stack exists (`collectors/`, `analyzers/`, `findings/`, `core/runner.py`) but `vapt_enabled` defaults to `False` and `PipelineRunner` is **never called** from `webvac/cli/scraper.py`. MCP would wrap a scraper, not a BAS recon engine, until that is wired.

---

## 2. Features you NEED for BAS via MCP

### Must-have (BAS signal path)

1. **Authenticated crawl** — login or restore `storage_state`, pin proxy, auth-check URL  
2. **Endpoint discovery** — crawl links + (VAPT) HTML/JS/network collectors + `EndpointGraph`  
3. **Session/cookie intelligence** — cookies + storage artifacts (values redacted in MCP responses)  
4. **Tech fingerprinting** — headers / JS / tech analyzers  
5. **Findings engine** — rule-based `Finding` objects with severity  
6. **Structured JSON contracts** — findings, graph, tech profile, job status (not HTML reports)  
7. **Headless, non-interactive** — no menus, no ENTER, no OTP prompts without TOTP secret  
8. **Job lifecycle** — start / status / cancel / partial results (MCP-friendly)  
9. **Scope & caps** — max_pages, depth, concurrency, wall-clock timeout, robots policy  
10. **Scan profiles** — `quick` / `standard` / `deep` / `bugbounty` from `config/scan_profiles.py`  
11. **Fail-closed auth** — failed login or auth-wall → job error (not “continue anyway” / silent skip)

### Nice-to-have (keep, gated)

- Proxy pools for engagement networks  
- Active probes (`interesting_files`, GraphQL introspection) — **opt-in only**  
- Screenshots of block pages — forensic evidence mode only  
- Lightweight HTTP preflight before browser crawl  

### Not needed for BAS agent (desktop product features)

- Interactive menu, colorama banners, tqdm as primary UX  
- Multi-format “marketing” reports (CSV/HTML/MD/SQLite) as default  
- Historical scan diffs (orchestrator can own trending)  
- PDF mass-download  
- Manual OAuth bootstrap / CAPTCHA solve on the server

---

## 3. What to REMOVE or demote on the Linux BAS image

| Item | Action | Why |
|------|--------|-----|
| `run.py` as entrypoint | **Demote** — local only | Menus + subprocess; useless for MCP |
| CAPTCHA `input()` / OTP `input()` | **Disable on server** | Hangs headless workers |
| `--auth-bootstrap` | **Offline workstation only** | Needs display + human |
| Default PDF download | **Off** | I/O noise; rare BAS value |
| Diff generation | **Off / optional** | Orchestrator owns history |
| HTML/CSV/MD reports as default | **JSON only** for MCP jobs | Smaller, machine-readable |
| `tqdm` / colorama in agent mode | **Replace with logging** | Non-TTY / JSON logs |
| Manual `--origin-ip` only | **Require explicit permission** | Scope/ethics risk |
| Unlimited crawl (`max_pages` omit) | **Forbid in MCP** | Accidental DoS |
| Default-cred auto-login | **Never** | Intelligence only, never exploit |

Do **not** delete VAPT code — wire it. Demote UX/export features, don’t gut recon.

---

## 4. What to CHANGE for Linux remote + MCP

### 4.1 Runtime / deploy

- Install Patchright Chromium + Linux libs (`libnss3`, `libatk-bridge2.0`, `libgbm`, fonts, etc.).
- Prefer **true headless** (`headless=True`). Avoid Xvfb unless a rare anti-bot path requires headed Chrome.
- Containerize: pinned Python, browser, resource limits (CPU/RAM), no secrets in image layers.
- Mint OAuth/CAPTCHA sessions on a **workstation** → upload encrypted `storage_state` to the agent (`WEBVAC_SESSION_KEY`).

### 4.2 Auth defaults for BAS

| Setting | Desktop scraper today | BAS server should |
|---------|----------------------|-------------------|
| `on_auth_wall` | `skip` | **`abort`** |
| Login failure | warn + continue | **fail job** |
| CAPTCHA prompt | optional | **always off** |
| OTP | prompt / TOTP | **TOTP only**; else `mfa_required` error |
| Bootstrap | supported | **not on server** |

### 4.3 Wire VAPT (critical)

After crawl:

```text
Crawler (vapt_enabled=True)
  → ArtifactStore filled by collectors
  → PipelineRunner.run_analysis(...)
  → findings + intelligence + endpoint_graph
  → persist recon JSON
```

Expose CLI/API: `--vapt` / `--profile standard|deep|bugbounty`.

### 4.4 Library API (MCP wraps this — not CLI subprocess)

```text
start_job(config) -> job_id
get_status(job_id) -> phase, pages_done, errors
cancel_job(job_id)
get_result(job_id) -> {findings, endpoints, tech, session_meta, pages?}
```

Cooperative cancel (`asyncio.Event`), structured logging, redacted secrets.

### 4.5 Fingerprints

Host is Linux, but browser UA can stay Windows/Chrome if evasion needs it — that’s fine. Prefer **stable, policy-controlled** identity per engagement rather than aggressive geo rotation for BAS fidelity/reproducibility.

---

## 5. Suggested MCP tool surface

| Tool | Purpose |
|------|---------|
| `webvac_list_profiles` | Expose scan profiles |
| `webvac_auth_login` | Non-interactive login → session ref |
| `webvac_auth_restore` | Restore + auth-check |
| `webvac_start_scan` | Crawl/recon job (profile, caps, auth session) |
| `webvac_scan_status` | Progress / phase / errors |
| `webvac_cancel_scan` | Cooperative cancel |
| `webvac_get_findings` | Severity-filtered findings |
| `webvac_get_endpoints` | Graph + API URLs |
| `webvac_get_tech_profile` | Stack fingerprint |
| `webvac_get_session_meta` | Cookie flags / auth state (no raw secrets by default) |
| `webvac_origin_probe` | **Gated** — requires engagement authorization token |

Typical BAS flow:

```text
auth_restore | auth_login
  → start_scan(profile=standard, on_auth_wall=abort, active_recon=false|true)
  → poll status
  → get_findings + get_endpoints + get_tech_profile
```

---

## 6. Risks (must treat as product policy)

1. **Authorization** — BAS must only target in-scope assets; WebVac won’t know engagement contracts.  
2. **Active probes** — intrusive GETs (`/.git`, `/.env`, swagger); opt-in + logged.  
3. **Origin IP (`--origin-ip`)** — can bypass CDN/WAF; manual only; require explicit permission.  
4. **Auth-wall skip** — under-reports authenticated surface; wrong for simulations.  
5. **Resource abuse** — high concurrency / unlimited pages can look like DoS.  
6. **Secrets** — never log passwords; encrypt sessions; inject via env/secret store.

---

## 7. Priority roadmap

| Priority | Work |
|----------|------|
| P0 | Wire `PipelineRunner` + `--vapt` / `--profile`; JSON recon output |
| P0 | Library job API: start/status/cancel/result |
| P0 | Headless-safe auth: no prompts; abort on wall; fail hard on login fail |
| P1 | MCP server package wrapping job API |
| P1 | Linux Docker image + Patchright deps |
| P1 | Default JSON-only; PDFs/diffs/screenshots opt-in |
| P2 | Gate manual origin IP + active probes behind policy flags |
| P2 | Demote bootstrap from server image |
| P2 | Replace print/tqdm with structured logging |
| P3 | Keep `run.py` as optional local operator tool only |

---

## 8. One-line strategy

**Keep** the crawl + AuthManager + VAPT brain.  
**Wire** findings into a job API.  
**Strip** interactive human UX from the server path.  
**Expose** that API as MCP tools to the BAS orchestrator.
