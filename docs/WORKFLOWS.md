# WebVac workflows

End-to-end operator and runtime workflows with diagrams. For layer internals see [ARCHITECTURE.md](ARCHITECTURE.md) and the `architecture/` deep dives.

---

## 1. First-time setup

```mermaid
flowchart TD
  A[Clone repo] --> B[git submodule update --init --recursive]
  B --> C[Create venv + pip install -e .]
  C --> D[python -m patchright install]
  D --> E[Copy examples → local secrets]
  E --> F[python -m webvac --doctor]
  F --> G{OK?}
  G -->|yes| H[First scrape or VAPT]
  G -->|no| I[Fix Patchright / paths / Node for VAPT]
```

Local (gitignored) files typically created:

| File | Purpose |
|------|---------|
| `proxies.txt` | Optional proxy pool |
| `capsolver.key` | CapSolver API key (enables solver by default) |
| `auth_creds.json` | Login credentials / profile |
| `sessions/*.json` | Saved `storage_state` |

---

## 2. Interactive menu workflow

```mermaid
flowchart TD
  Start[python run.py] --> Menu{Choice}
  Menu -->|1 Quick scrape| Single[Build --mode single argv]
  Menu -->|2 Site crawler| Crawl[Build --mode crawl argv]
  Menu -->|3 VAPT / JS analysis| Vapt[Build --task vapt argv]
  Menu -->|4 Scan library| List[List scraped_data sessions]
  Menu -->|5 Quit| End[Exit]
  Single --> Exec[Invoke webvac.cli.scraper]
  Crawl --> Exec
  Vapt --> Exec
```

Scrape wizard common steps: auth mode → URL/limits → formats (`json,html`) → robots bypass → proxies → headless → screenshots.

---

## 3. CLI scrape workflow

```mermaid
sequenceDiagram
  participant Op as Operator
  participant CLI as scraper.main
  participant Run as scraper.run
  participant Doc as --doctor optional

  Op->>CLI: python -m webvac --url ...
  alt --doctor
    CLI->>Doc: preflight and exit
  else normal
    CLI->>Run: asyncio.run(run(args))
    alt --task vapt
      Run->>Run: run_decaffeinator_task
    else scrape
      Run->>Run: proxies → browser → auth → crawl → save
    end
  end
```

### Typical commands

```bash
# Single page
python -m webvac --url https://example.com --mode single

# Site crawl
python -m webvac --url https://example.com --mode crawl --depth 3 --max-pages 50

# Authenticated crawl
python -m webvac --url https://example.com --mode crawl --login \
  --auth-profile auth_creds.json

# Session restore
python -m webvac --url https://example.com --session-file sessions/example_com_auth.json

# Disable CapSolver even if key exists
python -m webvac --url https://example.com --captcha-solver none

# VAPT
python -m webvac --task vapt --url https://example.com --vapt-profile deep
```

---

## 4. Per-page scrape workflow (critical path)

This is the heart of WebVac. Implemented in `webvac/core/page_scrape_flow.py`.

```mermaid
flowchart TD
  A[run_page_scrape] --> B[Consent URL rewrite]
  B --> C{URL is auth wall?}
  C -->|yes| D[Policy: abort / skip / relogin]
  C -->|no| E[Polite delay / robots wait]
  E --> F{engine lightweight?}
  F -->|yes| G[aiohttp / origin fetch]
  G -->|bot_blocked| H[Dynamic path]
  F -->|dynamic| H
  H --> I[new_page + network listen + captcha watch]
  I --> J[Host warmup once]
  J --> K[page.goto]
  K --> L{Live auth wall?}
  L -->|yes| D
  L -->|no| M[_after_goto: challenge wait + bot check]
  M --> N{Bot?}
  N -->|yes| O[CapSolver try]
  O -->|solved| P[Consent + humanize + scroll + collect]
  O -->|fail| Q[Screenshot + stealth retry]
  Q -->|still bot| R[Evasion: sleep + rotate + warmup + Google referer]
  R -->|fail| S[Return failed / None]
  N -->|no| T{HTTP status}
  T -->|429| U[Rotate / backoff + retry]
  T -->|>=400| S
  T -->|OK| P
  P --> V[Flush network dump if needed]
  V --> W[Return page record]
```

### Why order matters

1. **Auth wall before bot detect** — login pages often contain Turnstile/reCAPTCHA widgets; treating them as WAF would burn proxies and CapSolver credits incorrectly.
2. **CapSolver before proxy rotate** — widget tokens may clear the page without changing IP.
3. **Network flush on failure** — dumps land under `network/` for post-mortem.

Full detail: [CRAWL](architecture/CRAWL.md) · [CAPTCHA](architecture/CAPTCHA.md).

---

## 5. Auth workflow

```mermaid
stateDiagram-v2
  [*] --> Decide
  Decide --> Restore: --session-file / saved session
  Decide --> Login: --login + credentials
  Decide --> Anonymous: no auth flags
  Restore --> Verify: optional --auth-check-url
  Login --> Persist: save storage_state
  Persist --> Broadcast: all browser slots
  Broadcast --> Crawl
  Verify --> Crawl: ok
  Verify --> Login: expired / wall
  Anonymous --> Crawl
  Crawl --> WallHit: mid-crawl auth wall
  WallHit --> Skip: default policy
  WallHit --> Relogin: --on-auth-wall relogin
  WallHit --> Abort: --on-auth-wall abort
```

Details: [AUTH](architecture/AUTH.md).

---

## 6. CapSolver workflow

```mermaid
flowchart LR
  Watch[CaptchaNetworkWatcher] --> Detect[DOM + network candidates]
  Detect --> Rank[Rank / merge sitekeys]
  Rank --> Solve[CapSolverProvider.solve]
  Solve -->|ok| Inject[inject_solution]
  Inject --> Reload{reload needed?}
  Reload -->|yes| Goto[page.reload]
  Reload -->|no| Wait[settle / re-submit]
  Solve -->|type mismatch| Remap[variant_remaps + retry]
  Solve -->|unsolvable challenge_page| Skip[Skip CapSolver]
```

**Enabled by default** when `capsolver.key`, `CAPSOLVER_API_KEY`, or `WEBVAC_CAPSOLVER_KEY` is present. Details: [CAPTCHA](architecture/CAPTCHA.md).

---

## 7. Proxy failure workflow

```mermaid
flowchart TD
  Req[Request / page attempt] --> Out{Outcome}
  Out -->|success| Sticky[increment sticky counter]
  Sticky -->|threshold| SoftRot[voluntary rotate — not a failure]
  Out -->|429 / soft bot| Cool[cooldown proxy]
  Cool --> Next[pick next active proxy]
  Out -->|hard connect error| Fail[increment hard failures]
  Fail -->|max| Dead[mark dead]
  Next --> Sole{only cooling proxy?}
  Sole -->|yes| Wait[wait up to 30s and reuse]
  Health[Startup health-check] -->|all fail| Direct[Continue on real IP]
```

Details: [PROXY_ORIGIN](architecture/PROXY_ORIGIN.md).

---

## 8. VAPT workflow

```mermaid
sequenceDiagram
  participant Op as Operator
  participant S as scraper.run
  participant D as run_decaffeinator_task
  participant Sub as blob-unpacker/run.py

  Op->>S: --task vapt --url …
  S->>D: create ScanSession
  D->>D: write meta.json start
  D->>Sub: subprocess python run.py …
  Sub-->>D: exit code + reports
  D->>D: mark_completed + rewrite meta
  D-->>Op: analysis/decaffeinator/ artifacts
```

Details: [VAPT](architecture/VAPT.md).

---

## 9. Persist / report workflow

```mermaid
flowchart TD
  Results[List of page dicts] --> PDF[Optional PDF downloads]
  PDF --> Save[Storage.save]
  Save --> Complete[scan.mark_completed]
  Complete --> Meta[meta/meta.json]
  Save --> JSON[scrape/data.json]
  Save --> HTML[scrape/report.html]
  Save --> More[csv / md / sqlite if requested]
```

Details: [DATA](architecture/DATA.md) · [SCAN_LAYOUT](SCAN_LAYOUT.md).

---

## 10. Doctor workflow

```mermaid
flowchart TD
  Doc[python -m webvac --doctor] --> Py[Python OK]
  Py --> Out[Output dir writable]
  Out --> Pipe[Pipeline file]
  Pipe --> Cap[CapSolver key / enablement]
  Cap --> Prox[Proxy load + health]
  Prox --> Br{task vapt without playwright?}
  Br -->|skip browser| Done[Summary]
  Br -->|scrape| PR[Patchright launch]
  PR --> Done
  Doc --> VaptCheck[If --task vapt: decaffeinator root + npx]
```

Failures exit non-zero; warnings (dead proxies, no CapSolver key) do not.
