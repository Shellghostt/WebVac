"""HTML DOM collector — forms, links, scripts, comments, meta."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment

from webvac.collectors.base import BaseCollector, CollectorContext
from webvac.models.artifacts import BaseArtifact, FormArtifact, FormField, HtmlArtifact

_HIDDEN_DOM_JS = """
() => {
  const out = [];
  document.querySelectorAll('[hidden], [style*="display:none"], [style*="display: none"], [disabled], [aria-hidden="true"]').forEach(el => {
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      name: el.getAttribute('name') || '',
      type: el.getAttribute('type') || '',
      classes: (el.className && el.className.toString) ? el.className.toString().slice(0, 120) : '',
    });
    if (out.length >= 100) return;
  });
  document.querySelectorAll('[data-feature-flag], [data-flag], [data-testid]').forEach(el => {
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      attr: el.getAttribute('data-feature-flag') || el.getAttribute('data-flag') || el.getAttribute('data-testid') || '',
    });
    if (out.length >= 150) return;
  });
  return out.slice(0, 150);
}
"""


class HtmlCollector(BaseCollector):
    name = "html"

    def supports(self, ctx: CollectorContext) -> bool:
        return ctx.config.get("collectors", {}).get(self.name, False)

    async def collect(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
    ) -> list[BaseArtifact]:
        if page is None:
            return []

        base_url = page.url or ctx.base_url
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        meta: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content = tag.get("content", "")
            if name and content:
                meta[str(name).lower()] = content

        comments = tuple(
            str(c).strip() for c in soup.find_all(string=lambda t: isinstance(t, Comment))
        )

        forms: list[FormArtifact] = []
        for form in soup.find_all("form"):
            fields: list[FormField] = []
            for inp in form.find_all(["input", "textarea", "select"]):
                fields.append(
                    FormField(
                        tag=inp.name or "input",
                        type=inp.get("type", "text"),
                        name=inp.get("name", ""),
                        id=inp.get("id", ""),
                        value=inp.get("value", ""),
                        placeholder=inp.get("placeholder", ""),
                        autocomplete=inp.get("autocomplete", ""),
                        required=inp.has_attr("required"),
                    )
                )
            forms.append(
                FormArtifact(
                    page_url=base_url,
                    action=form.get("action", ""),
                    method=(form.get("method") or "get").upper(),
                    enctype=form.get("enctype", ""),
                    fields=tuple(fields),
                )
            )

        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                links.append(urljoin(base_url, href))

        script_urls: list[str] = []
        inline_scripts: list[str] = []
        for tag in soup.find_all("script"):
            src = tag.get("src")
            if src:
                script_urls.append(urljoin(base_url, src))
            elif tag.string and tag.string.strip():
                inline_scripts.append(tag.string.strip())

        open_graph: dict[str, str] = {}
        twitter_card: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            prop = tag.get("property", "")
            name = tag.get("name", "")
            content = tag.get("content", "")
            if prop.startswith("og:") and content:
                open_graph[prop] = content
            if name.startswith("twitter:") and content:
                twitter_card[name] = content

        canonical = ""
        link_canon = soup.find("link", rel=lambda v: v and "canonical" in v)
        if link_canon and link_canon.get("href"):
            canonical = urljoin(base_url, link_canon["href"])

        hidden_elements: tuple[dict[str, str], ...] = ()
        try:
            raw_hidden = await page.evaluate(_HIDDEN_DOM_JS)
            hidden_elements = tuple(dict(x) for x in (raw_hidden or []))
        except Exception:
            pass

        artifact = HtmlArtifact(
            page_url=base_url,
            raw_html=html,
            title=title,
            meta=meta,
            comments=comments,
            forms=tuple(forms),
            links=tuple(links),
            script_urls=tuple(script_urls),
            inline_scripts=tuple(inline_scripts),
            open_graph=open_graph,
            twitter_card=twitter_card,
            canonical_url=canonical,
            dom_hidden_elements=hidden_elements,
        )
        return [artifact]
