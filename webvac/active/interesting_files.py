"""Well-known sensitive path probes."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from webvac.models.findings import ProbeResult

BODY_PREVIEW = 512

# Paths grouped by probe toggle key in config active_probes
PROBE_PATH_GROUPS: dict[str, list[str]] = {
    "files": [
        "robots.txt",
        "sitemap.xml",
        "security.txt",
        "humans.txt",
        ".well-known/security.txt",
    ],
    "swagger": [
        "api/swagger",
        "api/docs",
        "swagger.json",
        "swagger-ui.html",
        "openapi.json",
        "openapi.yaml",
        "v2/api-docs",
        "v3/api-docs",
    ],
    "git": [
        ".git/HEAD",
        ".git/config",
        ".gitignore",
    ],
    "env": [
        ".env",
        ".env.local",
        ".env.production",
        ".env.backup",
    ],
}


async def probe_interesting_files(
    base_url: str,
    config: dict[str, Any],
    *,
    session: aiohttp.ClientSession | None = None,
) -> list[ProbeResult]:
    probes_cfg = config.get("active_probes", {})
    paths: list[tuple[str, str]] = []
    for group, group_paths in PROBE_PATH_GROUPS.items():
        if probes_cfg.get(group, True):
            for path in group_paths:
                paths.append((group, path))

    if not paths:
        return []

    proxy = config.get("_proxy_url")
    concurrency = int(config.get("active_probe_concurrency", 5))
    delay = float(config.get("active_probe_delay", 0.3))
    sem = asyncio.Semaphore(concurrency)
    results: list[ProbeResult] = []

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    async def probe_one(group: str, path: str) -> None:
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        async with sem:
            try:
                async with session.get(
                    url,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=False,
                ) as resp:
                    body = ""
                    if resp.status in (200, 201, 204):
                        try:
                            raw = await resp.read()
                            body = raw[:BODY_PREVIEW].decode("utf-8", errors="replace")
                        except Exception:
                            pass
                    if resp.status in (200, 201, 204, 401, 403):
                        results.append(
                            ProbeResult(
                                probe_name=f"{group}_probe",
                                url=url,
                                status=resp.status,
                                content_type=resp.headers.get("Content-Type", ""),
                                size_bytes=int(resp.headers.get("Content-Length", 0) or 0),
                                body_preview=body,
                                metadata={"path": path, "group": group},
                            )
                        )
            except Exception as exc:
                results.append(
                    ProbeResult(
                        probe_name=f"{group}_probe",
                        url=url,
                        status=0,
                        metadata={"error": str(exc), "path": path, "group": group},
                    )
                )
            if delay > 0:
                await asyncio.sleep(delay)

    try:
        await asyncio.gather(*(probe_one(g, p) for g, p in paths))
    finally:
        if own_session:
            await session.close()

    return [r for r in results if r.status in (200, 201, 204)]
