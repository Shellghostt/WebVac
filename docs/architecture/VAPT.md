# VAPT / Recon Pipeline Architecture

**Parent:** [Full System Architecture](../ARCHITECTURE.md)  
**Status:** Implemented · **default OFF** (`vapt_enabled: False`) · enable with `--vapt` or `--profile {quick,standard,deep,bugbounty}`

**Code:** `collectors/`, `analyzers/`, `findings/`, `active/`, `intelligence/`, `graph/`, `core/runner.py`, `config/scan_profiles.py`, CLI in `cli/scraper.py`

---

## 1. Goals

When enabled, enrich a crawl with:

1. Structured **artifacts** per page/session  
2. **Intelligence** observations from analyzers  
3. Optional **active probes**  
4. Rule-based **findings** + recon reports  

Must never change default scrape behavior while disabled.

---

## 2. Pipeline overview

```mermaid
flowchart LR
  Crawl[Crawler pages] --> Coll[CollectorEngine]
  Coll --> Art[ArtifactStore]
  Art --> Graph[EndpointGraph]
  Art --> Ana[AnalyzerEngine]
  Ana --> Intel[IntelligenceStore]
  Intel --> Probe[ProbeRunner optional]
  Probe --> Find[FindingsEngine]
  Intel --> Find
  Find --> Report[ReconReportWriter / Storage]
```

Orchestrator: `core/runner.py` → `PipelineRunner` (`run_analysis`, `persist_session`, `from_profile`).

---

## 3. Collectors

Plugin discovery via `collectors/plugins.py` → `CollectorEngine`.

| Collector | Level | Captures |
|-----------|-------|----------|
| `HttpCollector` | page | Status, headers, redirects |
| `HtmlCollector` | page | DOM, forms, links → graph edges |
| `NetworkCollector` | page (live attach) | XHR/fetch traffic |
| `StorageCollector` | page | Cookies, local/sessionStorage |
| `JavascriptCollector` | **session** | External JS + source maps |

```mermaid
sequenceDiagram
  participant Flow as page_scrape_flow
  participant CE as CollectorEngine
  participant AS as ArtifactStore
  participant EG as EndpointGraph

  Flow->>CE: collect_page(page, url)
  CE->>AS: put HTTP/HTML/Network/Storage artifacts
  CE->>EG: add_edge from discovered links
  Note over CE: after crawl
  CE->>AS: collect_session JavascriptCollector
```

---

## 4. Analyzers

`AnalyzerEngine.run(AnalysisContext)` with `ctx.is_analyzer_enabled(name)`.

```mermaid
flowchart TB
  Ctx[AnalysisContext] --> H[headers]
  Ctx --> C[cookies]
  Ctx --> A[auth]
  Ctx --> S[storage]
  Ctx --> J[js]
  Ctx --> SM[sourcemap]
  Ctx --> N[network]
  Ctx --> T[tech]
  Ctx --> G[graphql]
  Ctx --> O[oauth]
  Ctx --> CL[cloud]
  Ctx --> HTML[html]
  H --> Intel[IntelligenceItem list]
  C --> Intel
  A --> Intel
  S --> Intel
  J --> Intel
  SM --> Intel
  N --> Intel
  T --> Intel
  G --> Intel
  O --> Intel
  CL --> Intel
  HTML --> Intel
```

**HTML analyzer:** forms, hidden inputs, file uploads, interesting comments, admin/auth links.

**Auth analyzer note:** default-credential panel fingerprints always available when auth analyzer enabled; **cookie-flag findings** additionally require `vapt_enabled` (scrape-safe login warnings live in `auth/cookie_audit.py` instead).

---

## 5. Findings & active probes

```mermaid
flowchart TD
  Intel[IntelligenceStore] --> FE[FindingsEngine]
  Rules[ALL_RULES header/secret/cookie/…] --> FE
  FE --> Findings[Finding list]

  AR{active_recon?} -->|yes| PR[ProbeRunner]
  PR --> IF[interesting_files]
  PR --> GQ[graphql_probe]
  PR --> HM[http_methods OPTIONS]
  IF --> ProbeRes[ProbeResult]
  GQ --> ProbeRes
  HM --> ProbeRes
  ProbeRes --> FE
```

Rules modules under `findings/rules/`: header, secret, cookie, storage, network, cloud, auth, infra.

**Not implemented:** `api_fuzzer` (mentioned in older design notes only).

---

## 6. Profiles

`config/scan_profiles.py` presets: `quick`, `standard`, `deep`, `bugbounty`.

```bash
python -m webvac --url https://example.com --mode crawl --profile standard
python -m webvac --url https://example.com --mode single --vapt
python -m webvac --url https://example.com --mode crawl --profile deep   # includes active recon
python -m webvac --url https://example.com --mode crawl --vapt --active-recon
```

`--profile` / `--active-recon` imply VAPT. Default scrape path stays unchanged without these flags.

---

## 7. Scrape path with optional VAPT

```mermaid
flowchart TB
  subgraph today [Default scrape]
    A[scraper.run] --> B[Crawler HTML parse]
    B --> C[Storage scrape/]
  end

  subgraph vapt [With --vapt / --profile]
    A2[scraper.run] --> B2[Crawler + collectors]
    B2 --> R[PipelineRunner.run_analysis]
    R --> D[Storage scrape/ + recon/ + artifacts/]
  end
```

| Concern | Today |
|---------|-------|
| `vapt_enabled` default | `False` |
| Enable | `--vapt`, `--profile`, or `--active-recon` |
| Collectors during crawl | When `vapt_enabled` |
| `PipelineRunner` after crawl | Called from `cli/scraper.py` |
| Recon HTML/JSON reports | Via `Storage.save(..., recon=)` |

---

## 8. Shared stores

| Store | Role |
|-------|------|
| `ArtifactStore` | Typed raw evidence |
| `IntelligenceStore` | Deduped observations |
| `EndpointGraph` | URL/endpoint tree |
| `ScopeManager` | Scope + visit stats for recon context |

`AnalysisContext` bundles these for every analyzer call.
