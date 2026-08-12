"""Active probe — OPTIONS / Allow method discovery on interesting URLs."""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import aiohttp

from webvac.intelligence.store import IntelligenceStore
from webvac.models.findings import ProbeResult
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem


_DEFAULT_PATHS = (
    "/",
    "/api",
    "/api/v1",
    "/graphql",
    "/admin",
    "/login",
)


async def probe_http_methods(
    base_url: str,
    config: dict[str, Any],
    *,
    session: Optional[aiohttp.ClientSession] = None,
    intelligence: Optional[IntelligenceStore] = None,
) -> list[ProbeResult]:
    """
    Send OPTIONS to seed + discovered API/admin paths.
    Records Allow / Access-Control-Allow-Methods when present.
    """
    if not config.get("active_probes", {}).get("http_methods", True):
        return []

    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    targets: list[str] = [root + "/"]
    for path in _DEFAULT_PATHS:
        targets.append(urljoin(root + "/", path.lstrip("/")))

    if intelligence:
        for item in intelligence.all():
            if item.category not in (
                IntelligenceCategory.ENDPOINT,
                IntelligenceCategory.GRAPHQL,
                IntelligenceCategory.AUTH,
            ):
                continue
            val = str(item.value or "")
            if val.startswith("http"):
                targets.append(val.split("?")[0])
            elif val.startswith("/"):
                targets.append(urljoin(root + "/", val.lstrip("/")))

    # de-dupe, cap
    seen: set[str] = set()
    urls: list[str] = []
    for u in targets:
        if u in seen:
            continue
        seen.add(u)
        urls.append(u)
        if len(urls) >= 25:
            break

    delay = float(config.get("active_probe_delay", 0.3))
    proxy = config.get("_proxy_url")
    results: list[ProbeResult] = []
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    assert session is not None
    try:
        for url in urls:
            try:
                async with session.request(
                    "OPTIONS",
                    url,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False,
                    allow_redirects=False,
                ) as resp:
                    allow = (
                        resp.headers.get("Allow")
                        or resp.headers.get("Access-Control-Allow-Methods")
                        or ""
                    )
                    if allow or resp.status < 400:
                        results.append(
                            ProbeResult(
                                probe_name="http_methods",
                                url=url,
                                status=resp.status,
                                metadata={
                                    "allow": allow,
                                    "headers": {
                                        k: v
                                        for k, v in resp.headers.items()
                                        if k.lower()
                                        in (
                                            "allow",
                                            "access-control-allow-methods",
                                            "access-control-allow-origin",
                                            "access-control-allow-headers",
                                        )
                                    },
                                },
                            )
                        )
                        if intelligence is not None and allow:
                            intelligence.add(
                                IntelligenceItem(
                                    source="http_methods_probe",
                                    category=IntelligenceCategory.NETWORK,
                                    key="http_methods_allow",
                                    value=allow,
                                    confidence=0.95,
                                    affected_url=url,
                                    context={"status": resp.status},
                                )
                            )
            except Exception:
                pass
            if delay:
                await asyncio.sleep(delay)
    finally:
        if own_session:
            await session.close()

    return results
