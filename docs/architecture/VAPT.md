# VAPT / Recon Pipeline Architecture

**Parent:** [Full System Architecture](../ARCHITECTURE.md)  
**Status:** Implemented in codebase · **default OFF** (`vapt_enabled: False`) · **`PipelineRunner` not wired into CLI scrape path yet**

**Code:** `collectors/`, `analyzers/`, `findings/`, `active/`, `intelligence/`, `graph/`, `core/runner.py`, `config/scan_profiles.py`

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
```

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
  IF --> ProbeRes[ProbeResult]
  GQ --> ProbeRes
  ProbeRes --> FE
```

Rules modules under `findings/rules/`: header, secret, cookie, storage, network, cloud, auth, infra.

**Not implemented:** `api_fuzzer` (mentioned in older design notes only).

---

## 6. Profiles

`config/scan_profiles.py` presets: `quick`, `standard`, `deep`, `bugbounty`.

Each profile toggles collectors/analyzers/active flags. Intended use:

```python
PipelineRunner.from_profile("standard", ...)
```

There is **no `--profile` CLI flag on scraper yet** — wiring is a future task.

---

## 7. Intended vs current scrape path

```mermaid
flowchart TB
  subgraph today [Today — default]
    A[scraper.run] --> B[Crawler HTML parse]
    B --> C[Storage scrape/]
  end

  subgraph future [When VAPT wired]
    A2[scraper.run] --> B2[Crawler + collectors]
    B2 --> R[PipelineRunner]
    R --> D[Storage scrape/ + recon/ + artifacts/]
  end
```

| Concern | Today |
|---------|-------|
| `vapt_enabled` default | `False` |
| Collectors during crawl | Only if flag flipped in config |
| `PipelineRunner` after crawl | Not called from `scraper.run` |
| Recon HTML/JSON reports | Writer exists (`data/recon_report.py`) |

---

## 8. Shared stores

| Store | Role |
|-------|------|
| `ArtifactStore` | Typed raw evidence |
| `IntelligenceStore` | Deduped observations |
| `EndpointGraph` | URL/endpoint tree |
| `ScopeManager` | Scope + visit stats for recon context |

`AnalysisContext` bundles these for every analyzer call.
