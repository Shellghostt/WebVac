# Data & Storage Architecture

**Parent:** [Full System Architecture](../ARCHITECTURE.md)  
**Code:** `data/`, `store/`, `models/`, `utils/asset_downloader.py`

---

## 1. Goals

- Turn raw HTML into a stable **page record** dict.
- Persist versioned scan sessions with multi-format exports.
- Diff against prior scans and download discovered assets.

---

## 2. Component diagram

```mermaid
flowchart LR
  Page[Browser page HTML] --> Parser[HtmlPageParser]
  Parser --> Builder
  Builder --> Dict[page dict]
  Dict --> Pipe[PipelineManager optional]
  Pipe --> Results[results list]
  Results --> Storage[Storage.save]
  Results --> Assets[AssetDownloader]
  Storage --> Layout[ScanSession folders]
```

---

## 3. Page record pipeline

```mermaid
flowchart TD
  HTML[HTML string + URL] --> Parse[BeautifulSoup / lxml]
  Parse --> Extract[title, text, links, forms, emails, meta, …]
  Extract --> Creds[DefaultCredsChecker hints]
  Creds --> Record[page record dict]
  Record --> UserPipe{--pipeline-file?}
  UserPipe -->|yes| Transform[process_item hooks]
  UserPipe -->|no| Out[append to results]
  Transform --> Out
```

**Key types:**

| Module | Role |
|--------|------|
| `data/html_parser.py` | DOM extraction |
| `data/page_record.py` | `PageRecordBuilder.from_html` |
| `core/pipeline.py` | User post-process hooks |
| `models/scan.py` | `ScanMetadata`, `TargetMetadata` |

---

## 4. Scan session layout

```mermaid
flowchart TB
  Root[scraped_data] --> Target["target folder domain_id"]
  Target --> Scans[scans/]
  Scans --> Scan["timestamp_scanid/"]
  Scan --> Scrape[scrape/]
  Scan --> Network[network/]
  Scan --> Meta[meta/]
  Scan --> Assets[assets/]
```

`store/scan_session.py` owns path helpers and parent-scan chaining (`--parent-scan-id`).

---

## 5. Export formats

`data/storage.py` → `Storage.save`:

| Format | Typical file |
|--------|----------------|
| JSON | `scrape/data.json` |
| CSV | `scrape/data.csv` |
| HTML | `scrape/report.html` |
| Markdown | `scrape/data.md` |
| SQLite | `scrape/data.sqlite` |
| all | union of above |

Screenshots land in `assets/screenshots/`; network failure dumps in `network/`.

---

## 6. Asset download path

```mermaid
flowchart LR
  Results[page records] --> PDF[collect_pdf_urls]
  PDF --> DL[AssetDownloader.download_pdfs]
  DL --> Out[assets/pdfs/]
  JS[JS collector / sourcemaps] -.-> SM[assets/sourcemaps/]
  Cap[ScreenshotModule] --> SS[assets/screenshots/]
```

Triggered from `scraper._persist_run` after crawl completes (or on interrupt with partial results).

---

## 7. Models overview

```mermaid
classDiagram
  class ScanMetadata {
    scan_id
    target
    started_at
    config snapshot
  }
  class PageRecord {
    url
    title
    links
    forms
    emails
    status
  }
  ScanMetadata --> PageRecord : produces many
```

---

## 8. Data contracts (page dict)

Typical fields produced for scrape mode (simplified):

- Identity: `url`, `final_url`, `title`, `status`
- Content: `text`, `headings`, `meta`
- Graph: `links` (`internal` / `external`), `forms`
- Signals: `emails`, `phones`, default-cred hints
- Ops: timestamps, depth, errors, bot flags

User pipelines must treat this dict as the contract; avoid breaking Storage/HTML report renderers.
