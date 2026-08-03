# Architecture documentation index

| Document | Description |
|----------|-------------|
| [STRUCTURE.md](STRUCTURE.md) | Clean repository / `webvac/` package tree |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full system architecture — layers, runtime sequence, package map, status || [architecture/AUTH.md](architecture/AUTH.md) | AuthManager, engines, sessions, MFA, walls, bootstrap |
| [architecture/CRAWL.md](architecture/CRAWL.md) | BFS crawler, page_scrape_flow, browser pool, anti-block |
| [architecture/DATA.md](architecture/DATA.md) | HTML parse, page records, scan layout, exports |
| [architecture/PROXY_ORIGIN.md](architecture/PROXY_ORIGIN.md) | Proxies, robots, CF-Hero, origin IP bypass |
| [architecture/CF_HERO.md](architecture/CF_HERO.md) | Complete CF-Hero CLI integration + validation |
| [architecture/VAPT.md](architecture/VAPT.md) | Collectors → analyzers → findings (default OFF) |
| [CHANGES_AND_IMPROVEMENTS.md](CHANGES_AND_IMPROVEMENTS.md) | Change log + external repo ideas |
| [webvac-architecture-one-page.html](webvac-architecture-one-page.html) | Visual one-pager |

All diagrams use Mermaid — view in GitHub, VS Code Mermaid preview, or any Mermaid-compatible renderer.
