"""
storage.py — Save scraped data to JSON, CSV, Markdown, SQLite, and HTML.

Folder structure:
    scraped_data/
        <slug>/                         ← per-site folder
            <timestamp>/                ← per-session folder
                data.json
                data.csv
                report.md
                report.html             ← beautiful interactive HTML report
                data.db
            diffs/
                diff_<timestamp>.json
                diff_<timestamp>.md

Supported formats (pass as a list to save()):
    json      — Full nested data, pretty-printed.
    csv       — Flattened rows; nested fields are JSON-stringified.
    markdown  — Human-readable document with tables and sections per page.
    sqlite    — SQLite DB with scalar columns + JSON blobs; queryable.
    html      — Beautiful interactive single-file HTML report.
"""

import json
import csv
import os
import sqlite3
from datetime import datetime
from urllib.parse import urlparse


# Fields stored as dedicated SQLite columns for easy SQL querying
_SQLITE_SCALAR_COLS = ["url", "status", "error", "scraped_at", "title", "word_count"]
_SQLITE_JSON_COLS = [
    "meta", "open_graph", "twitter_card", "structured_data",
    "headings", "paragraphs", "links", "images", "tables",
    "lists", "forms", "media", "code_blocks", "emails",
    "phone_numbers", "social_links",
]


class Storage:

    def __init__(self, output_dir: str = "scraped_data"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def save(
        self,
        data: list[dict],
        label: str = None,
        formats: list[str] = None,
    ) -> dict:
        """
        Save a list of page dicts in the requested formats.
        Returns a dict mapping format name → saved file path.

        Args:
            data:    List of page dicts from the extractor.
            label:   Custom filename prefix (default: domain slug).
            formats: Which formats to write. Valid values:
                     "json", "csv", "markdown", "sqlite", "html".
                     Defaults to ["json", "csv", "html"].
        """
        if not data:
            print("[Storage] No data to save.")
            return {}

        formats = formats or ["json", "csv", "html"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = label or self._url_slug(data[0].get("url", "scrape"))

        # ── Build per-site / per-session directory ────────────────────────────
        site_dir    = os.path.join(self.output_dir, slug)
        session_dir = os.path.join(site_dir, timestamp)
        diffs_dir   = os.path.join(site_dir, "diffs")
        os.makedirs(session_dir, exist_ok=True)
        os.makedirs(diffs_dir,   exist_ok=True)

        # ── Compute sequential scan differences ───────────────────────────────
        self._generate_diff(data, slug, timestamp, site_dir, diffs_dir)

        _writers = {
            "json":     lambda d, _: self._save_json(d, session_dir),
            "csv":      lambda d, _: self._save_csv(d, session_dir),
            "markdown": lambda d, _: self._save_markdown(d, session_dir, slug, timestamp),
            "sqlite":   lambda d, _: self._save_sqlite(d, session_dir, slug),
            "html":     lambda d, _: self._save_html(d, session_dir, slug, timestamp),
        }

        paths: dict[str, str] = {}
        for fmt in formats:
            writer = _writers.get(fmt)
            if writer:
                paths[fmt] = writer(data, None)

        print(f"\n[Storage] Saved {len(data)} page(s) -> {session_dir}")
        for fmt, path in paths.items():
            rel = os.path.relpath(path, self.output_dir)
            print(f"  {fmt.upper():8s} -> {rel}")
        return paths

    # ── JSON ──────────────────────────────────────────────────────────────────

    def _save_json(self, data: list[dict], session_dir: str) -> str:
        path = os.path.join(session_dir, "data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    # ── CSV ───────────────────────────────────────────────────────────────────

    def _save_csv(self, data: list[dict], session_dir: str) -> str:
        """Flatten each page record into CSV rows. Nested lists/dicts are JSON-stringified."""
        path = os.path.join(session_dir, "data.csv")
        flat_rows = [self._flatten(record) for record in data]
        all_keys = self._all_keys(flat_rows)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            for row in flat_rows:
                writer.writerow({k: row.get(k, "") for k in all_keys})
        return path

    def _flatten(self, record: dict, prefix: str = "") -> dict:
        """Recursively flatten a nested dict. Lists / deep dicts become JSON strings."""
        flat = {}
        for key, value in record.items():
            full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            if isinstance(value, dict):
                if len(value) <= 10:
                    flat.update(self._flatten(value, prefix=full_key))
                else:
                    flat[full_key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, list):
                flat[full_key] = json.dumps(value, ensure_ascii=False)
            else:
                flat[full_key] = value if value is not None else ""
        return flat

    def _all_keys(self, rows: list[dict]) -> list:
        """Union of all keys across rows, preserving insertion order."""
        seen: dict = {}
        for row in rows:
            for key in row:
                seen[key] = True
        return list(seen.keys())

    # ── Markdown ──────────────────────────────────────────────────────────────

    def _save_markdown(self, data: list[dict], session_dir: str, slug: str, timestamp: str) -> str:
        """Generate a readable Markdown document — one section per scraped page."""
        path = os.path.join(session_dir, "report.md")
        ts_fmt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        lines: list[str] = [
            f"# WebVac Report — `{slug}`\n",
            f"*{len(data)} page(s) · generated {ts_fmt}*\n",
            "---\n",
        ]

        for i, page in enumerate(data, 1):
            title = page.get("title") or page.get("url", "Untitled")
            lines.append(f"\n## {i}. {title}\n")

            # ── Summary table ────────────────────────────────────────────────
            lines.append("| Field | Value |")
            lines.append("|---|---|")
            lines.append(f"| **URL** | {page.get('url', '')} |")
            if page.get("scraped_at"):
                lines.append(f"| **Scraped** | {page['scraped_at']} |")
            lines.append(f"| **Status** | {page.get('status', 'success')} |")
            lines.append(f"| **Words** | {page.get('word_count', 0):,} |")
            meta = page.get("meta", {})
            if meta.get("description"):
                lines.append(f"| **Description** | {meta['description']} |")
            og = page.get("open_graph", {})
            if og.get("image"):
                lines.append(f"| **OG Image** | {og['image']} |")
            lines.append("")

            # ── Headings ─────────────────────────────────────────────────────
            headings = page.get("headings", {})
            if headings:
                lines.append("### Headings\n")
                for level, texts in headings.items():
                    depth = int(level[1])
                    hashes = "#" * (depth + 2)
                    for text in texts:
                        lines.append(f"{hashes} {text}")
                lines.append("")

            # ── Paragraphs (first 10) ─────────────────────────────────────
            paragraphs = page.get("paragraphs", [])
            if paragraphs:
                lines.append("### Content\n")
                for para in paragraphs[:10]:
                    lines.append(f"{para}\n")
                if len(paragraphs) > 10:
                    lines.append(f"*…{len(paragraphs) - 10} more paragraph(s) — see data.json for full data.*\n")

            # ── Links table ───────────────────────────────────────────────
            links = page.get("links", [])
            internal = [l for l in links if l.get("type") == "internal"]
            external = [l for l in links if l.get("type") == "external"]
            if links:
                lines.append(
                    f"### Links — {len(internal)} internal / {len(external)} external\n"
                )
                sample = (external or internal)[:20]
                if sample:
                    lines.append("| Text | URL |")
                    lines.append("|---|---|")
                    for lk in sample:
                        text = (lk.get("text") or lk["url"])[:60]
                        lines.append(f"| {text} | {lk['url']} |")
                    if len(links) > 20:
                        lines.append(f"\n*…{len(links) - 20} more links in data.json output.*")
                lines.append("")

            # ── Images ───────────────────────────────────────────────────
            images = page.get("images", [])
            if images:
                lines.append(f"### Images ({len(images)})\n")
                for img in images[:10]:
                    alt = img.get("alt") or "(no alt)"
                    lines.append(f"- `{img['src']}` — *{alt}*")
                if len(images) > 10:
                    lines.append(f"\n*…{len(images) - 10} more images in data.json output.*")
                lines.append("")

            # ── Contact / Social ─────────────────────────────────────────
            emails = page.get("emails", [])
            phones = page.get("phone_numbers", [])
            social = page.get("social_links", [])
            if emails or phones or social:
                lines.append("### Contact & Social\n")
                for em in emails:
                    lines.append(f"- ✉  {em}")
                for ph in phones:
                    lines.append(f"- 📞 {ph}")
                for soc in social:
                    lines.append(f"- **{soc.get('platform', '')}** — {soc.get('url', '')}")
                lines.append("")

            lines.append("---\n")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path

    # ── SQLite ────────────────────────────────────────────────────────────────

    def _save_sqlite(self, data: list[dict], session_dir: str, slug: str) -> str:
        path = os.path.join(session_dir, f"{slug}.db")
        conn = sqlite3.connect(path)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT,
                status           TEXT,
                error            TEXT,
                scraped_at       TEXT,
                title            TEXT,
                word_count       INTEGER,
                meta_description TEXT,
                meta_keywords    TEXT,
                og_title         TEXT,
                og_description   TEXT,
                og_image         TEXT,
                meta_json             TEXT,
                open_graph_json       TEXT,
                twitter_card_json     TEXT,
                structured_data_json  TEXT,
                headings_json         TEXT,
                paragraphs_json       TEXT,
                links_json            TEXT,
                images_json           TEXT,
                tables_json           TEXT,
                lists_json            TEXT,
                forms_json            TEXT,
                media_json            TEXT,
                code_blocks_json      TEXT,
                emails_json           TEXT,
                phone_numbers_json    TEXT,
                social_links_json     TEXT
            )
        """)

        for page in data:
            meta = page.get("meta", {}) or {}
            og   = page.get("open_graph", {}) or {}

            row = {
                "url":              page.get("url", ""),
                "status":           page.get("status", "success"),
                "error":            page.get("error", ""),
                "scraped_at":       page.get("scraped_at", ""),
                "title":            page.get("title", ""),
                "word_count":       page.get("word_count", 0),
                "meta_description": meta.get("description", ""),
                "meta_keywords":    meta.get("keywords", ""),
                "og_title":         og.get("title", ""),
                "og_description":   og.get("description", ""),
                "og_image":         og.get("image", ""),
            }
            for col in _SQLITE_JSON_COLS:
                val = page.get(col)
                row[f"{col}_json"] = (
                    json.dumps(val, ensure_ascii=False) if val is not None else None
                )

            cur.execute("""
                INSERT INTO pages (
                    url, status, error, scraped_at, title, word_count,
                    meta_description, meta_keywords,
                    og_title, og_description, og_image,
                    meta_json, open_graph_json, twitter_card_json,
                    structured_data_json, headings_json, paragraphs_json,
                    links_json, images_json, tables_json, lists_json,
                    forms_json, media_json, code_blocks_json,
                    emails_json, phone_numbers_json, social_links_json
                ) VALUES (
                    :url, :status, :error, :scraped_at, :title, :word_count,
                    :meta_description, :meta_keywords,
                    :og_title, :og_description, :og_image,
                    :meta_json, :open_graph_json, :twitter_card_json,
                    :structured_data_json, :headings_json, :paragraphs_json,
                    :links_json, :images_json, :tables_json, :lists_json,
                    :forms_json, :media_json, :code_blocks_json,
                    :emails_json, :phone_numbers_json, :social_links_json
                )
            """, row)

        conn.commit()
        conn.close()
        return path

    # ── HTML Report ───────────────────────────────────────────────────────────

    def _save_html(self, data: list[dict], session_dir: str, slug: str, timestamp: str) -> str:
        """Generate a self-contained, beautiful interactive HTML report."""
        path = os.path.join(session_dir, "report.html")
        ts_fmt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%B %d, %Y at %H:%M:%S")

        total   = len(data)
        success = sum(1 for p in data if p.get("status", "success") == "success")
        failed  = total - success
        total_words = sum(p.get("word_count", 0) for p in data)
        total_links = sum(len(p.get("links", [])) for p in data)
        total_images = sum(len(p.get("images", [])) for p in data)

        # ── Sidebar nav items ─────────────────────────────────────────────────
        nav_items = ""
        for i, page in enumerate(data):
            title = (page.get("title") or page.get("url", "Page"))[:45]
            status = page.get("status", "success")
            dot_cls = "dot-ok" if status == "success" else "dot-fail"
            nav_items += f"""
            <a href="#page-{i}" class="nav-item" onclick="showPage({i})">
                <span class="nav-dot {dot_cls}"></span>
                <span class="nav-title">{self._esc(title)}</span>
            </a>"""

        # ── Per-page cards ────────────────────────────────────────────────────
        page_cards = ""
        for i, page in enumerate(data):
            title  = page.get("title") or page.get("url", "Untitled")
            url    = page.get("url", "")
            status = page.get("status", "success")
            words  = page.get("word_count", 0)
            scraped_at = page.get("scraped_at", "")
            meta   = page.get("meta", {}) or {}
            og     = page.get("open_graph", {}) or {}
            tc     = page.get("twitter_card", {}) or {}
            links  = page.get("links", [])
            images = page.get("images", [])
            emails = page.get("emails", [])
            phones = page.get("phone_numbers", [])
            social = page.get("social_links", [])
            headings = page.get("headings", {})
            paragraphs = page.get("paragraphs", [])
            forms  = page.get("forms", [])
            tables = page.get("tables", [])
            creds  = page.get("default_creds", [])

            internal_links = [l for l in links if l.get("type") == "internal"]
            external_links = [l for l in links if l.get("type") == "external"]

            status_badge = (
                '<span class="badge badge-ok">✓ Success</span>'
                if status == "success"
                else f'<span class="badge badge-fail">✗ {self._esc(page.get("error","Failed"))}</span>'
            )

            # OG image preview
            og_img_html = ""
            og_img = og.get("image") or page.get("screenshot")
            if og_img and og_img.startswith("http"):
                og_img_html = f'<img src="{self._esc(og_img)}" class="og-preview" alt="OG image" onerror="this.style.display=\'none\'">'

            # Headings tree
            headings_html = ""
            if headings:
                headings_html = '<div class="headings-tree">'
                for lvl in ["h1","h2","h3","h4","h5","h6"]:
                    for txt in headings.get(lvl, []):
                        headings_html += f'<div class="h-node h-{lvl}"><span class="h-tag">{lvl.upper()}</span> {self._esc(txt)}</div>'
                headings_html += "</div>"

            # Paragraphs (first 5)
            paras_html = ""
            if paragraphs:
                paras_html = "<div class='para-list'>"
                for p in paragraphs[:5]:
                    paras_html += f"<p class='para-item'>{self._esc(p[:300])}{'…' if len(p)>300 else ''}</p>"
                if len(paragraphs) > 5:
                    paras_html += f"<p class='para-more'>+{len(paragraphs)-5} more paragraphs in data.json</p>"
                paras_html += "</div>"

            # Links tables
            int_links_html = self._render_link_table(internal_links[:15], "Internal")
            ext_links_html = self._render_link_table(external_links[:15], "External")

            # Images gallery
            imgs_html = ""
            if images:
                imgs_html = "<div class='img-gallery'>"
                for img in images[:12]:
                    src = img.get("src","")
                    alt = img.get("alt","") or "image"
                    if src.startswith("http"):
                        imgs_html += f'<div class="img-card"><img src="{self._esc(src)}" alt="{self._esc(alt)}" loading="lazy" onerror="this.parentElement.style.display=\'none\'"><div class="img-alt">{self._esc(alt[:40])}</div></div>'
                if len(images) > 12:
                    imgs_html += f'<div class="img-card img-more">+{len(images)-12} more</div>'
                imgs_html += "</div>"

            # Contact / Social
            contact_html = ""
            if emails or phones or social:
                contact_html = "<div class='contact-grid'>"
                for em in emails:
                    contact_html += f'<a class="contact-chip chip-email" href="mailto:{self._esc(em)}">✉ {self._esc(em)}</a>'
                for ph in phones:
                    contact_html += f'<span class="contact-chip chip-phone">📞 {self._esc(ph)}</span>'
                for soc in social:
                    pl = soc.get("platform","")
                    su = soc.get("url","")
                    contact_html += f'<a class="contact-chip chip-social" href="{self._esc(su)}" target="_blank">🔗 {self._esc(pl)}</a>'
                contact_html += "</div>"

            # Default creds warning
            creds_html = ""
            if creds:
                creds_html = "<div class='creds-warning'><div class='creds-title'>⚠ Default Credentials Found</div><div class='creds-list'>"
                for c in creds:
                    creds_html += f"<div class='cred-item'><b>{self._esc(c.get('service',''))}</b> — user: <code>{self._esc(c.get('username',''))}</code> / pass: <code>{self._esc(c.get('password',''))}</code></div>"
                creds_html += "</div></div>"

            # Meta / OG / TC accordion
            meta_rows = "".join(f"<tr><td>{self._esc(k)}</td><td>{self._esc(str(v))}</td></tr>" for k,v in meta.items() if v)
            og_rows   = "".join(f"<tr><td>{self._esc(k)}</td><td>{self._esc(str(v))}</td></tr>" for k,v in og.items() if v)
            tc_rows   = "".join(f"<tr><td>{self._esc(k)}</td><td>{self._esc(str(v))}</td></tr>" for k,v in tc.items() if v)

            page_cards += f"""
            <div class="page-card" id="page-{i}" style="display:none">
                {og_img_html}
                <div class="page-header">
                    <div class="page-header-left">
                        <div class="page-num">Page {i+1} of {total}</div>
                        <h2 class="page-title">{self._esc(title)}</h2>
                        <a class="page-url" href="{self._esc(url)}" target="_blank">{self._esc(url)}</a>
                    </div>
                    <div class="page-header-right">
                        {status_badge}
                        <div class="page-stats-row">
                            <div class="mini-stat"><span class="mini-val">{words:,}</span><span class="mini-lbl">words</span></div>
                            <div class="mini-stat"><span class="mini-val">{len(links)}</span><span class="mini-lbl">links</span></div>
                            <div class="mini-stat"><span class="mini-val">{len(images)}</span><span class="mini-lbl">images</span></div>
                        </div>
                    </div>
                </div>
                <div class="page-meta-strip">
                    <span class="meta-chip">🕐 {self._esc(scraped_at[:19].replace("T"," ") if scraped_at else "")}</span>
                    {"<span class='meta-chip'>📝 " + self._esc(meta.get('description','')[:80]) + "…</span>" if meta.get('description') else ""}
                </div>

                {creds_html}

                <div class="tabs">
                    <button class="tab-btn active" onclick="switchTab(this, 'content-{i}')">Content</button>
                    <button class="tab-btn" onclick="switchTab(this, 'links-{i}')">Links ({len(links)})</button>
                    <button class="tab-btn" onclick="switchTab(this, 'images-{i}')">Images ({len(images)})</button>
                    <button class="tab-btn" onclick="switchTab(this, 'meta-{i}')">Meta / SEO</button>
                    {"<button class='tab-btn' onclick=\"switchTab(this, 'contact-{i}')\">Contact</button>" if (emails or phones or social) else ""}
                </div>

                <div class="tab-panel" id="content-{i}">
                    {('<div class="section-label">Headings</div>' + headings_html) if headings_html else ""}
                    {('<div class="section-label">Content Preview</div>' + paras_html) if paras_html else ""}
                </div>

                <div class="tab-panel hidden" id="links-{i}">
                    {int_links_html}
                    {ext_links_html}
                </div>

                <div class="tab-panel hidden" id="images-{i}">
                    {imgs_html if imgs_html else "<p class='empty-msg'>No images found.</p>"}
                </div>

                <div class="tab-panel hidden" id="meta-{i}">
                    {"<div class='section-label'>Meta Tags</div><table class='meta-table'><thead><tr><th>Property</th><th>Value</th></tr></thead><tbody>" + meta_rows + "</tbody></table>" if meta_rows else ""}
                    {"<div class='section-label'>Open Graph</div><table class='meta-table'><thead><tr><th>Property</th><th>Value</th></tr></thead><tbody>" + og_rows + "</tbody></table>" if og_rows else ""}
                    {"<div class='section-label'>Twitter Card</div><table class='meta-table'><thead><tr><th>Property</th><th>Value</th></tr></thead><tbody>" + tc_rows + "</tbody></table>" if tc_rows else ""}
                </div>

                {"<div class='tab-panel hidden' id='contact-" + str(i) + "'>" + contact_html + "</div>" if (emails or phones or social) else ""}
            </div>"""

        # ── Full HTML ─────────────────────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WebVac Report — {self._esc(slug)}</title>
<style>
  /* ── Reset & Base ─────────────────────────────────────────────────── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:       #0f1117;
    --surface:  #181c24;
    --surface2: #1e2330;
    --border:   #2a2f3e;
    --accent:   #4f8ef7;
    --accent2:  #7c5cbf;
    --ok:       #22c55e;
    --fail:     #ef4444;
    --warn:     #f59e0b;
    --text:     #e2e8f0;
    --muted:    #6b7280;
    --font:     'Segoe UI', system-ui, -apple-system, sans-serif;
    --mono:     'Cascadia Code', 'Fira Code', 'Courier New', monospace;
    --radius:   12px;
    --shadow:   0 4px 24px rgba(0,0,0,0.4);
  }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    font-size: 14px;
    line-height: 1.6;
  }}

  /* ── Top Bar ────────────────────────────────────────────────────────── */
  .topbar {{
    background: linear-gradient(90deg, #0f1117 0%, #181c24 100%);
    border-bottom: 1px solid var(--border);
    padding: 14px 28px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky; top: 0; z-index: 100;
    backdrop-filter: blur(8px);
  }}
  .topbar-logo {{
    font-size: 20px; font-weight: 800; letter-spacing: -0.5px;
    background: linear-gradient(135deg, #4f8ef7, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }}
  .topbar-sep {{ flex: 1; }}
  .topbar-meta {{ color: var(--muted); font-size: 12px; text-align: right; }}
  .topbar-meta strong {{ color: var(--text); }}

  /* ── Layout ─────────────────────────────────────────────────────────── */
  .layout {{ display: flex; flex: 1; height: calc(100vh - 57px); overflow: hidden; }}

  /* ── Sidebar ─────────────────────────────────────────────────────────── */
  .sidebar {{
    width: 280px; min-width: 220px; max-width: 320px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    overflow: hidden;
  }}
  .sidebar-header {{
    padding: 16px 16px 8px;
    border-bottom: 1px solid var(--border);
  }}
  .sidebar-search {{
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 12px;
    color: var(--text);
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s;
  }}
  .sidebar-search:focus {{ border-color: var(--accent); }}
  .sidebar-list {{ flex: 1; overflow-y: auto; padding: 8px; }}
  .sidebar-list::-webkit-scrollbar {{ width: 4px; }}
  .sidebar-list::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}
  .nav-item {{
    display: flex; align-items: center; gap: 10px;
    padding: 9px 10px; border-radius: 8px;
    cursor: pointer; text-decoration: none;
    color: var(--muted); font-size: 12.5px;
    transition: all 0.15s; border: 1px solid transparent;
    white-space: nowrap; overflow: hidden;
  }}
  .nav-item:hover {{ background: var(--surface2); color: var(--text); }}
  .nav-item.active {{ background: rgba(79,142,247,0.12); border-color: rgba(79,142,247,0.3); color: var(--accent); }}
  .nav-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
  .dot-ok   {{ background: var(--ok); box-shadow: 0 0 6px var(--ok); }}
  .dot-fail {{ background: var(--fail); box-shadow: 0 0 6px var(--fail); }}
  .nav-title {{ overflow: hidden; text-overflow: ellipsis; flex: 1; }}

  /* ── Main content ──────────────────────────────────────────────────── */
  .main {{ flex: 1; overflow-y: auto; display: flex; flex-direction: column; }}
  .main::-webkit-scrollbar {{ width: 6px; }}
  .main::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 6px; }}

  /* ── Dashboard ─────────────────────────────────────────────────────── */
  #dashboard {{ padding: 28px; }}
  .dash-title {{ font-size: 24px; font-weight: 700; margin-bottom: 4px; }}
  .dash-sub {{ color: var(--muted); margin-bottom: 24px; font-size: 13px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
    transition: transform 0.2s, border-color 0.2s;
  }}
  .stat-card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
  .stat-val {{ font-size: 28px; font-weight: 800; letter-spacing: -1px; }}
  .stat-lbl {{ font-size: 12px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .stat-ok   .stat-val {{ color: var(--ok); }}
  .stat-fail .stat-val {{ color: var(--fail); }}
  .stat-blue .stat-val {{ color: var(--accent); }}
  .stat-purple .stat-val {{ background: linear-gradient(135deg, #4f8ef7, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}

  /* pages index table */
  .dash-table-wrap {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }}
  .dash-table-title {{ padding: 14px 18px; font-weight: 600; font-size: 13px; border-bottom: 1px solid var(--border); color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
  .dash-table {{ width: 100%; border-collapse: collapse; }}
  .dash-table th {{ padding: 10px 14px; text-align: left; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); background: var(--surface2); }}
  .dash-table td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: middle; }}
  .dash-table tr:last-child td {{ border-bottom: none; }}
  .dash-table tr:hover td {{ background: var(--surface2); }}
  .dash-table tr {{ cursor: pointer; transition: background 0.1s; }}
  .url-cell {{ max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--accent); }}
  .title-cell {{ max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  /* ── Page card ────────────────────────────────────────────────────── */
  .page-card {{ padding: 28px; animation: fadeIn 0.2s ease; }}
  @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(6px); }} to {{ opacity:1; transform:none; }} }}
  .og-preview {{ width: 100%; max-height: 220px; object-fit: cover; border-radius: var(--radius); margin-bottom: 20px; border: 1px solid var(--border); }}
  .page-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 12px; flex-wrap: wrap; }}
  .page-num {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .page-title {{ font-size: 20px; font-weight: 700; margin-bottom: 6px; line-height: 1.3; }}
  .page-url {{ color: var(--accent); font-size: 13px; text-decoration: none; word-break: break-all; }}
  .page-url:hover {{ text-decoration: underline; }}
  .page-header-right {{ text-align: right; flex-shrink: 0; }}
  .page-stats-row {{ display: flex; gap: 16px; margin-top: 10px; justify-content: flex-end; }}
  .mini-stat {{ text-align: center; }}
  .mini-val {{ font-size: 18px; font-weight: 700; color: var(--accent); display: block; }}
  .mini-lbl {{ font-size: 11px; color: var(--muted); }}
  .page-meta-strip {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
  .meta-chip {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 20px; padding: 4px 12px; font-size: 12px; color: var(--muted); }}

  /* ── Badges ──────────────────────────────────────────────────────── */
  .badge {{ padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
  .badge-ok   {{ background: rgba(34,197,94,0.15); color: var(--ok); border: 1px solid rgba(34,197,94,0.3); }}
  .badge-fail {{ background: rgba(239,68,68,0.15); color: var(--fail); border: 1px solid rgba(239,68,68,0.3); }}

  /* ── Tabs ────────────────────────────────────────────────────────── */
  .tabs {{ display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }}
  .tab-btn {{
    padding: 9px 16px; background: none; border: none;
    color: var(--muted); cursor: pointer; font-size: 13px; font-family: var(--font);
    border-bottom: 2px solid transparent; margin-bottom: -1px;
    transition: all 0.15s; border-radius: 4px 4px 0 0;
  }}
  .tab-btn:hover {{ color: var(--text); background: var(--surface2); }}
  .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }}
  .tab-panel {{ animation: fadeIn 0.15s ease; }}
  .tab-panel.hidden {{ display: none; }}

  /* ── Content sections ─────────────────────────────────────────────── */
  .section-label {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.7px; color: var(--muted); margin: 20px 0 10px; }}

  /* headings tree */
  .headings-tree {{ background: var(--surface2); border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; }}
  .h-node {{ display: flex; align-items: baseline; gap: 10px; padding: 3px 0; }}
  .h-tag {{ font-size: 10px; font-weight: 700; font-family: var(--mono); background: var(--border); padding: 1px 6px; border-radius: 4px; color: var(--accent); min-width: 30px; text-align: center; }}
  .h-h1 {{ font-size: 15px; font-weight: 700; color: var(--text); }}
  .h-h2 {{ font-size: 14px; font-weight: 600; color: var(--text); padding-left: 10px; }}
  .h-h3 {{ font-size: 13px; color: #94a3b8; padding-left: 20px; }}
  .h-h4, .h-h5, .h-h6 {{ font-size: 12px; color: var(--muted); padding-left: 30px; }}

  /* paragraphs */
  .para-list {{ display: flex; flex-direction: column; gap: 10px; }}
  .para-item {{ background: var(--surface2); border-left: 3px solid var(--border); padding: 10px 14px; border-radius: 0 8px 8px 0; font-size: 13.5px; color: #94a3b8; line-height: 1.7; }}
  .para-more {{ color: var(--muted); font-size: 12px; font-style: italic; padding: 4px 0; }}

  /* links table */
  .link-section-title {{ font-size: 12px; font-weight: 600; color: var(--muted); margin: 16px 0 8px; display: flex; align-items: center; gap: 8px; }}
  .link-count {{ background: var(--border); border-radius: 20px; padding: 2px 8px; font-size: 11px; }}
  .link-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; background: var(--surface2); border-radius: 10px; overflow: hidden; margin-bottom: 16px; }}
  .link-table th {{ padding: 8px 12px; text-align: left; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; background: var(--surface); }}
  .link-table td {{ padding: 7px 12px; border-top: 1px solid var(--border); word-break: break-all; }}
  .link-table tr:hover td {{ background: rgba(79,142,247,0.05); }}
  .link-text {{ color: var(--text); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .link-url  {{ color: var(--accent); }}
  .link-url a {{ color: inherit; text-decoration: none; }}
  .link-url a:hover {{ text-decoration: underline; }}

  /* images gallery */
  .img-gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }}
  .img-card {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; transition: transform 0.2s, border-color 0.2s; }}
  .img-card:hover {{ transform: scale(1.03); border-color: var(--accent); }}
  .img-card img {{ width: 100%; height: 100px; object-fit: cover; display: block; }}
  .img-alt {{ padding: 6px 8px; font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .img-more {{ display: flex; align-items: center; justify-content: center; height: 130px; font-size: 13px; color: var(--muted); font-style: italic; }}

  /* meta table */
  .meta-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; background: var(--surface2); border-radius: 10px; overflow: hidden; margin-bottom: 16px; }}
  .meta-table th {{ padding: 8px 12px; text-align: left; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; background: var(--surface); }}
  .meta-table td {{ padding: 7px 12px; border-top: 1px solid var(--border); word-break: break-word; }}
  .meta-table td:first-child {{ color: var(--muted); white-space: nowrap; width: 160px; }}
  .meta-table tr:hover td {{ background: rgba(79,142,247,0.05); }}

  /* contact */
  .contact-grid {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .contact-chip {{ padding: 6px 14px; border-radius: 20px; font-size: 12.5px; text-decoration: none; border: 1px solid; transition: all 0.15s; }}
  .chip-email  {{ color: #60a5fa; border-color: rgba(96,165,250,0.3); background: rgba(96,165,250,0.08); }}
  .chip-phone  {{ color: var(--ok);  border-color: rgba(34,197,94,0.3);  background: rgba(34,197,94,0.08); }}
  .chip-social {{ color: #a78bfa;   border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.08); }}
  .chip-email:hover, .chip-social:hover {{ opacity: 0.8; }}

  /* creds warning */
  .creds-warning {{ background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.4); border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; }}
  .creds-title {{ font-weight: 700; color: var(--warn); margin-bottom: 8px; }}
  .cred-item {{ font-size: 13px; color: var(--text); margin-top: 6px; }}
  .cred-item code {{ background: var(--surface2); padding: 1px 6px; border-radius: 4px; font-family: var(--mono); color: var(--warn); }}

  /* empty */
  .empty-msg {{ color: var(--muted); font-style: italic; text-align: center; padding: 30px; font-size: 13px; }}

  /* scrollbar for main */
  .main::-webkit-scrollbar {{ width: 6px; }}
  .main::-webkit-scrollbar-track {{ background: transparent; }}
  .main::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 6px; }}

  /* responsive */
  @media (max-width: 700px) {{
    .sidebar {{ display: none; }}
    .page-header {{ flex-direction: column; }}
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<!-- Top Bar -->
<div class="topbar">
  <div class="topbar-logo">⚡ WebVac</div>
  <div class="topbar-sep"></div>
  <div class="topbar-meta">
    <strong>{self._esc(slug)}</strong><br>
    {self._esc(ts_fmt)}
  </div>
</div>

<div class="layout">
  <!-- Sidebar -->
  <div class="sidebar">
    <div class="sidebar-header">
      <input class="sidebar-search" id="sidebarSearch" placeholder="🔍  Filter pages…" oninput="filterNav(this.value)">
    </div>
    <div class="sidebar-list" id="sidebarList">
      <a href="#dashboard" class="nav-item active" onclick="showDashboard()" id="nav-dash">
        <span class="nav-dot" style="background:var(--accent);box-shadow:0 0 6px var(--accent)"></span>
        <span class="nav-title">📊 Overview Dashboard</span>
      </a>
      {nav_items}
    </div>
  </div>

  <!-- Main -->
  <div class="main" id="main">

    <!-- Dashboard -->
    <div id="dashboard">
      <div class="dash-title">Scrape Report</div>
      <div class="dash-sub">Site: <strong>{self._esc(slug)}</strong> &nbsp;·&nbsp; {self._esc(ts_fmt)}</div>

      <div class="stats-grid">
        <div class="stat-card stat-purple">
          <div class="stat-val">{total}</div>
          <div class="stat-lbl">Pages Scraped</div>
        </div>
        <div class="stat-card stat-ok">
          <div class="stat-val">{success}</div>
          <div class="stat-lbl">Successful</div>
        </div>
        <div class="stat-card stat-fail">
          <div class="stat-val">{failed}</div>
          <div class="stat-lbl">Failed / Blocked</div>
        </div>
        <div class="stat-card stat-blue">
          <div class="stat-val">{total_words:,}</div>
          <div class="stat-lbl">Total Words</div>
        </div>
        <div class="stat-card stat-blue">
          <div class="stat-val">{total_links:,}</div>
          <div class="stat-lbl">Total Links</div>
        </div>
        <div class="stat-card stat-blue">
          <div class="stat-val">{total_images:,}</div>
          <div class="stat-lbl">Total Images</div>
        </div>
      </div>

      <div class="dash-table-wrap">
        <div class="dash-table-title">All Pages</div>
        <table class="dash-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Title</th>
              <th>URL</th>
              <th>Status</th>
              <th>Words</th>
              <th>Links</th>
              <th>Images</th>
            </tr>
          </thead>
          <tbody>
            {"".join(self._render_index_row(i, p, total) for i, p in enumerate(data))}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Page cards (hidden by default) -->
    {page_cards}

  </div><!-- .main -->
</div><!-- .layout -->

<script>
  let currentPage = -1;

  function showDashboard() {{
    document.getElementById('dashboard').style.display = '';
    document.querySelectorAll('.page-card').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById('nav-dash').classList.add('active');
    currentPage = -1;
    document.getElementById('main').scrollTop = 0;
  }}

  function showPage(idx) {{
    document.getElementById('dashboard').style.display = 'none';
    document.querySelectorAll('.page-card').forEach(c => c.style.display = 'none');
    const card = document.getElementById('page-' + idx);
    if (card) card.style.display = '';
    document.querySelectorAll('.nav-item').forEach((n, i) => {{
      n.classList.toggle('active', i === idx + 1);  // +1 because dash is first
    }});
    currentPage = idx;
    document.getElementById('main').scrollTop = 0;
  }}

  function switchTab(btn, panelId) {{
    const card = btn.closest('.page-card');
    card.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    card.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.remove('hidden');
  }}

  function filterNav(q) {{
    const items = document.querySelectorAll('#sidebarList .nav-item:not(#nav-dash)');
    q = q.toLowerCase();
    items.forEach(item => {{
      const txt = item.querySelector('.nav-title').textContent.toLowerCase();
      item.style.display = txt.includes(q) ? '' : 'none';
    }});
  }}

  // Keyboard navigation
  document.addEventListener('keydown', e => {{
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
      if (currentPage < {total - 1}) showPage(currentPage + 1);
    }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
      if (currentPage > 0) showPage(currentPage - 1);
      else if (currentPage === 0) showDashboard();
    }}
  }});
</script>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def _render_index_row(self, i: int, page: dict, total: int) -> str:
        title  = (page.get("title") or "—")[:50]
        url    = page.get("url", "")
        status = page.get("status", "success")
        words  = page.get("word_count", 0)
        links  = len(page.get("links", []))
        images = len(page.get("images", []))
        badge  = (
            '<span style="color:var(--ok);font-weight:600">✓</span>'
            if status == "success"
            else '<span style="color:var(--fail);font-weight:600">✗</span>'
        )
        return (
            f'<tr onclick="showPage({i})">'
            f'<td style="color:var(--muted)">{i+1}</td>'
            f'<td class="title-cell">{self._esc(title)}</td>'
            f'<td class="url-cell"><a href="{self._esc(url)}" target="_blank" onclick="event.stopPropagation()">{self._esc(url)}</a></td>'
            f'<td>{badge}</td>'
            f'<td>{words:,}</td>'
            f'<td>{links}</td>'
            f'<td>{images}</td>'
            f'</tr>'
        )

    def _render_link_table(self, links: list, label: str) -> str:
        if not links:
            return ""
        rows = "".join(
            f'<tr>'
            f'<td class="link-text">{self._esc((lk.get("text") or "—")[:60])}</td>'
            f'<td class="link-url"><a href="{self._esc(lk["url"])}" target="_blank">{self._esc(lk["url"][:80])}</a></td>'
            f'</tr>'
            for lk in links
        )
        return (
            f'<div class="link-section-title">{label} Links <span class="link-count">{len(links)}</span></div>'
            f'<table class="link-table"><thead><tr><th>Text</th><th>URL</th></tr></thead><tbody>{rows}</tbody></table>'
        )

    @staticmethod
    def _esc(s: str) -> str:
        """HTML-escape a string."""
        return (
            str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _url_slug(self, url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").replace(".", "_")
        return domain[:40] if domain else "scrape"

    def _generate_diff(
        self,
        current_data: list[dict],
        slug: str,
        timestamp: str,
        site_dir: str,
        diffs_dir: str,
    ) -> None:
        """
        Scan site_dir for the most recent historical session for the same slug,
        compute changes (new, removed, modified, failures), and save report inside diffs/
        """
        # Find previous sessions: they are subdirectories (timestamps)
        history_sessions = sorted([
            d for d in os.listdir(site_dir)
            if os.path.isdir(os.path.join(site_dir, d)) and d != timestamp and d != "diffs"
        ])

        diff_json_path = os.path.join(diffs_dir, f"diff_{timestamp}.json")
        diff_md_path   = os.path.join(diffs_dir, f"diff_{timestamp}.md")

        curr_total   = len(current_data)
        curr_success = sum(1 for p in current_data if p.get("status", "success") == "success")
        curr_failed  = curr_total - curr_success

        if not history_sessions:
            report = {
                "site": slug, "scan_time": timestamp, "first_run": True,
                "summary": {"total_pages": curr_total, "success": curr_success, "failed": curr_failed}
            }
            with open(diff_json_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

            md = f"""# WebVac Scan Diff — `{slug}`

*Generated on {timestamp} (Initial Run)*

## Scan Overview

* **Total Pages Scraped**: `{curr_total}`
* **Success**: `{curr_success}`
* **Failed/Blocked**: `{curr_failed}`

> [!NOTE]
> No previous scan history found for `{slug}`. Differences will appear on subsequent scans.
"""
            with open(diff_md_path, "w", encoding="utf-8") as f:
                f.write(md)
            return

        # Load previous session's data.json
        prev_session = history_sessions[-1]
        prev_json = os.path.join(site_dir, prev_session, "data.json")
        try:
            with open(prev_json, encoding="utf-8") as f:
                prev_data = json.load(f)
        except Exception as exc:
            print(f"[Diff] [Warning] Failed to read previous session {prev_session}: {exc}")
            return

        prev_total   = len(prev_data)
        prev_success = sum(1 for p in prev_data if p.get("status", "success") == "success")
        prev_failed  = prev_total - prev_success

        prev_map = {p["url"]: p for p in prev_data if "url" in p}
        curr_map = {p["url"]: p for p in current_data if "url" in p}
        prev_urls = set(prev_map.keys())
        curr_urls = set(curr_map.keys())

        added_urls   = curr_urls - prev_urls
        removed_urls = prev_urls - curr_urls
        common_urls  = curr_urls & prev_urls

        modified = []
        for url in common_urls:
            curr_p = curr_map[url]
            prev_p = prev_map[url]
            changes = []
            c_status = curr_p.get("status", "success")
            p_status = prev_p.get("status", "success")
            if c_status != p_status:
                changes.append(f"Status changed from '{p_status}' to '{c_status}'")
            c_title = curr_p.get("title", "")
            p_title = prev_p.get("title", "")
            if c_title != p_title and c_status == p_status == "success":
                changes.append(f"Title changed from '{p_title}' to '{c_title}'")
            c_words = curr_p.get("word_count", 0)
            p_words = prev_p.get("word_count", 0)
            if abs(c_words - p_words) > max(10, p_words * 0.1) and c_status == p_status == "success":
                changes.append(f"Word count changed from {p_words} to {c_words}")
            if changes:
                modified.append({"url": url, "changes": changes})

        failures = [
            {"url": url, "error": curr_map[url].get("error", "Unknown")}
            for url in curr_urls if curr_map[url].get("status") == "failed"
        ]

        report = {
            "site": slug, "scan_time": timestamp, "first_run": False,
            "previous_scan": {"session": prev_session, "total_pages": prev_total, "success": prev_success, "failed": prev_failed},
            "current_scan":  {"total_pages": curr_total, "success": curr_success, "failed": curr_failed},
            "diff": {
                "added_count": len(added_urls), "removed_count": len(removed_urls),
                "modified_count": len(modified),
                "added": list(added_urls), "removed": list(removed_urls),
                "modified": modified, "failures": failures,
            }
        }
        with open(diff_json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        def delta(c, p):
            d = c - p
            return f"+{d}" if d > 0 else str(d)

        added_list   = "\n".join(f"  - [{u}]({u})" for u in sorted(added_urls))   or "  - *None*"
        removed_list = "\n".join(f"  - [{u}]({u})" for u in sorted(removed_urls)) or "  - *None*"
        mod_lines    = [f"  - [{m['url']}]({m['url']}):\n" + "\n".join(f"    * {c}" for c in m["changes"]) for m in modified]
        modified_list = "\n".join(mod_lines) or "  - *None*"
        fail_lines   = [f"  - [{f['url']}]({f['url']}) — `{f['error']}`" for f in failures]
        failed_list  = "\n".join(fail_lines) or "  - *None*"

        md = f"""# WebVac Scan Diff — `{slug}`

*Generated on {timestamp}*

## Scan Overview

| Metric | Previous (`{prev_session}`) | Current | Change |
|---|---|---|---|
| **Total Pages** | {prev_total} | {curr_total} | {delta(curr_total, prev_total)} |
| **Success** | {prev_success} | {curr_success} | {delta(curr_success, prev_success)} |
| **Failed/Blocked** | {prev_failed} | {curr_failed} | {delta(curr_failed, prev_failed)} |

## Changes

* **Added Pages ({len(added_urls)})**:
{added_list}

* **Removed Pages ({len(removed_urls)})**:
{removed_list}

* **Modified Pages ({len(modified)})**:
{modified_list}

## Current Failures & Blocks ({len(failures)})

{failed_list}
"""
        with open(diff_md_path, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"\n[Diff] Compared against session {prev_session}:")
        print(f"  Added     : {len(added_urls)} page(s)")
        print(f"  Removed   : {len(removed_urls)} page(s)")
        print(f"  Modified  : {len(modified)} page(s)")
        print(f"  Failures  : {len(failures)} page(s)")
        print(f"  Report    -> {os.path.relpath(diff_md_path)}")
