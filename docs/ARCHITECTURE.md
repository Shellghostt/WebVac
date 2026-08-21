# WebVac — full system architecture

**Version:** 0.3.0  
**Related:** [Overview](OVERVIEW.md) · [Workflows](WORKFLOWS.md) · [Crawl](architecture/CRAWL.md) · [Auth](architecture/AUTH.md) · [Captcha](architecture/CAPTCHA.md) · [Proxy](architecture/PROXY_ORIGIN.md) · [Browser](architecture/BROWSER.md) · [Network](architecture/NETWORK.md) · [Data](architecture/DATA.md) · [VAPT](architecture/VAPT.md) · [Changelog](../CHANGELOG.md)

---

## 1. Purpose

WebVac is an **asyncio** scraper that drives real Chromium (via **Patchright**) to crawl JavaScript-heavy sites, optionally authenticate, rotate proxies, auto-solve widget CAPTCHAs (CapSolver), diagnose network failures, and export multi-format historical scan artifacts. An opt-in **VAPT** task shells out to De-Caffeinator for JS analysis.

---

## 2. System context

```mermaid
flowchart LR
  User["Operator"] --> Menu["run.py / webvac-menu"]
  User --> CLI["python -m webvac"]
  Menu --> CLI
  CLI --> Runtime["WebVac Runtime"]
  Runtime --> Target["Target website"]
  Runtime --> Proxy["Proxy pool"]
  Runtime --> CapAPI["CapSolver API"]
  Runtime --> Disk["scraped_data/"]
  Runtime --> Sess["sessions/"]
  Runtime -->|task=vapt| Decaf["decaffeinator/blob-unpacker"]
```

---

## 3. Layered architecture

```mermaid
flowchart TB
  subgraph entry [Entry]
    RunPy[run.py]
    Interactive[cli/interactive.py]
    Scraper[cli/scraper.py]
  end

  subgraph authLayer [Auth]
    AM[auth/manager.py]
    Wall[auth/wall.py]
    SessStore[auth/session_store.py]
  end

  subgraph captchaLayer [Captcha]
    CapMgr[captcha/manager.py]
    CapProv[providers/capsolver.py]
  end

  subgraph crawlLayer [Crawl]
    Crawler[core/crawler.py]
    Flow[core/page_scrape_flow.py]
    Pipe[core/pipeline.py]
  end

  subgraph browserLayer [Browser]
    BM[utils/browser.py]
    Pool[utils/browser_pool.py]
    Hum[utils/humanize.py]
    Det[utils/detection.py]
  end

  subgraph netLayer [Network policy]
    Proxy[utils/proxy.py]
    Robots[utils/robots.py]
    Origin[utils/origin_probe.py]
    NetL[utils/network_listener.py]
    NetD[utils/network_debug.py]
  end

  subgraph dataLayer [Data]
    Parse[data/html_parser.py]
    Rec[data/page_record.py]
    Store[data/storage.py]
    Scan[store/scan_session.py]
  end

  subgraph vaptLayer [VAPT]
    DecafMod[vapt/decaffeinator.py]
  end

  RunPy --> Interactive --> Scraper
  Scraper -->|vapt| DecafMod
  Scraper --> AM
  Scraper --> Crawler
  AM --> BM
  Crawler --> Flow
  Flow --> BM
  Flow --> Det
  Flow --> Wall
  Flow --> CapMgr
  CapMgr --> CapProv
  Flow --> NetL
  NetL --> NetD
  Crawler --> Proxy
  Crawler --> Robots
  Flow --> Parse --> Rec --> Pipe --> Store --> Scan
```

---

## 4. End-to-end runtime sequence (scrape)

```mermaid
sequenceDiagram
  participant U as Operator
  participant S as scraper.run
  participant P as ProxyManager
  participant B as BrowserManager
  participant A as AuthManager
  participant C as Crawler
  participant F as page_scrape_flow
  participant Cap as CapSolverManager
  participant St as Storage

  U->>S: CLI / menu argv
  S->>P: load proxies + optional health-check
  Note over P: all dead → continue direct IP
  S->>B: start N concurrent slots
  opt login or session restore
    S->>A: restore | login
    A->>B: broadcast storage_state
  end
  S->>C: scrape_single | scrape_site
  loop each URL batch
    C->>F: run_page_scrape(url, slot)
    F->>B: new_page + warmup + goto
    F->>A: auth-wall check first
    alt bot detected
      F->>Cap: try_solve_on_page
      Cap-->>F: inject / reload or fail
      F->>B: stealth retry / evasion
    end
    F->>F: consent + humanize + scroll + collect
    F-->>C: page record
  end
  S->>St: save formats + mark completed_at
  S->>B: stop
```

---

## 5. Task split: scrape vs VAPT

```mermaid
flowchart TD
  Start[scraper.run] --> Task{args.task}
  Task -->|scrape default| ScrapePath[Proxy Browser Auth Crawler Storage]
  Task -->|vapt| VaptPath[ScanSession + subprocess De-Caffeinator]
  ScrapePath --> Artifacts[scrape/ network/ assets/ meta/]
  VaptPath --> Artifacts2[analysis/decaffeinator/ + meta/]
```

| Task | Browser crawl? | Primary output |
|------|----------------|----------------|
| `scrape` (default) | Yes | `scrape/data.json`, `report.html`, … |
| `vapt` | No (De-Caffeinator may use Playwright internally) | `analysis/decaffeinator/` |

---

## 6. Package map

| Package / path | Responsibility |
|----------------|----------------|
| `run.py` | Thin shim → interactive menu |
| `cli/scraper.py` | CLI parser, doctor, scrape/VAPT orchestration |
| `cli/interactive.py` | Menu UX → argv builder |
| `core/crawler.py` | Single / BFS crawl, session init, retries orchestration |
| `core/page_scrape_flow.py` | Per-URL goto → wall → bot → captcha → collect |
| `core/pipeline.py` | Optional user post-processing hooks |
| `auth/` | AuthManager, profiles, sessions, MFA, walls |
| `captcha/` | CapSolver detect / extract / solve / inject |
| `utils/` | Browser, proxy, robots, detection, humanize, network, screenshots, assets, consent, origin |
| `data/` | HTML parse, page records, multi-format storage |
| `store/` | Scan folder layout + `meta.json` |
| `models/` | `ScanMetadata`, `TargetMetadata`, origin models |
| `vapt/` | De-Caffeinator launcher |
| `config/` | `DEFAULT_CONFIG` |
| `decaffeinator/` | Git submodule (tool at `blob-unpacker/`) |

---

## 7. Critical separation: auth wall vs bot block

```mermaid
flowchart TD
  Page[Loaded page] --> Wall{is_auth_wall?}
  Wall -->|yes| Policy[abort / skip / relogin]
  Policy --> NoBot[Do NOT mark proxy failure]
  Wall -->|no| Bot{is_bot_detected?}
  Bot -->|yes| Cap[CapSolver + stealth + evasion]
  Bot -->|no| Happy[consent → humanize → extract]
```

This separation is intentional and must not be collapsed. Details: [AUTH](architecture/AUTH.md) · [BROWSER](architecture/BROWSER.md).

---

## 8. Concurrency model

- One shared Chromium process.
- `concurrency = N` → N `BrowserSlot` contexts.
- Each slot can pin a different proxy + UA + optional geo/timezone identity.
- Auth login always uses **slot 0**; `storage_state` is broadcast to other slots.
- BFS takes batches of up to N URLs and `asyncio.gather`s them.

---

## 9. Artifact model

Every scrape or VAPT run creates a **scan session**:

```text
scraped_data/<domain>_<target8>/scans/<timestamp>_<scan8>/
  scrape/ | network/ | analysis/ | assets/ | meta/
```

See [SCAN_LAYOUT.md](SCAN_LAYOUT.md).

---

## 10. Status matrix (product)

| Area | Status | Notes |
|------|--------|-------|
| Dynamic crawl (Patchright) | Stable | Primary path |
| Lightweight aiohttp engine | Supported | Falls back to dynamic on bot block |
| Auth login / session / TOTP | Stable | Patchright-only |
| CapSolver widgets | Stable | Default on when key present |
| Managed CF interstitial | Partial | Detected; CapSolver usually cannot clear |
| Proxy playbooks | Stable | residential / datacenter / none |
| Network debug dumps | Stable | RUM beacons ignored |
| De-Caffeinator VAPT | Stable | Submodule required |
| In-tree VAPT analyzers | Removed | Use De-Caffeinator instead |

---

## 11. Configuration surface

Defaults live in `webvac/config/config.py`. CLI flags overlay into `session_config` inside `scraper.run`. Full map: [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md).
