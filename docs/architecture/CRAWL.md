# Crawl & Browser Architecture

**Parent:** [Full System Architecture](../ARCHITECTURE.md)  
**Code:** `core/crawler.py`, `core/page_scrape_flow.py`, `utils/browser.py`, `utils/browser_pool.py`, `utils/detection.py`, `scope/scope_manager.py`

---

## 1. Goals

- Crawl single pages or whole sites with depth / page limits.
- Run N concurrent workers as isolated browser contexts.
- Survive bot challenges with retries, origin bypass, and CAPTCHA prompts.
- Stay polite (robots, delays) and in-scope.

---

## 2. Component diagram

```mermaid
flowchart TB
  Scraper[scraper.run] --> Crawler
  Crawler --> Scope[ScopeManager]
  Crawler --> Flow[run_page_scrape]
  Crawler --> Pool[Browser slots]
  Flow --> BM[BrowserManager]
  Flow --> Det[detection]
  Flow --> Auth[AuthManager walls]
  Flow --> Collect[_collect_page]
  Collect --> Parser[HtmlPageParser]
  BM --> Slot0[BrowserSlot 0]
  BM --> SlotN[BrowserSlot N]
```

---

## 3. BFS crawl algorithm

```mermaid
flowchart TD
  Start[scrape_site seed] --> Init[_init_session]
  Init --> Enq[enqueue seed depth 0]
  Enq --> Loop{queue empty or max_pages?}
  Loop -->|yes| Done[finalize + return results]
  Loop -->|no| Batch[take up to concurrency URLs]
  Batch --> Gather[asyncio.gather run_page_scrape]
  Gather --> Merge[append records]
  Merge --> Links[for each internal link]
  Links --> OK{_url_ok_for_crawl?}
  OK -->|yes| Enq2[enqueue depth+1]
  OK -->|no| Drop[drop]
  Enq2 --> Loop
  Drop --> Loop
```

**`_url_ok_for_crawl` checks:**

1. Scope (host / subdomain policy)  
2. Depth limit  
3. Allow / deny URL regex  
4. Logout URL soft-deny when authenticated  
5. robots.txt (unless disabled)

---

## 4. Per-page scrape flow

```mermaid
flowchart TD
  Start[run_page_scrape] --> Delay[robots wait + polite sleep]
  Delay --> Engine{engine?}
  Engine -->|lightweight| LW[_scrape_page_lightweight]
  LW -->|bot/block| Dyn[fall through to dynamic]
  Engine -->|dynamic| Dyn
  Dyn --> Page[browser.new_page slot]
  Page --> Goto[page.goto]
  Goto --> After[_after_goto challenge wait]
  After --> AuthW[auth-wall check]
  AuthW -->|abort/skip/relogin| AuthOut[policy branch]
  AuthW -->|ok| Bot{bot detected?}
  Bot -->|yes| Evade[stealth / rotate / CAPTCHA]
  Bot -->|no| Scroll[_scroll_page]
  Evade -->|still blocked| Fail[screenshot + None]
  Evade -->|ok| Scroll
  Scroll --> Collect[_collect_page]
  Collect --> Close[page.close]
  Close --> Ret[return page dict]
```

---

## 5. Browser pool model

```mermaid
flowchart LR
  subgraph BM [BrowserManager]
    Launch[shared Chromium]
    Launch --> C0[Context slot 0]
    Launch --> C1[Context slot 1]
    Launch --> CN[Context slot N]
  end

  ID0[SlotIdentity UA+CH] --> C0
  ID1[SlotIdentity UA+CH] --> C1
  Proxy0[Proxy entry] --> C0
  Proxy1[Proxy entry] --> C1
  AuthState[shared storage_state] -.-> C0
  AuthState -.-> C1
  AuthState -.-> CN
```

| Concept | Meaning |
|---------|---------|
| Slot | Isolated `BrowserContext` + page factory |
| SlotIdentity | UA / Sec-CH-UA fingerprint per worker |
| Auth broadcast | Same cookies/origins injected into every slot after login |
| Proxy rotate | Rebuild context for one slot; reinject auth if needed |

Key APIs: `start`, `new_page(slot)`, `rotate_proxy`, `set_auth_session`, `broadcast_auth_session`, `capture_auth_session`, `human_warmup`, `prompt_captcha_solve`, `reconfigure_host_resolver`.

---

## 6. Modes

| Mode | Entry | Behavior |
|------|-------|----------|
| `single` | `scrape_single` | One URL, no link follow |
| `crawl` | `scrape_site` | BFS internal links |
| `engine=dynamic` | default | Patchright |
| `engine=lightweight` | CLI | aiohttp first; upgrade to dynamic on blocks; **disabled when `--login`** |

---

## 7. Anti-block escalation

```mermaid
flowchart TD
  Block[Bot / challenge detected] --> Stealth[stealth retry + warmup]
  Stealth -->|fail| Rotate[proxy rotate + backoff]
  Rotate -->|fail| Referrer[Google referrer trick]
  Referrer -->|fail| Captcha[optional --no-headless CAPTCHA prompt]
  Captcha -->|fail| GiveUp[record failure / screenshot]
```

Detection lives in `utils/detection.py` (`is_bot_detected`, `wait_for_challenge_resolution`).

---

## 8. Scope architecture

`scope/scope_manager.py`:

- Seed host is in-scope.
- Optional subdomain allow.
- Depth tracking per visit.
- Feeds crawler URL admission.

```mermaid
flowchart LR
  URL --> Scope{CrawlScope.is_url_in_scope}
  Scope -->|yes| Depth{depth <= max}
  Depth -->|yes| Admit[crawl]
  Scope -->|no| Reject
  Depth -->|no| Reject
```

---

## 9. Collection branch

```mermaid
flowchart TD
  HTML[page.content] --> PR[PageRecordBuilder.from_html]
  PR --> Dict[page dict]
```

The default path builds page records directly from scraped HTML.
