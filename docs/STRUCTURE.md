# WebVac repository structure

```text
WebVac/
├── README.md
├── requirements.txt
├── pyproject.toml              # package metadata + console scripts
├── .gitignore
├── run.py                      # thin shim → webvac.cli.interactive
├── examples/                   # input templates (see examples/README.md)
│   ├── auth_creds.example.json
│   ├── proxies.example.txt
│   ├── session.example.json
│   ├── session_cookies_legacy.example.json
│   └── pipeline.example.py
├── docs/                       # architecture & guides
├── scripts/                    # tooling (e.g. architecture PDF)
├── tests/                      # unittest suite
└── webvac/                     # installable Python package
    ├── __init__.py
    ├── __main__.py             # python -m webvac
    ├── cli/
    │   ├── scraper.py          # CLI orchestrator
    │   └── interactive.py      # menu launcher
    ├── core/                   # crawler, page flow, pipelines, VAPT runner
    ├── auth/                   # AuthManager, sessions, MFA, walls
    ├── utils/                  # browser, proxies, CF-Hero, robots, …
    ├── data/                   # parse, page records, storage
    ├── config/
    ├── models/
    ├── store/
    ├── scope/
    ├── graph/
    ├── intelligence/
    ├── collectors/             # VAPT collectors (default off)
    ├── analyzers/
    ├── findings/
    └── active/
```

## Entry points

| Command | Module |
|---------|--------|
| `python run.py` | `webvac.cli.interactive` |
| `python -m webvac …` | `webvac.cli.scraper` |
| `webvac` (after `pip install -e .`) | `webvac.cli.scraper:main` |
| `webvac-menu` | `webvac.cli.interactive:main` |

## Runtime / local (gitignored)

- `scraped_data/` — scan outputs  
- `sessions/` — auth storage_state  
- `auth_creds.json` — real credentials (use `examples/auth_creds.example.json`)  
- `proxies.txt` — local proxy lists  
