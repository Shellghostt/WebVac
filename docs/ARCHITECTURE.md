# WebVac — Full System Architecture

**Last updated:** 2026-07-27  
**Related:** [Authentication](architecture/AUTH.md) · [Crawl & Browser](architecture/CRAWL.md) · [Data & Storage](architecture/DATA.md) · [Proxy & Origin](architecture/PROXY_ORIGIN.md) · [VAPT Pipeline](architecture/VAPT.md) · [Changes](CHANGES_AND_IMPROVEMENTS.md)

---

## 1. Purpose

WebVac is an **asyncio** scraper that drives real Chromium (via **Patchright**) to crawl JavaScript-heavy sites, optionally authenticate, rotate proxies, bypass CDN-to-origin when authorized, and export multi-format historical scan artifacts.

A full **VAPT/recon stack** (collectors → analyzers → findings → active probes) is implemented in-tree but **disabled by default** (`vapt_enabled: False`) and not yet hooked into the main CLI scrape path.

---

## 2. High-level system context

```mermaid
flowchart LR
  User["Operator"] --> Run["run.py menu"]
  User --> CLI["python -m core.scraper"]
  Run --> CLI
  CLI --> WebVac["WebVac Runtime"]
  WebVac --> Target["Target Website"]
  WebVac --> Proxy["Proxy Pool"]
  WebVac --> Disk["scraped_data/"]
  WebVac --> Sess["sessions/ storage_state"]
  WebVac -.->|optional| CFHero["CF-Hero binary"]
```

---

## 3. Layered architecture

```mermaid
flowchart TB
  subgraph entry [Entry Layer]
    RunPy[run.py]
    Scraper[core/scraper.py]
  end

  subgraph authLayer [Auth Layer]
    AM[auth/manager.py]
    Engines[auth engines + session]
  end

  subgraph crawlLayer [Crawl Layer]
    Crawler[core/crawler.py]
    Flow[core/page_scrape_flow.py]
    Scope[scope/scope_manager.py]
    Pipe[core/pipeline.py]
  end

  subgraph browserLayer [Browser & Resilience]
    BM[utils/browser.py]
    Pool[utils/browser_pool.py]
    Det[utils/detection.py]
    Cap[utils/screenshot.py]
  end

  subgraph netLayer [Network Policy]
    Proxy[utils/proxy.py]
    Robots[utils/robots.py]
    Origin[utils/origin_probe.py]
    CF[utils/cf_hero.py]
  end

  subgraph dataLayer [Data Layer]
    Parse[data/html_parser.py]
    Rec[data/page_record.py]
    Store[data/storage.py]
    Scan[store/scan_session.py]
    Assets[utils/asset_downloader.py]
  end

  subgraph vaptLayer [VAPT Overlay — default OFF]
    Coll[collectors/]
    Ana[analyzers/]
    Find[findings/]
    Active[active/]
    Runner[core/runner.py]
  end

  RunPy --> Scraper
  Scraper --> AM
  Scraper --> Crawler
  AM --> Engines
  AM --> BM
  Crawler --> Flow
  Crawler --> Scope
  Flow --> BM
  Flow --> Det
  Flow --> AM
  Crawler --> Proxy
  Crawler --> Robots
  Crawler --> Origin
  Crawler --> CF
  Flow --> Parse
  Parse --> Rec
  Rec --> Pipe
  Pipe --> Store
  Store --> Scan
  Crawler --> Assets
  Crawler -.-> Coll
  Coll -.-> Ana
  Ana -.-> Find
  Find -.-> Active
  Runner -.-> Store
```

---

## 4. End-to-end runtime sequence

```mermaid
sequenceDiagram
  participant U as Operator
  participant S as scraper.run
  participant P as ProxyManager
  participant B as BrowserManager
  participant A as AuthManager
  participant C as Crawler
  participant F as page_scrape_flow
  participant St as Storage

  U->>S: CLI / run.py args
  S->>P: load + optional benchmark
  S->>B: start N slots
  opt login / session / bootstrap
    S->>A: restore | login | bootstrap
    A->>B: broadcast storage_state
  end
  S->>C: scrape_single | scrape_site
  loop each URL batch
    C->>F: run_page_scrape(url, slot)
    F->>B: new_page + goto
    F->>A: auth-wall check if authed
    F-->>C: page record dict
  end
  S->>St: save formats + diffs
  S->>B: stop
```

---

## 5. Package map

| Package | Responsibility |
|---------|----------------|
| `run.py` | Interactive launcher → builds argv → invokes scraper |
| `core/` | CLI orchestration, BFS crawler, per-page flow, user pipelines, VAPT runner |
| `auth/` | Login, sessions, MFA, walls, profiles |
| `utils/` | Browser pool, proxies, robots, detection, CF-Hero, screenshots, assets |
| `data/` | HTML parse, page records, multi-format export, recon report writer |
| `config/` | Defaults + VAPT scan profiles |
| `scope/` | Domain / depth / URL allow-deny |
| `store/` | Scan folder layout + artifact store |
| `models/` | Typed artifacts, findings, intelligence, scan metadata |
| `collectors/` | VAPT page/session collectors (plugin discovery) |
| `analyzers/` | VAPT intelligence extractors |
| `findings/` | Rule engine → security findings |
| `active/` | Opt-in active probes |
| `intelligence/` | Deduped observation store |
| `graph/` | Endpoint parent/child graph |
| `tests/` | Unit + e2e coverage |
| `docs/` | Architecture & change docs |

---

## 6. Two pipelines (do not confuse)

| Pipeline | Module | Status |
|----------|--------|--------|
| **User scrape pipeline** | `core/pipeline.py` (`PipelineManager`) | **Active** — `--pipeline-file` mutates page dicts before save |
| **VAPT recon pipeline** | `core/runner.py` (`PipelineRunner`) | **Built, default OFF, not CLI-wired** |

---

## 7. Configuration spine

```mermaid
flowchart LR
  Defaults["config/config.py DEFAULT_CONFIG"] --> Session["session_config dict"]
  CLI["argparse in scraper"] --> Session
  Profiles["scan_profiles.py"] -.->|VAPT only| Session
  Session --> Crawler
  Session --> Collectors
  Session --> Analyzers
```

Important defaults:

- `vapt_enabled: False`
- Scrape formats: `json,csv,html`
- Crawl respects robots unless `--no-robots`
- Auth wall policy default: `skip`

---

## 8. On-disk output model

```text
scraped_data/
  <domain>_<target_id>/
    scans/
      <timestamp>_<scan_id>/
        scrape/       # data.json, data.csv, report.html, …
        recon/        # VAPT (when enabled + wired)
        artifacts/    # VAPT raw artifacts
        assets/
          pdfs/
          sourcemaps/
          screenshots/
        meta/
          meta.json
          session.json
    diffs/
      diff_<scan>.json | .md
```

Sessions (auth) live separately under `sessions/` (gitignored).

---

## 9. Concurrency model

```mermaid
flowchart TB
  Seed[Seed URL] --> Queue[BFS deque]
  Queue --> Batch["Batch size = concurrency"]
  Batch --> S0[Slot 0 context]
  Batch --> S1[Slot 1 context]
  Batch --> SN[Slot N context]
  S0 --> Recs[Page records]
  S1 --> Recs
  SN --> Recs
  Recs --> Visited[visited + enqueue internal links]
  Visited --> Queue
```

Each **slot** = isolated browser context with:

- Own proxy (optional)
- Own UA / Client Hints identity
- Shared auth `storage_state` after login (broadcast)

Login always uses **slot 0**; when authenticated, slot-0 proxy is pinned (no voluntary rotate).

---

## 10. Feature status matrix

| Feature | Status |
|---------|--------|
| Single-page + BFS crawl | Active |
| Concurrent browser slots | Active |
| Proxy pool + health + sticky | Active |
| Robots + delays | Active |
| AuthManager (Patchright / Nodriver) | Active |
| Session restore / TTL / Fernet | Active |
| Mid-crawl auth-wall policy | Active |
| CF-Hero / origin Host bypass | Active |
| Bot detection + CAPTCHA prompt | Active |
| Multi-format export + diffs | Active |
| PDF / sourcemap download | Active |
| User `PipelineManager` | Active |
| Collectors / analyzers / findings | Implemented, default OFF |
| `PipelineRunner` in CLI | Not wired |
| `api_fuzzer` | Not implemented |

---

## 11. Design principles

1. **Scrape spine first** — browser crawl + page records must work without VAPT.
2. **Auth is a facade** — engines stay swappable behind `AuthManager`.
3. **Slot isolation** — concurrency via contexts, not tabs in one profile.
4. **Additive CLI** — new flags never break existing `--login` / `--session-file`.
5. **Security gated** — VAPT and active probes stay opt-in.
6. **Historical scans** — every run is a versioned session with optional diffs.

---

## 12. Module architecture index

| Doc | Focus |
|-----|-------|
| [architecture/AUTH.md](architecture/AUTH.md) | Login, sessions, MFA, walls, bootstrap |
| [architecture/CRAWL.md](architecture/CRAWL.md) | Crawler, page flow, browser pool |
| [architecture/DATA.md](architecture/DATA.md) | Parse, records, storage, scan layout |
| [architecture/PROXY_ORIGIN.md](architecture/PROXY_ORIGIN.md) | Proxies, robots, CF-Hero, origin |
| [architecture/VAPT.md](architecture/VAPT.md) | Collectors → analyzers → findings |

Open the visual one-pager: [`webvac-architecture-one-page.html`](webvac-architecture-one-page.html).
