"""
extractor.py — Universal data extractor.
Pulls every meaningful data type from a rendered page.
"""

import re
import json
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from patchright.async_api import Page
from auth.default_creds import DefaultCredsChecker

_creds_checker = DefaultCredsChecker()


from typing import Optional

class Extractor:
    """Extracts all data types from a Playwright page."""

    def __init__(self, extract_css: Optional[list[str]] = None, extract_xpath: Optional[list[str]] = None):
        self.css_selectors = {}
        for item in (extract_css or []):
            if "=" in item:
                k, v = item.split("=", 1)
                self.css_selectors[k] = v
                
        self.xpath_selectors = {}
        for item in (extract_xpath or []):
            if "=" in item:
                k, v = item.split("=", 1)
                self.xpath_selectors[k] = v

    async def extract(self, page: Page, base_url: str, server_header: str = "") -> dict:
        """Run all extractors and return a unified data dict."""
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        url = page.url
        title = self._title(soup)

        targeted_data = {}
        # CSS Extraction
        for key, sel in self.css_selectors.items():
            elements = soup.select(sel)
            targeted_data[key] = [el.get_text(strip=True) for el in elements]
            
        # XPath Extraction
        if self.xpath_selectors:
            from lxml import html as lxml_html
            tree = lxml_html.fromstring(html)
            for key, xpath in self.xpath_selectors.items():
                try:
                    elements = tree.xpath(xpath)
                    extracted = []
                    for el in elements:
                        if hasattr(el, 'text_content'):
                            extracted.append(el.text_content().strip())
                        elif isinstance(el, str):
                            extracted.append(el.strip())
                    targeted_data[key] = extracted
                except Exception as e:
                    targeted_data[key] = f"XPath Error: {str(e)}"

        data = {
            "url": url,
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
            # EyeWitness-style default credential check
            "default_creds": self._check_default_creds(url, title, server_header),
            # Filled in by crawler.py if a CAPTCHA screenshot was captured
            "screenshot": None,
        }
        return data

    # ── Basic ────────────────────────────────────────────────────────────────

    def _title(self, soup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    def _word_count(self, soup) -> int:
        text = soup.get_text(separator=" ")
        return len(text.split())

    def _check_default_creds(self, url: str, title: str, server_header: str) -> list[dict]:
        """Check whether the page looks like a known vendor login panel."""
        matches = _creds_checker.check(url=url, title=title, server_header=server_header)
        if matches:
            for m in matches:
                print(
                    f"[DefaultCreds] ⚠  Possible default credentials on {url}\n"
                    f"               Vendor: {m['vendor']} / {m['panel']}\n"
                    f"               Login:  {m['username']} / {m['password']}"
                )
        return matches

    # ── Meta tags ────────────────────────────────────────────────────────────

    def _meta(self, soup) -> dict:
        meta = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content = tag.get("content")
            if name and content:
                meta[name] = content
        return meta

    def _open_graph(self, soup) -> dict:
        og = {}
        for tag in soup.find_all("meta", property=re.compile(r"^og:")):
            key = tag.get("property", "").replace("og:", "")
            og[key] = tag.get("content", "")
        return og

    def _twitter_card(self, soup) -> dict:
        tc = {}
        for tag in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
            key = tag.get("name", "").replace("twitter:", "")
            tc[key] = tag.get("content", "")
        return tc

    def _json_ld(self, soup) -> list:
        results = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                results.append(json.loads(tag.string or "{}"))
            except json.JSONDecodeError:
                pass
        return results

    # ── Content ──────────────────────────────────────────────────────────────

    def _headings(self, soup) -> dict:
        headings = {}
        for level in range(1, 7):
            tags = soup.find_all(f"h{level}")
            texts = [t.get_text(strip=True) for t in tags if t.get_text(strip=True)]
            if texts:
                headings[f"h{level}"] = texts
        return headings

    def _paragraphs(self, soup) -> list:
        return [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True)
        ]

    def _lists(self, soup) -> list:
        result = []
        for lst in soup.find_all(["ul", "ol"]):
            items = [li.get_text(strip=True) for li in lst.find_all("li") if li.get_text(strip=True)]
            if items:
                result.append({
                    "type": lst.name,  # ul or ol
                    "items": items,
                })
        return result

    def _code_blocks(self, soup) -> list:
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

    # ── Links & Images ───────────────────────────────────────────────────────

    def _links(self, soup, base_url: str) -> list:
        seen = set()
        links = []
        origin = urlparse(base_url).netloc
        for tag in soup.find_all("a", href=True):
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

    def _images(self, soup, base_url: str) -> list:
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

    # ── Tables ───────────────────────────────────────────────────────────────

    def _tables(self, soup) -> list:
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

    # ── Forms ────────────────────────────────────────────────────────────────

    def _forms(self, soup) -> list:
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

    # ── Media ────────────────────────────────────────────────────────────────

    def _media(self, soup, base_url: str) -> dict:
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

    # ── Contact Info ─────────────────────────────────────────────────────────

    def _emails(self, soup) -> list:
        text = soup.get_text()
        pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        return list(set(re.findall(pattern, text)))

    def _phones(self, soup) -> list:
        text = soup.get_text()
        pattern = r"(\+?\d[\d\s\-().]{7,}\d)"
        raw = re.findall(pattern, text)
        return list(set(r.strip() for r in raw if len(re.sub(r"\D", "", r)) >= 7))

    def _social_links(self, soup) -> list:
        SOCIAL_DOMAINS = [
            "facebook.com", "twitter.com", "x.com", "instagram.com",
            "linkedin.com", "youtube.com", "tiktok.com", "github.com",
            "pinterest.com", "reddit.com", "snapchat.com", "telegram.org",
            "whatsapp.com", "discord.com",
        ]
        social = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            for domain in SOCIAL_DOMAINS:
                if domain in href:
                    social.append({"platform": domain.split(".")[0], "url": href})
                    break
        return social
