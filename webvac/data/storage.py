"""
storage.py — Save scraped data to JSON, CSV, Markdown, SQLite, and HTML.

Folder structure:

    scraped_data/
        <domain>_<target_id>/
            scans/
                <YYYYMMDD_HHMMSS>_<scan_id>/
                    scrape/     report.html, data.json, ...
                    network/    network debug dumps
                    assets/     pdfs/, sourcemaps/, screenshots/
                    meta/       session.json, meta.json

Legacy fallback (no scan metadata): scraped_data/<slug>/<timestamp>/
"""

import json
import csv
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from webvac.models.scan import ScanMetadata
from webvac.store.scan_session import ScanSession


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
        scan: Optional[ScanMetadata] = None,
        *,
        interrupted: bool = False,
        assets_meta: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        Save a list of page dicts in the requested formats.
        Returns a dict mapping format name → saved file path.
        """
        if not data:
            print("[Storage] No data to save.")
            return {}

        formats = formats or (["json", "html"] if data else [])
        slug = label or (self._url_slug(data[0].get("url", "scrape")) if data else (scan.target.domain if scan else "scrape"))
        report_ts_fmt = self._report_ts_fmt(scan)

        if scan:
            session = ScanSession(self.output_dir, scan)
            session.ensure_dirs()
            layout = session.layout_paths()
            session_dir = session.session_dir
            scrape_dir = layout["scrape"]
            meta_dir = layout["meta"]
            session_key = session.session_name
            paths: dict[str, str] = {
                "meta": session.write_meta(
                    slug,
                    interrupted=interrupted,
                    origin_access=(assets_meta or {}).get("origin_access"),
                ),
            }
        else:
            session_key = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = os.path.join(self.output_dir, slug, session_key)
            scrape_dir = session_dir
            meta_dir = session_dir
            os.makedirs(session_dir, exist_ok=True)
            paths = {}

        _writers = {
            "json":     lambda d, _: self._save_json(d, scrape_dir),
            "csv":      lambda d, _: self._save_csv(d, scrape_dir),
            "markdown": lambda d, _: self._save_markdown(d, scrape_dir, slug, report_ts_fmt),
            "sqlite":   lambda d, _: self._save_sqlite(d, scrape_dir, slug),
            "html":     lambda d, _: self._save_html(
                d, scrape_dir, slug, report_ts_fmt,
                interrupted=interrupted, assets_meta=assets_meta,
            ),
        }

        for fmt in formats:
            writer = _writers.get(fmt)
            if writer:
                paths[fmt] = writer(data, None)

        paths["session_dir"] = session_dir

        saved = f"{len(data)} page(s)" if data else "session"
        status = " (partial — interrupted)" if interrupted else ""
        print(f"\n[Storage] Saved {saved}{status} -> {session_dir}")
        for fmt, path in paths.items():
            if fmt == "session_dir":
                continue
            rel = os.path.relpath(path, self.output_dir)
            print(f"  {fmt.upper():8s} -> {rel}")
        return paths

    @staticmethod
    def _report_ts_fmt(scan: Optional[ScanMetadata]) -> str:
        if scan and scan.started_at:
            try:
                dt = datetime.fromisoformat(scan.started_at.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _write_json_file(path: str, data: Any) -> str:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

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

    def _save_markdown(self, data: list[dict], session_dir: str, slug: str, ts_fmt: str) -> str:
        """Generate a readable Markdown document — one section per scraped page."""
        path = os.path.join(session_dir, "report.md")
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

    def _save_html(
        self,
        data: list[dict],
        session_dir: str,
        slug: str,
        ts_fmt: str,
        *,
        interrupted: bool = False,
        assets_meta: Optional[dict[str, Any]] = None,
    ) -> str:
        """Generate a self-contained, beautiful interactive HTML report."""
        path = os.path.join(session_dir, "report.html")
        assets_meta = assets_meta or {}
        pdf_count = assets_meta.get("pdfs_downloaded", 0)
        sm_count = assets_meta.get("sourcemaps_exported", 0)

        total   = len(data)
        success = sum(1 for p in data if p.get("status", "success") == "success")
        auth_walls = sum(1 for p in data if p.get("status") == "auth_wall")
        failed  = sum(1 for p in data if p.get("status") == "failed")
        # Treat unknown non-success statuses as failed for the counter
        other_fail = total - success - auth_walls - failed
        failed += max(0, other_fail)
        total_words = sum(p.get("word_count", 0) for p in data)
        total_links = sum(len(p.get("links", [])) for p in data)
        total_images = sum(len(p.get("images", [])) for p in data)

        interrupt_banner = ""
        if interrupted:
            interrupt_banner = """
      <div class="interrupt-banner">
        <strong>⚠ Scan interrupted</strong> — partial results saved from pages completed before Ctrl+C.
      </div>"""
        assets_banner = ""
        if pdf_count or sm_count:
            assets_banner = f"""
      <div class="assets-banner">
        <div class="assets-title">📦 Collected Assets</div>
        <div class="assets-pills">
          {"<span class='asset-pill'>📄 " + str(pdf_count) + " PDF(s)</span>" if pdf_count else ""}
          {"<span class='asset-pill'>🗺 " + str(sm_count) + " source map(s)</span>" if sm_count else ""}
        </div>
        <div class="assets-hint">See <code>assets/pdfs/</code> and <code>assets/sourcemaps/</code> in this scan folder.</div>
      </div>"""
        # ── Sidebar nav items ─────────────────────────────────────────────────
        nav_items = ""
        for i, page in enumerate(data):
            title = (page.get("title") or page.get("url", "Page"))[:45]
            status = page.get("status", "success")
            dot_cls = (
                "dot-ok" if status == "success"
                else "dot-skip" if status == "auth_wall"
                else "dot-fail"
            )
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

            if status == "success":
                status_badge = '<span class="badge badge-ok">✓ Success</span>'
            elif status == "auth_wall":
                status_badge = (
                    '<span class="badge badge-skip">⊘ Auth wall (skipped)</span>'
                )
            else:
                status_badge = (
                    f'<span class="badge badge-fail">✗ '
                    f'{self._esc(page.get("error","Failed"))}</span>'
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

            # Forms table
            forms_html = ""
            if forms:
                form_rows = ""
                for form in forms:
                    fields = form.get("fields") or []
                    fnames = ", ".join(f.get("name") or f.get("type", "?") for f in fields[:5])
                    form_rows += (
                        f"<tr><td>{self._esc(form.get('method','GET'))}</td>"
                        f"<td>{self._esc(form.get('action',''))}</td>"
                        f"<td>{self._esc(fnames)}</td></tr>"
                    )
                forms_html = (
                    "<table class='link-table'><thead><tr><th>Method</th><th>Action</th>"
                    f"<th>Fields</th></tr></thead><tbody>{form_rows}</tbody></table>"
                )

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
                    {"<button class='tab-btn' onclick=\"switchTab(this, 'forms-" + str(i) + "')\">Forms (" + str(len(forms)) + ")</button>" if forms else ""}
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

                {"<div class='tab-panel hidden' id='forms-" + str(i) + "'>" + forms_html + "</div>" if forms else ""}

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
    --bg:       #0a0e14;
    --surface:  #121820;
    --surface2: #1a2230;
    --border:   #2d3748;
    --accent:   #00d4aa;
    --accent2:  #ff6b4a;
    --ok:       #34d399;
    --fail:     #f87171;
    --warn:     #fbbf24;
    --text:     #e8edf4;
    --muted:    #7a8a9e;
    --font:     'Segoe UI', system-ui, -apple-system, sans-serif;
    --mono:     'Cascadia Code', 'Fira Code', 'Courier New', monospace;
    --radius:   12px;
    --shadow:   0 4px 24px rgba(0,0,0,0.45);
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
    background: linear-gradient(90deg, #0a0e14 0%, #121820 50%, #0f1a24 100%);
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
    background: linear-gradient(135deg, #00d4aa, #ff6b4a);
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
  .nav-item.active {{ background: rgba(0,212,170,0.12); border-color: rgba(0,212,170,0.35); color: var(--accent); }}
  .nav-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
  .dot-ok   {{ background: var(--ok); box-shadow: 0 0 6px var(--ok); }}
  .dot-fail {{ background: var(--fail); box-shadow: 0 0 6px var(--fail); }}
  .dot-skip {{ background: var(--warn); box-shadow: 0 0 6px var(--warn); }}
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
  .stat-purple .stat-val {{ background: linear-gradient(135deg, #00d4aa, #ff6b4a); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}

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
  .badge-skip {{ background: rgba(251,191,36,0.15); color: var(--warn); border: 1px solid rgba(251,191,36,0.35); }}

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
  .link-table tr:hover td {{ background: rgba(0,212,170,0.06); }}
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
  .meta-table tr:hover td {{ background: rgba(0,212,170,0.06); }}

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

  .interrupt-banner {{
    background: rgba(251,191,36,0.12);
    border: 1px solid rgba(251,191,36,0.45);
    border-radius: var(--radius);
    padding: 12px 18px;
    margin-bottom: 16px;
    color: var(--warn);
    font-size: 13px;
  }}
  .assets-banner {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 18px;
    margin-bottom: 20px;
  }}
  .assets-title {{ font-weight: 700; margin-bottom: 8px; }}
  .assets-pills {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }}
  .asset-pill {{
    padding: 4px 12px;
    border-radius: 16px;
    font-size: 12px;
    background: rgba(0,212,170,0.12);
    border: 1px solid rgba(0,212,170,0.3);
    color: var(--accent);
  }}
  .assets-hint {{ font-size: 11px; color: var(--muted); }}
  .assets-hint code {{ background: var(--surface2); padding: 2px 6px; border-radius: 4px; }}
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

      {interrupt_banner}
      {assets_banner}

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
        <div class="stat-card">
          <div class="stat-val" style="color:var(--warn)">{auth_walls}</div>
          <div class="stat-lbl">Auth Walls Skipped</div>
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
        {"<div class='stat-card stat-blue'><div class='stat-val'>" + str(pdf_count) + "</div><div class='stat-lbl'>PDFs Saved</div></div>" if pdf_count else ""}
        {"<div class='stat-card stat-blue'><div class='stat-val'>" + str(sm_count) + "</div><div class='stat-lbl'>Source Maps</div></div>" if sm_count else ""}
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
            else '<span style="color:var(--warn);font-weight:600">⊘</span>'
            if status == "auth_wall"
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


