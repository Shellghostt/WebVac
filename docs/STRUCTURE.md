# WebVac repository structure

```text
WebVac/
├── README.md                      # User-facing quick start
├── CHANGELOG.md
├── LICENSE                        # MIT
├── requirements.txt
├── pyproject.toml                 # package metadata + console scripts
├── .gitignore
├── .gitmodules                    # decaffeinator submodule
├── run.py                         # thin shim → webvac.cli.interactive
├── examples/                      # input templates (see examples/README.md)
│   ├── auth_creds.example.json
│   ├── proxies.example.txt
│   ├── session.example.json
│   ├── session_cookies_legacy.example.json
│   ├── pipeline.example.py
│   ├── capsolver.example.key
│   ├── captcha_smoke.py
│   └── captcha_watch_demo.py
├── docs/                          # this documentation tree
├── scripts/                       # tooling (architecture PDF)
├── decaffeinator/                 # De-Caffeinator git submodule
│   └── blob-unpacker/             # tool root (run.py)
└── webvac/                        # installable Python package
    ├── __init__.py                # version
    ├── __main__.py                # python -m webvac
    ├── cli/
    │   ├── scraper.py             # CLI orchestrator + --doctor
    │   ├── interactive.py         # menu launcher
    │   └── captcha_demo.py        # CapSolver demo helper
    ├── core/
    │   ├── crawler.py             # single + BFS crawl
    │   ├── page_scrape_flow.py    # per-URL critical path
    │   └── pipeline.py            # user post-processors
    ├── auth/                      # AuthManager, sessions, MFA, walls
    ├── captcha/                   # CapSolver pipeline
    ├── utils/                     # browser, proxy, robots, network, …
    ├── data/                      # parse, page records, storage
    ├── config/                    # DEFAULT_CONFIG
    ├── models/                    # ScanMetadata, origin models
    ├── store/                     # ScanSession layout
    └── vapt/                      # De-Caffeinator launcher
```

## Entry points

| Command | Module |
|---------|--------|
| `python run.py` | `webvac.cli.interactive` |
| `python -m webvac …` | `webvac.cli.scraper` |
| `webvac` (after `pip install -e .`) | `webvac.cli.scraper:main` |
| `webvac-menu` | `webvac.cli.interactive:main` |

## Runtime / local (gitignored)

| Path | Purpose |
|------|---------|
| `scraped_data/` | Scan outputs |
| `sessions/` | Auth `storage_state` files |
| `auth_creds.json` | Real credentials (from example) |
| `proxies.txt` | Local proxy list |
| `capsolver.key` | CapSolver API key |
| `.env` | Optional env secrets |
| `.venv/` | Virtualenv |

## Documentation index

See [docs/README.md](README.md).
