# Proxy, Robots & Origin Architecture

**Parent:** [Full System Architecture](../ARCHITECTURE.md)  
**Code:** `utils/proxy.py`, `utils/robots.py`, `utils/cf_hero.py`, `utils/origin_probe.py`, `utils/detection.py`

---

## 1. Goals

- Route traffic through healthy proxies with strategy + cooldown.
- Obey robots.txt (unless explicitly disabled).
- Optionally scrape via **origin IP + Host header** when CDN edge blocks the browser (authorized use only).

---

## 2. Component diagram

```mermaid
flowchart TB
  Scraper --> Proxy[ProxyManager]
  Scraper --> Robots[RobotsHandler]
  Scraper --> Origin[_resolve_origin_access]
  Origin --> CF[cf_hero.discover_origin]
  Origin --> Probe[origin_probe.validate_origin]
  Proxy --> Slots[per-slot proxy entries]
  Crawler --> Proxy
  Crawler --> Robots
  Crawler --> CF
  Flow[page_scrape_flow] --> Det[detection]
  Det -->|block| CF
```

---

## 3. Proxy architecture

```mermaid
flowchart LR
  File[proxies.txt / --proxies] --> PM[ProxyManager]
  PM --> Bench[benchmark_all latency]
  Bench --> Pool[healthy pool]
  Pool --> Strat{strategy}
  Strat -->|latency| Best[lowest RTT]
  Strat -->|round_robin| RR[rotate]
  Strat -->|random| Rand[pick]
  Best --> Slot[assign to BrowserSlot]
  RR --> Slot
  Rand --> Slot
  Slot --> Sticky{sticky_requests}
  Sticky -->|hit| VolRotate[voluntary rotate]
  Err[429 / timeout] --> Cool[cooldown_seconds]
  Cool --> Pool
```

**Auth interaction:** when authenticated / `--login`, voluntary rotate on slot 0 is suppressed (`auth_pin_proxy`). Forced rotate reinjects `storage_state` and may re-verify `--auth-check-url`.

---

## 4. Robots architecture

```mermaid
sequenceDiagram
  participant C as Crawler
  participant R as RobotsHandler
  participant T as Target

  C->>R: fetch(seed robots.txt)
  R->>T: GET /robots.txt
  T-->>R: rules + crawl-delay
  loop each URL
    C->>R: is_allowed(url)
    R-->>C: allow/deny
    C->>R: wait_if_needed()
  end
```

Flags:

- `--no-robots` — ignore entirely  
- `--ignore-crawl-delay` — keep allow/deny, skip delay  
- `--delay-min` / `--delay-max` — additional politeness jitter  

---

## 5. Origin / CF-Hero path

```mermaid
flowchart TD
  Need[CDN / bot block or --cf-hero / --origin-ip] --> Mode{mode}
  Mode -->|manual| IP[--origin-ip]
  Mode -->|discover| Hero[run cf-hero binary]
  Hero --> Cand[candidate origin IPs]
  IP --> Val[validate_origin title check]
  Cand --> Val
  Val -->|ok| OriginTarget[OriginTarget model]
  OriginTarget --> Browser[Host header / host resolver reconfig]
  OriginTarget --> Light[lightweight fetch_via_origin]
```

| Piece | Role |
|-------|------|
| `utils/cf_hero.py` | Locate binary, run, parse IPs |
| `utils/origin_probe.py` | Title validation, origin HTTP fetch |
| `models/origin.py` | `OriginTarget` dataclass |
| `BrowserManager.reconfigure_host_resolver` | Point hostname → origin IP in browser |

**Auto fallback:** on persistent bot block, crawler may invoke CF-Hero if `cf_hero_auto_fallback` is true (`--no-cf-hero-auto` disables).

---

## 6. Decision matrix

| Situation | Preferred action |
|-----------|------------------|
| Normal scrape | Direct or proxy via Patchright |
| Soft rate limit | Delay + sticky rotate |
| Hard bot wall | Stealth → CF-Hero → CAPTCHA |
| Authenticated crawl | Pin proxy; avoid voluntary rotate |
| Authorized origin recon | `--origin-ip` or `--cf-hero` |

---

## 7. Security / ethics note

Origin-IP scraping and CF-Hero bypass can violate target ToS and laws if unauthorized. Architecture supports these only as **opt-in operator tools** with validation guards (`expected_title`) to reduce accidental misrouting.
