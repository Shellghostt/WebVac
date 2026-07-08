"""
Download crawl-discovered assets (PDFs, etc.) to the session assets folder.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from typing import Optional
from urllib.parse import urlparse, unquote

import aiohttp

_PDF_RE = re.compile(r"\.pdf(?:\?|#|$)", re.I)


def collect_pdf_urls(pages: list[dict]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for page in pages:
        candidates = [page.get("url", "")]
        for link in page.get("links", []):
            candidates.append(link.get("url", ""))
        for raw in candidates:
            if raw and _PDF_RE.search(raw):
                if raw not in seen:
                    seen.add(raw)
                    urls.append(raw)
    return urls


def _safe_filename(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = os.path.basename(path) or "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w.\-]+", "_", stem)[:80]
    return f"{stem}_{digest}{ext}"


class AssetDownloader:
    def __init__(
        self,
        dest_dir: str,
        *,
        timeout: float = 60.0,
        concurrency: int = 4,
    ) -> None:
        self.dest_dir = dest_dir
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.concurrency = max(1, concurrency)
        os.makedirs(dest_dir, exist_ok=True)

    async def download_pdfs(
        self,
        urls: list[str],
        *,
        cookie_header: str = "",
        proxy: Optional[str] = None,
    ) -> list[dict]:
        if not urls:
            return []

        sem = asyncio.Semaphore(self.concurrency)
        results: list[dict] = []

        async def _one(session: aiohttp.ClientSession, url: str) -> None:
            async with sem:
                fname = _safe_filename(url)
                out_path = os.path.join(self.dest_dir, fname)
                if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                    results.append({"url": url, "path": out_path, "status": "cached"})
                    return
                headers = {}
                if cookie_header:
                    headers["Cookie"] = cookie_header
                try:
                    async with session.get(url, headers=headers, proxy=proxy) as resp:
                        if resp.status != 200:
                            results.append({
                                "url": url, "path": "", "status": f"http_{resp.status}",
                            })
                            return
                        data = await resp.read()
                        if len(data) < 100:
                            results.append({
                                "url": url, "path": "", "status": "too_small",
                            })
                            return
                        with open(out_path, "wb") as f:
                            f.write(data)
                        results.append({
                            "url": url, "path": out_path, "status": "ok",
                            "bytes": len(data),
                        })
                except Exception as exc:
                    results.append({
                        "url": url, "path": "", "status": str(type(exc).__name__),
                    })

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            await asyncio.gather(*[_one(session, u) for u in urls])

        ok = sum(1 for r in results if r.get("status") == "ok")
        if urls:
            print(f"[Assets] Downloaded {ok}/{len(urls)} PDF(s) -> {self.dest_dir}")
        return results
