"""
VAPT recon report generation — findings, technology profile, endpoints.

Used by Storage.save() when recon analysis data is provided.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_SEVERITY_COLORS = {
    "CRITICAL": "#ef4444",
    "HIGH": "#f97316",
    "MEDIUM": "#f59e0b",
    "LOW": "#3b82f6",
    "INFO": "#6b7280",
}


class ReconReportWriter:
    def __init__(self, esc_fn) -> None:
        self._esc = esc_fn

    def save_json(self, recon: dict[str, Any], session_dir: str) -> str:
        path = os.path.join(session_dir, "recon.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(recon, f, ensure_ascii=False, indent=2)
        return path

    def save_markdown(self, recon: dict[str, Any], session_dir: str, slug: str) -> str:
        path = os.path.join(session_dir, "recon_report.md")
        session = recon.get("session", {})
        findings = recon.get("findings", [])
        fc = recon.get("findings_count", {})
        tech = recon.get("technology_profile", {})
        lines = [
            f"# WebVac Recon Report — `{slug}`\n",
            f"**Target:** {session.get('seed_url', '')}  ",
            f"**Mode:** {session.get('mode', 'passive')}  ",
            f"**Profile:** {session.get('profile', '')}  ",
            f"**Scan ID:** `{session.get('scan_id', '')}`\n",
            "## Findings Summary\n",
        ]
        for sev in _SEVERITY_ORDER:
            if fc.get(sev):
                lines.append(f"- **{sev}**: {fc[sev]}")
        lines.append(f"\n## Findings ({len(findings)})\n")
        for f in sorted(findings, key=lambda x: _SEVERITY_ORDER.index(x.get("severity", "INFO")) if x.get("severity") in _SEVERITY_ORDER else 99):
            lines.append(f"### [{f.get('severity')}] {f.get('title')}\n")
            lines.append(f"{f.get('description', '')}\n")
            if f.get("remediation"):
                lines.append(f"**Remediation:** {f['remediation']}\n")
            urls = f.get("affected_urls") or []
            if urls:
                lines.append("**Affected:** " + ", ".join(f"`{u}`" for u in urls[:5]))
                if len(urls) > 5:
                    lines.append(f" (+{len(urls)-5} more)")
                lines.append("")
        if tech:
            lines.append("\n## Technology Profile\n")
            for role in ("server", "framework", "frontend", "cms", "cdn", "waf"):
                entry = tech.get(role)
                if entry:
                    name = entry.get("name", entry) if isinstance(entry, dict) else entry
                    lines.append(f"- **{role.title()}**: {name}")
            for label, key in (("Analytics", "analytics"), ("Payments", "payments"), ("Third party", "third_party")):
                vals = tech.get(key) or []
                if vals:
                    lines.append(f"- **{label}**: {', '.join(vals)}")
        tree = recon.get("endpoint_tree") or []
        if tree:
            lines.append("\n## Endpoint Tree\n```")
            lines.extend(tree[:80])
            lines.append("```\n")
        active = recon.get("active_recon", {})
        probes = active.get("probe_results") or []
        if probes:
            lines.append(f"\n## Active Recon ({len(probes)} hits)\n")
            for p in probes[:30]:
                lines.append(f"- `{p.get('url')}` — HTTP {p.get('status')} ({p.get('probe_name')})")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path

    def save_html(
        self,
        recon: dict[str, Any],
        pages: list[dict],
        session_dir: str,
        slug: str,
        timestamp: str,
    ) -> str:
        path = os.path.join(session_dir, "recon_report.html")
        session = recon.get("session", {})
        ts_fmt = self._format_report_time(session, timestamp)
        findings = recon.get("findings", [])
        fc = recon.get("findings_count", {})
        tech = recon.get("technology_profile", {})
        intelligence = recon.get("intelligence", [])
        active = recon.get("active_recon", {})
        tree_lines = recon.get("endpoint_tree") or []

        fc_cards = ""
        for sev in _SEVERITY_ORDER:
            count = fc.get(sev, 0)
            color = _SEVERITY_COLORS[sev]
            fc_cards += f"""
            <div class="sev-card" style="border-color:{color}40">
              <div class="sev-val" style="color:{color}">{count}</div>
              <div class="sev-lbl">{sev}</div>
            </div>"""

        findings_html = ""
        sorted_findings = sorted(
            findings,
            key=lambda f: _SEVERITY_ORDER.index(f.get("severity", "INFO"))
            if f.get("severity") in _SEVERITY_ORDER
            else 99,
        )
        for f in sorted_findings:
            sev = f.get("severity", "INFO")
            color = _SEVERITY_COLORS.get(sev, "#6b7280")
            urls = f.get("affected_urls") or []
            urls_html = "".join(
                f'<li><a href="{self._esc(u)}" target="_blank">{self._esc(u)}</a></li>'
                for u in urls[:8]
            )
            if len(urls) > 8:
                urls_html += f"<li><em>+{len(urls)-8} more</em></li>"
            findings_html += f"""
            <div class="finding-card" style="border-left:4px solid {color}">
              <div class="finding-head">
                <span class="sev-badge" style="background:{color}22;color:{color}">{self._esc(sev)}</span>
                <span class="finding-id">{self._esc(f.get('id',''))}</span>
              </div>
              <h3 class="finding-title">{self._esc(f.get('title',''))}</h3>
              <p class="finding-desc">{self._esc(f.get('description',''))}</p>
              {f'<p class="finding-remediation"><strong>Remediation:</strong> {self._esc(f.get("remediation",""))}</p>' if f.get('remediation') else ''}
              {f'<ul class="finding-urls">{urls_html}</ul>' if urls_html else ''}
            </div>"""

        tech_html = self._render_tech_profile(tech)
        intel_html = self._render_intelligence_summary(intelligence)
        forms_html = self._render_forms(pages)
        probes_html = self._render_probes(active.get("probe_results") or [])
        tree_html = "<br>".join(self._esc(line) for line in tree_lines[:100]) if tree_lines else "<em>No endpoint graph data.</em>"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WebVac Recon — {self._esc(slug)}</title>
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#0a0e14;--surface:#121820;--surface2:#1a2230;--border:#2d3748;
    --text:#e8edf4;--muted:#7a8a9e;--accent:#00d4aa;--accent2:#ff6b4a;--radius:10px;
    --font:'Segoe UI',system-ui,sans-serif;--mono:'Cascadia Code',monospace;
  }}
  body{{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.55;font-size:14px}}
  a{{color:var(--accent)}}
  .topbar{{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:50}}
  .logo{{font-size:18px;font-weight:800;background:linear-gradient(135deg,#00d4aa,#ff6b4a);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
  .topbar a.btn{{margin-left:auto;padding:8px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);text-decoration:none;font-size:13px}}
  .wrap{{max-width:1100px;margin:0 auto;padding:24px 20px 60px}}
  h1{{font-size:26px;margin-bottom:6px}}
  .sub{{color:var(--muted);margin-bottom:24px;font-size:13px}}
  .meta-row{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:28px}}
  .chip{{background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:5px 12px;font-size:12px;color:var(--muted)}}
  .sev-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:12px;margin-bottom:28px}}
  .sev-card{{background:var(--surface);border:1px solid;border-radius:var(--radius);padding:16px;text-align:center}}
  .sev-val{{font-size:28px;font-weight:800}}
  .sev-lbl{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:4px}}
  section{{margin-bottom:36px}}
  h2{{font-size:16px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)}}
  .finding-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;margin-bottom:12px}}
  .finding-head{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
  .sev-badge{{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700}}
  .finding-id{{font-family:var(--mono);font-size:11px;color:var(--muted)}}
  .finding-title{{font-size:16px;margin-bottom:6px}}
  .finding-desc{{color:var(--muted);font-size:13px}}
  .finding-remediation{{font-size:13px;margin-top:10px;padding:10px;background:var(--surface2);border-radius:8px}}
  .finding-urls{{margin-top:8px;padding-left:18px;font-size:12px}}
  .tech-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}}
  .tech-item{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px}}
  .tech-role{{font-size:10px;text-transform:uppercase;color:var(--muted);letter-spacing:.5px}}
  .tech-name{{font-weight:600;margin-top:4px}}
  .tree-box{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px;font-family:var(--mono);font-size:12px;line-height:1.7;overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border)}}
  th{{color:var(--muted);font-size:11px;text-transform:uppercase;background:var(--surface2)}}
  tr:hover td{{background:var(--surface2)}}
  .empty{{color:var(--muted);font-style:italic;padding:20px;text-align:center}}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">⚡ WebVac Recon</div>
  <a class="btn" href="../scrape/report.html">← Scrape Report</a>
</div>
<div class="wrap">
  <h1>Reconnaissance Report</h1>
  <p class="sub">{self._esc(slug)} · {self._esc(ts_fmt)}</p>
  <div class="meta-row">
    <span class="chip">🎯 {self._esc(session.get('seed_url',''))}</span>
    <span class="chip">📋 {self._esc(session.get('profile',''))}</span>
    <span class="chip">🔍 {self._esc(session.get('mode','passive'))}</span>
    <span class="chip">📄 {session.get('pages_visited',0)} pages</span>
    <span class="chip">🧠 {recon.get('observations_count',0)} observations</span>
  </div>

  <section>
    <h2>Findings Summary</h2>
    <div class="sev-grid">{fc_cards}</div>
    {findings_html if findings_html else '<p class="empty">No security findings generated.</p>'}
  </section>

  <section>
    <h2>Technology Profile</h2>
    {tech_html}
  </section>

  <section>
    <h2>Forms Discovered</h2>
    {forms_html}
  </section>

  <section>
    <h2>Endpoint Graph</h2>
    <div class="tree-box">{tree_html}</div>
  </section>

  <section>
    <h2>Intelligence Highlights</h2>
    {intel_html}
  </section>

  <section>
    <h2>Active Reconnaissance</h2>
    {probes_html if active.get('enabled') else '<p class="empty">Passive scan only — active recon was not enabled.</p>'}
  </section>
</div>
</body>
</html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def _render_tech_profile(self, tech: dict) -> str:
        if not tech:
            return '<p class="empty">No technology fingerprint available.</p>'
        items = []
        for role in ("server", "framework", "frontend", "cms", "cdn", "waf"):
            entry = tech.get(role)
            if entry:
                name = entry.get("name", str(entry)) if isinstance(entry, dict) else str(entry)
                conf = entry.get("confidence", "") if isinstance(entry, dict) else ""
                conf_str = f" <span style='color:var(--muted);font-size:11px'>({conf:.0%})</span>" if isinstance(conf, float) else ""
                items.append(f'<div class="tech-item"><div class="tech-role">{role}</div><div class="tech-name">{self._esc(name)}{conf_str}</div></div>')
        for label, key in (("Analytics", "analytics"), ("Payments", "payments"), ("Third Party", "third_party")):
            for name in tech.get(key) or []:
                items.append(f'<div class="tech-item"><div class="tech-role">{label}</div><div class="tech-name">{self._esc(name)}</div></div>')
        return f'<div class="tech-grid">{"".join(items)}</div>' if items else '<p class="empty">No technologies detected.</p>'

    def _render_intelligence_summary(self, intelligence: list) -> str:
        if not intelligence:
            return '<p class="empty">No intelligence items.</p>'
        by_cat: dict[str, int] = {}
        for item in intelligence:
            cat = item.get("category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        rows = "".join(
            f"<tr><td>{self._esc(cat)}</td><td>{count}</td></tr>"
            for cat, count in sorted(by_cat.items(), key=lambda x: -x[1])
        )
        highlights = []
        priority_cats = {"secret", "endpoint", "auth", "cloud", "graphql"}
        for item in intelligence:
            if item.get("category") in priority_cats and len(highlights) < 25:
                highlights.append(
                    f"<tr><td>{self._esc(item.get('category',''))}</td>"
                    f"<td><code>{self._esc(str(item.get('key','')))}</code></td>"
                    f"<td>{self._esc(str(item.get('value',''))[:80])}</td>"
                    f"<td>{self._esc(item.get('affected_url','')[:60])}</td></tr>"
                )
        highlight_table = ""
        if highlights:
            highlight_table = f"""
            <h3 style="font-size:13px;margin:16px 0 8px;color:var(--muted)">Notable observations</h3>
            <table><thead><tr><th>Category</th><th>Key</th><th>Value</th><th>URL</th></tr></thead>
            <tbody>{''.join(highlights)}</tbody></table>"""
        return f"""
        <table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>{rows}</tbody></table>
        {highlight_table}"""

    def _render_forms(self, pages: list[dict]) -> str:
        all_forms = []
        for page in pages:
            for form in page.get("forms") or []:
                all_forms.append((page.get("url", ""), form))
        if not all_forms:
            return '<p class="empty">No HTML forms discovered.</p>'
        rows = ""
        for page_url, form in all_forms[:40]:
            action = form.get("action", "")
            method = form.get("method", "GET")
            fields = form.get("fields") or []
            field_summary = ", ".join(
                f"{f.get('name') or f.get('type','?')}" for f in fields[:6]
            )
            if len(fields) > 6:
                field_summary += f" (+{len(fields)-6})"
            rows += f"<tr><td>{self._esc(method)}</td><td>{self._esc(action)}</td><td>{self._esc(field_summary)}</td><td><a href='{self._esc(page_url)}' target='_blank'>{self._esc(page_url[:50])}</a></td></tr>"
        return f"""<table>
          <thead><tr><th>Method</th><th>Action</th><th>Fields</th><th>Page</th></tr></thead>
          <tbody>{rows}</tbody></table>"""

    def _render_probes(self, probes: list[dict]) -> str:
        if not probes:
            return '<p class="empty">No successful active probes.</p>'
        rows = ""
        for p in probes:
            if p.get("status") not in (200, 201, 204):
                continue
            rows += (
                f"<tr><td>{self._esc(p.get('probe_name',''))}</td>"
                f"<td><a href='{self._esc(p.get('url',''))}' target='_blank'>{self._esc(p.get('url',''))}</a></td>"
                f"<td>{p.get('status')}</td>"
                f"<td>{self._esc(p.get('content_type','')[:40])}</td></tr>"
            )
        return f"""<table>
          <thead><tr><th>Probe</th><th>URL</th><th>Status</th><th>Type</th></tr></thead>
          <tbody>{rows}</tbody></table>"""

    @staticmethod
    def _format_report_time(session: dict, timestamp: str) -> str:
        started = session.get("started_at")
        if started:
            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                return dt.strftime("%B %d, %Y at %H:%M:%S")
            except ValueError:
                pass
        if len(timestamp) == 15 and timestamp[8] == "_":
            try:
                return datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime(
                    "%B %d, %Y at %H:%M:%S"
                )
            except ValueError:
                pass
        return timestamp
