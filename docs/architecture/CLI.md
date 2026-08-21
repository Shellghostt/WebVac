# CLI & interactive launcher architecture

**Parent:** [ARCHITECTURE](../ARCHITECTURE.md) · [WORKFLOWS](../WORKFLOWS.md)  
**Code:** `webvac/cli/scraper.py`, `webvac/cli/interactive.py`, `run.py`, `webvac/__main__.py`

---

## 1. Entry points

| Command | Resolves to |
|---------|-------------|
| `python -m webvac` | `webvac.cli.scraper:main` |
| `webvac` | same (console script) |
| `python run.py` | `webvac.cli.interactive:main` |
| `webvac-menu` | same |

`run.py` is only a shim; all logic lives in the package.

---

## 2. scraper.py flow

```mermaid
flowchart TD
  main[main] --> parse[build_parser]
  parse --> need{url or doctor?}
  need -->|doctor| doc[_run_doctor exit]
  need -->|url| run[asyncio.run run args]
  run --> task{task}
  task -->|vapt| vapt[run_decaffeinator_task]
  task -->|scrape| prep[formats proxies playbook robots]
  prep --> br[BrowserManager.start]
  br --> auth[Auth restore/login]
  auth --> crawl[Crawler scrape_single/site]
  crawl --> save[_persist_run Storage.save]
  save --> stop[browser.stop]
```

### Responsibilities of `run()`

1. Resolve output formats (default `json,html`).
2. Auto-pick `proxies.txt` / pipeline example when present.
3. Apply proxy playbook.
4. Build robots handler only if respecting robots.
5. Load proxies + optional health-check (dead pool → direct IP message).
6. Start browser with concurrency slots.
7. AuthManager restore or login.
8. Construct `Crawler` + `session_config` (humanize, CapSolver, network debug, …).
9. Execute scrape; download PDFs; `Storage.save`; stop browser.

---

## 3. Interactive menu

```mermaid
flowchart TD
  M[main menu] --> Q[Quick scrape single]
  M --> C[Site crawler]
  M --> V[VAPT / JS analysis]
  M --> L[Scan library]
  M --> X[Quit]
  Q --> Wiz[Auth + options wizard]
  C --> Wiz
  V --> Vwiz[VAPT profile wizard]
  Wiz --> Argv[Build argv list]
  Vwiz --> Argv
  Argv --> Scraper[Invoke scraper.main]
```

Scrape wizard fixes several production defaults: `--format json,html`, `--no-robots`, `--wait-until load`, auto `proxies.txt` when present.

---

## 4. Doctor

`python -m webvac --doctor` (optionally with `--url` / `--task vapt`):

| Check | Severity |
|-------|----------|
| Python version | OK / FAIL |
| Output dir writable | OK / FAIL |
| Pipeline file | OK / WARN |
| CapSolver key + default enablement | OK / WARN / FAIL |
| Proxy file load + health | OK / WARN |
| Patchright launch | OK / FAIL (may skip for some VAPT) |
| De-Caffeinator root + npx | when `--task vapt` |

Exit code `1` if any FAIL.

---

## 5. Argv / config merge

CLI flags overlay `DEFAULT_CONFIG` into a `session_config` dict consumed by BrowserManager, Crawler, CapSolver, etc. See [CONFIG_REFERENCE](../CONFIG_REFERENCE.md).

Notable defaults:

- Robots bypassed unless `--respect-robots`
- CapSolver on when key present unless `--captcha-solver none`
- Network debug on unless `--no-network-debug`

---

## 6. Related

- [VAPT](VAPT.md)  
- [CRAWL](CRAWL.md)  
- [CAPTCHA](CAPTCHA.md)  
