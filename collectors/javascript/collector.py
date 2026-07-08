"""JavaScript file collector — downloads external JS and source maps (session-level)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin, urlparse

import aiohttp

from collectors.base import BaseCollector, CollectorContext
from models.artifacts import (
    ArtifactType,
    BaseArtifact,
    HtmlArtifact,
    JavaScriptArtifact,
    JavaScriptFile,
    SourceMapArtifact,
)

_SOURCEMAP_RE = re.compile(r"//#\s*sourceMappingURL=(\S+)")


class JavascriptCollector(BaseCollector):
    name = "javascript"
    session_level = True

    def supports(self, ctx: CollectorContext) -> bool:
        return ctx.config.get("collectors", {}).get(self.name, False)

    def _cookie_header(self, ctx: CollectorContext) -> str:
        parts = []
        for c in ctx.cookies:
            name = c.get("name")
            value = c.get("value")
            if name:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    async def _fetch(
        self,
        session: aiohttp.ClientSession,
        url: str,
        cookie_header: str,
        proxy: str | None,
    ) -> tuple[str, int]:
        headers = {}
        if cookie_header:
            headers["Cookie"] = cookie_header
        try:
            async with session.get(url, headers=headers, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status >= 400:
                    return "", 0
                text = await resp.text(errors="replace")
                return text, len(text.encode("utf-8"))
        except Exception:
            return "", 0

    def _discover_js_urls(self, ctx: CollectorContext) -> dict[str, set[str]]:
        """url -> set of script URLs."""
        by_page: dict[str, set[str]] = {}
        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if not isinstance(artifact, HtmlArtifact):
                continue
            by_page.setdefault(artifact.page_url, set()).update(artifact.script_urls)
        return by_page

    def _inline_blocks(self, ctx: CollectorContext) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = []
        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if not isinstance(artifact, HtmlArtifact):
                continue
            for script in artifact.inline_scripts:
                blocks.append((artifact.page_url, script))
        return blocks

    async def collect(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
    ) -> list[BaseArtifact]:
        return []

    async def collect_session(self, ctx: CollectorContext) -> list[BaseArtifact]:
        js_cfg = ctx.config.get("javascript", {})
        if not js_cfg.get("download_external", True):
            return await self._session_from_inline_only(ctx)

        concurrency = int(js_cfg.get("concurrency", 5))
        fetch_maps = bool(js_cfg.get("fetch_source_maps", False))
        proxy = ctx.config.get("_proxy_url")
        cookie_header = self._cookie_header(ctx)

        all_urls: set[str] = set()
        for urls in self._discover_js_urls(ctx).values():
            all_urls.update(urls)

        sem = asyncio.Semaphore(concurrency)
        files: list[JavaScriptFile] = []
        source_maps: list[SourceMapArtifact] = []

        async with aiohttp.ClientSession() as session:

            async def fetch_one(url: str, referer: str) -> None:
                async with sem:
                    content, size = await self._fetch(session, url, cookie_header, proxy)
                    if not content:
                        return
                    map_url = None
                    m = _SOURCEMAP_RE.search(content)
                    if m:
                        map_url = urljoin(url, m.group(1).strip())
                    elif fetch_maps:
                        map_url = url + ".map"
                    files.append(
                        JavaScriptFile(
                            url=url,
                            content=content,
                            source_map_url=map_url,
                            size_bytes=size,
                        )
                    )
                    if fetch_maps and map_url:
                        map_content, _ = await self._fetch(session, map_url, cookie_header, proxy)
                        if map_content.strip().startswith("{"):
                            await self._parse_source_map(map_url, url, map_content, source_maps, referer)

            await asyncio.gather(*(fetch_one(u, referer) for referer, urls in self._discover_js_urls(ctx).items() for u in urls))

        inline_blocks = tuple(self._inline_blocks(ctx))
        seed = ctx.scan.target.seed_url
        artifacts: list[BaseArtifact] = [
            JavaScriptArtifact(
                page_url=seed,
                files=tuple(files),
                inline_blocks=inline_blocks,
            )
        ]
        artifacts.extend(source_maps)
        return artifacts

    async def _session_from_inline_only(self, ctx: CollectorContext) -> list[BaseArtifact]:
        seed = ctx.scan.target.seed_url
        return [
            JavaScriptArtifact(
                page_url=seed,
                files=(),
                inline_blocks=tuple(self._inline_blocks(ctx)),
            )
        ]

    async def _parse_source_map(
        self,
        map_url: str,
        js_url: str,
        content: str,
        out: list[SourceMapArtifact],
        page_url: str,
    ) -> None:
        try:
            import json
            data = json.loads(content)
            sources = tuple(data.get("sources") or [])
            sources_content = {}
            raw_content = data.get("sourcesContent") or []
            for i, src in enumerate(sources):
                if i < len(raw_content) and raw_content[i]:
                    sources_content[src] = raw_content[i][:500_000]
            out.append(
                SourceMapArtifact(
                    page_url=page_url,
                    map_url=map_url,
                    js_url=js_url,
                    sources=sources,
                    sources_content=sources_content,
                )
            )
        except Exception:
            pass
