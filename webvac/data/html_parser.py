"""
HTML → legacy page record dict parsing (forms, links, meta, etc.).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from webvac.auth.default_creds import DefaultCredsChecker

_creds_checker = DefaultCredsChecker()

_SOCIAL_DOMAINS = (
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com", "github.com",
    "pinterest.com", "reddit.com", "snapchat.com", "telegram.org",
    "whatsapp.com", "discord.com",
)


class HtmlPageParser:
    """Parses rendered HTML into the legacy scrape page dict schema."""

    def __init__(
        self,
        extract_css: Optional[list[str]] = None,
        extract_xpath: Optional[list[str]] = None,
    ) -> None:
        self.css_selectors: dict[str, str] = {}
        for item in extract_css or []:
            if "=" in item:
                k, v = item.split("=", 1)
                self.css_selectors[k] = v

        self.xpath_selectors: dict[str, str] = {}
        for item in extract_xpath or []:
            if "=" in item:
                k, v = item.split("=", 1)
                self.xpath_selectors[k] = v

    def build_from_html(
        self,
        html: str,
        *,
        page_url: str,
        base_url: str,
        server_header: str = "",
    ) -> dict:
        soup = BeautifulSoup(html, "lxml")
        title = self._title(soup)
        targeted_data = self._targeted_data(html, soup)

        return {
            "url": page_url,
            "targeted_data": targeted_data,
            "status": "success",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "meta": self._meta(soup),
            "open_graph": self._open_graph(soup),
            "twitter_card": self._twitter_card(soup),
            "structured_data": self._json_ld(soup),
            "headings": self._headings(soup),
            "paragraphs": self._paragraphs(soup),
            "links": self._links(soup, base_url),
            "images": self._images(soup, base_url),
            "tables": self._tables(soup),
            "lists": self._lists(soup),
            "forms": self._forms(soup),
            "media": self._media(soup, base_url),
            "code_blocks": self._code_blocks(soup),
            "emails": self._emails(soup),
            "phone_numbers": self._phones(soup),
            "social_links": self._social_links(soup),
            "word_count": self._word_count(soup),
            "default_creds": self._check_default_creds(page_url, title, server_header),
            "screenshot": None,
        }

    def _targeted_data(self, html: str, soup) -> dict:
        targeted: dict = {}
        for key, sel in self.css_selectors.items():
            elements = soup.select(sel)
            targeted[key] = [el.get_text(strip=True) for el in elements]

        if self.xpath_selectors:
            from lxml import html as lxml_html

            tree = lxml_html.fromstring(html)
            for key, xpath in self.xpath_selectors.items():
                try:
                    elements = tree.xpath(xpath)
                    extracted = []
                    for el in elements:
                        if hasattr(el, "text_content"):
                            extracted.append(el.text_content().strip())
                        elif isinstance(el, str):
                            extracted.append(el.strip())
                    targeted[key] = extracted
                except Exception as e:
                    targeted[key] = f"XPath Error: {str(e)}"
        return targeted

    @staticmethod
    def _title(soup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _word_count(soup) -> int:
        return len(soup.get_text(separator=" ").split())

    def _check_default_creds(self, url: str, title: str, server_header: str) -> list[dict]:
        matches = _creds_checker.check(url=url, title=title, server_header=server_header)
        if matches:
            for m in matches:
                print(
                    f"[DefaultCreds] ⚠  Possible default credentials on {url}\n"
                    f"               Vendor: {m['vendor']} / {m['panel']}\n"
                    f"               Login:  {m['username']} / {m['password']}"
                )
        return matches

    @staticmethod
    def _meta(soup) -> dict:
        meta = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content = tag.get("content")
            if name and content:
                meta[name] = content
        return meta

    @staticmethod
    def _open_graph(soup) -> dict:
        og = {}
        for tag in soup.find_all("meta", property=re.compile(r"^og:")):
            key = tag.get("property", "").replace("og:", "")
            og[key] = tag.get("content", "")
        return og

    @staticmethod
    def _twitter_card(soup) -> dict:
        tc = {}
        for tag in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
            key = tag.get("name", "").replace("twitter:", "")
            tc[key] = tag.get("content", "")
        return tc

    @staticmethod
    def _json_ld(soup) -> list:
        results = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                results.append(json.loads(tag.string or "{}"))
            except json.JSONDecodeError:
                pass
        return results

    @staticmethod
    def _headings(soup) -> dict:
        headings = {}
        for level in range(1, 7):
            tags = soup.find_all(f"h{level}")
            texts = [t.get_text(strip=True) for t in tags if t.get_text(strip=True)]
            if texts:
                headings[f"h{level}"] = texts
        return headings

    @staticmethod
    def _paragraphs(soup) -> list:
        return [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True)
        ]

    @staticmethod
    def _lists(soup) -> list:
        result = []
        for lst in soup.find_all(["ul", "ol"]):
            items = [li.get_text(strip=True) for li in lst.find_all("li") if li.get_text(strip=True)]
            if items:
                result.append({"type": lst.name, "items": items})
        return result

    @staticmethod
    def _code_blocks(soup) -> list:
        blocks = []
        for tag in soup.find_all(["pre", "code"]):
            text = tag.get_text(strip=True)
            if text:
                blocks.append({
                    "tag": tag.name,
                    "language": tag.get("class", [""])[0] if tag.get("class") else "",
                    "content": text,
                })
        return blocks

    @staticmethod
    def _looks_like_honeypot(tag) -> bool:
        """True if the link (or an ancestor) looks invisible / trap-like to humans."""
        honeypot_class_bits = (
            "honeypot",
            "honey-pot",
            "hidden-link",
            "visually-hidden",
            "sr-only",
            "screen-reader",
            "display-none",
            "u-hidden",
            "is-hidden",
        )

        def _node_hidden(node) -> bool:
            if node is None or not getattr(node, "name", None):
                return False
            if node.get("hidden") is not None:
                return True
            if str(node.get("aria-hidden", "")).lower() == "true":
                return True
            style = (node.get("style") or "").lower().replace(" ", "")
            if "display:none" in style or "visibility:hidden" in style:
                return True
            if "opacity:0" in style or "opacity:0.0" in style:
                return True
            if "left:-" in style or "top:-999" in style or "left:-999" in style:
                return True
            if "font-size:0" in style or "height:0" in style or "width:0" in style:
                return True
            classes = " ".join(node.get("class") or []).lower()
            if any(bit in classes for bit in honeypot_class_bits):
                return True
            # Extremely common trap: class exactly "hidden"
            class_list = [c.lower() for c in (node.get("class") or [])]
            if "hidden" in class_list or "invisible" in class_list:
                return True
            return False

        if _node_hidden(tag):
            return True
        for parent in list(tag.parents)[:8]:
            if getattr(parent, "name", None) in (None, "[document]", "html", "body"):
                break
            if _node_hidden(parent):
                return True
        return False

    @staticmethod
    def _links(soup, base_url: str) -> list:
        seen = set()
        links = []
        origin = urlparse(base_url).netloc
        for tag in soup.find_all("a", href=True):
            if HtmlPageParser._looks_like_honeypot(tag):
                continue
            href = tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(base_url, href)
            if full in seen:
                continue
            seen.add(full)
            link_type = "internal" if urlparse(full).netloc == origin else "external"
            links.append({
                "url": full,
                "text": tag.get_text(strip=True),
                "type": link_type,
                "rel": tag.get("rel", []),
            })
        return links

    @staticmethod
    def _images(soup, base_url: str) -> list:
        images = []
        for tag in soup.find_all("img"):
            src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
            if not src:
                continue
            images.append({
                "src": urljoin(base_url, src),
                "alt": tag.get("alt", ""),
                "title": tag.get("title", ""),
                "width": tag.get("width", ""),
                "height": tag.get("height", ""),
            })
        return images

    @staticmethod
    def _tables(soup) -> list:
        tables = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    if headers and len(cells) == len(headers):
                        rows.append(dict(zip(headers, cells)))
                    else:
                        rows.append(cells)
            if rows:
                tables.append({"headers": headers, "rows": rows})
        return tables

    @staticmethod
    def _forms(soup) -> list:
        forms = []
        for form in soup.find_all("form"):
            fields = []
            for inp in form.find_all(["input", "textarea", "select"]):
                fields.append({
                    "tag": inp.name,
                    "type": inp.get("type", "text"),
                    "name": inp.get("name", ""),
                    "id": inp.get("id", ""),
                    "placeholder": inp.get("placeholder", ""),
                    "required": inp.has_attr("required"),
                })
            forms.append({
                "action": form.get("action", ""),
                "method": form.get("method", "get").upper(),
                "fields": fields,
            })
        return forms

    @staticmethod
    def _media(soup, base_url: str) -> dict:
        videos, audios, iframes = [], [], []
        for tag in soup.find_all("video"):
            src = tag.get("src") or (tag.find("source") and tag.find("source").get("src"))
            if src:
                videos.append(urljoin(base_url, src))
        for tag in soup.find_all("audio"):
            src = tag.get("src") or (tag.find("source") and tag.find("source").get("src"))
            if src:
                audios.append(urljoin(base_url, src))
        for tag in soup.find_all("iframe"):
            src = tag.get("src", "")
            if src:
                iframes.append(src)
        return {"videos": videos, "audios": audios, "iframes": iframes}

    @staticmethod
    def _emails(soup) -> list:
        text = soup.get_text()
        pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        return list(set(re.findall(pattern, text)))

    @staticmethod
    def _phones(soup) -> list:
        text = soup.get_text()
        pattern = r"(\+?\d[\d\s\-().]{7,}\d)"
        raw = re.findall(pattern, text)
        return list(set(r.strip() for r in raw if len(re.sub(r"\D", "", r)) >= 7))

    @staticmethod
    def _social_links(soup) -> list:
        social = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            for domain in _SOCIAL_DOMAINS:
                if domain in href:
                    social.append({"platform": domain.split(".")[0], "url": href})
                    break
        return social
