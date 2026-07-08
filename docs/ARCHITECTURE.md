# WebVac — Architecture Reference

## Overview

**WebVac** is a Python asyncio web scraper that drives real Chromium browsers (via Patchright) to crawl JavaScript-heavy sites, extract structured page data, and export multi-format reports. It includes an optional VAPT/recon pipeline (collectors, analyzers, findings) that is **built but disabled** in the default configuration (`vapt_enabled: False`).

**Elevator pitch:** A stealth browser crawler with proxy rotation, CDN origin bypass, concurrent context pools, and rich HTML/JSON/CSV output — with a security-recon layer ready to re-enable later.

---

## System Diagram

See **`docs/webvac-architecture-one-page.html`** (open in browser → Print → Save as PDF) or **`docs/webvac-architecture.pdf`** if generated.

---

## Layered Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ENTRY                                                                  │
│  run.py (menu)  →  core/scraper.py (CLI orchestrator)                   │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│  CRAWL ENGINE                                                           │
│  core/crawler.py (BFS)  →  core/page_scrape_flow.py (per-page logic)    │
│  scope/scope_manager.py  ·  core/pipeline.py (user hooks)                 │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ BROWSER       │         │ PROXY / ORIGIN  │         │ DATA            │
│ browser.py    │         │ proxy.py        │         │ html_parser.py  │
│ browser_pool  │         │ cf_hero.py      │         │ page_record.py  │
│ detection.py  │         │ origin_probe.py │         │ storage.py      │
│ screenshot.py │         │ robots.py       │         │ scan_session.py │
└───────────────┘         └─────────────────┘         └─────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  VAPT PIPELINE (optional — disabled by default)                         │
│  collectors/ → analyzers/ → findings/ → core/runner.py → recon reports  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Crawl Flow

1. **CLI / menu** parses args (`--url`, `--mode`, `--depth`, `--concurrency`, proxies, etc.).
2. **ProxyManager** loads proxies, benchmarks latency, picks initial per-slot assignments.
3. **BrowserManager** launches Chromium with N isolated contexts (one per concurrent worker).
4. **Crawler** runs BFS from seed URL:
   - Respects robots.txt, scope, depth, and page limits.
   - Batches up to `concurrency` pages in parallel via `asyncio.gather`.
5. **page_scrape_flow** for each URL:
   - Polite delay → `goto` → challenge wait → bot detection.
   - On block: stealth retry → CF-Hero auto origin → evasion sequence → optional CAPTCHA prompt.
   - On success: scroll, extract HTML, build page record, follow internal links.
6. **Storage** writes JSON, CSV, HTML report, optional diffs vs prior scan.
7. **AssetDownloader** fetches PDFs and source maps discovered during crawl.

---

## Module Reference

### Entry & config

| Module | Purpose |
|--------|---------|
| `run.py` | Interactive menu launcher |
| `core/scraper.py` | Main CLI: setup, crawl, persist |
| `config/config.py` | Default settings |
| `config/scan_profiles.py` | VAPT profile presets |

### Crawl engine

| Module | Purpose |
|--------|---------|
| `core/crawler.py` | BFS crawler, session init, slot proxies |
| `core/page_scrape_flow.py` | Dynamic per-page scrape, retries, evasion |
| `core/pipeline.py` | User `process_item()` data hooks |
| `scope/scope_manager.py` | Domain/URL scope and limits |
| `graph/endpoint_graph.py` | Page link graph (VAPT) |

### Browser & anti-block

| Module | Purpose |
|--------|---------|
| `utils/browser.py` | Patchright lifecycle, stealth, CAPTCHA UI |
| `utils/browser_pool.py` | Per-slot browser contexts |
| `utils/detection.py` | WAF/challenge detection |
| `utils/proxy.py` | Proxy pool, rotation, cool-down |
| `utils/cf_hero.py` | CF-Hero CLI integration |
| `utils/origin_probe.py` | Host-header origin validation |
| `models/origin.py` | OriginTarget dataclass |
| `utils/robots.py` | robots.txt handling |
| `utils/screenshot.py` | Block-page screenshots |

### Data & output

| Module | Purpose |
|--------|---------|
| `data/html_parser.py` | HTML → structured dict |
| `data/page_record.py` | Page record builder |
| `data/storage.py` | JSON, CSV, HTML, SQLite, diffs |
| `store/scan_session.py` | Historical scan folder layout |
| `utils/asset_downloader.py` | PDF & source map downloads |
| `models/scan.py` | Scan/target metadata |

### Auth

| Module | Purpose |
|--------|---------|
| `auth/auth.py` | Login, session cookie save/restore |

### VAPT (disabled by default)

| Module | Purpose |
|--------|---------|
| `collectors/` | HTTP, HTML, JS, network, storage capture |
| `analyzers/` | Headers, cookies, OAuth, GraphQL, tech, etc. |
| `findings/` | Security rule engine |
| `active/` | Active file/GraphQL/swagger probes |
| `core/runner.py` | Post-crawl analysis orchestrator |
| `store/artifact_store.py` | Per-page artifact store |

---

## Output Layout

```
scraped_data/
  <domain>_<target_id>/
    scans/
      <YYYYMMDD_HHMMSS>_<scan_id>/
        scrape/       data.json, data.csv, report.html
        recon/        findings (VAPT)
        artifacts/    raw collector output
        assets/       pdfs/, sourcemaps/, screenshots/
        meta/         session.json, meta.json
    diffs/            diff vs previous scan
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Real browser (Patchright) | Renders SPAs, survives JS challenges |
| Context pool per concurrency | Safe parallel crawl with isolated proxies |
| Pinned proxy identity | UA + Sec-CH-UA match proxy fingerprint |
| Layered bot handling | Challenge wait → retry → CF-Hero → evasion → CAPTCHA |
| BFS + scope manager | Predictable crawl with guardrails |
| Dual scrape/VAPT paths | Same crawler; VAPT toggled via config |
| Versioned scan sessions | Historical runs + diffs |

---

## Current Status

| Feature | Status |
|---------|--------|
| Single-page & BFS crawl | ✅ Active |
| Proxy rotation & health-check | ✅ Active |
| Concurrent context pool | ✅ Active |
| CF-Hero / origin bypass | ✅ Active |
| JSON / CSV / HTML output | ✅ Active |
| PDF & source map download | ✅ Active |
| Login + session cookies | ✅ Active |
| VAPT pipeline | ⏸ Disabled |

---

## Tech Stack

Python 3.12+ · asyncio · Patchright · aiohttp · BeautifulSoup/lxml · tqdm · colorama

---

## Quick Start

```bash
python run.py                                          # interactive menu
python -m core.scraper --url https://example.com --mode single
python -m core.scraper --url https://example.com --mode crawl --depth 3 --max-pages 50 --concurrency 2
```

---

## Generate PDF Diagram

```bash
python scripts/generate_architecture_pdf.py
```

Or open `docs/webvac-architecture-one-page.html` in a browser and use **Print → Save as PDF** (landscape, fit to one page).
