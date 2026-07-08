"""GraphQL introspection probe."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from models.findings import ProbeResult
from models.intelligence import IntelligenceCategory
from intelligence.store import IntelligenceStore

INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      name
      kind
      description
    }
  }
}
""".strip()


def _discover_graphql_urls(
    base_url: str, intelligence: IntelligenceStore | None
) -> list[str]:
    urls: set[str] = set()
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    defaults = [
        urljoin(root + "/", "graphql"),
        urljoin(root + "/", "api/graphql"),
        urljoin(root + "/", "v1/graphql"),
    ]
    urls.update(defaults)

    if intelligence:
        for item in intelligence.all():
            if item.category not in (
                IntelligenceCategory.GRAPHQL,
                IntelligenceCategory.ENDPOINT,
            ):
                continue
            val = str(item.value)
            if "graphql" in val.lower():
                if val.startswith("http"):
                    urls.add(val)
                else:
                    urls.add(urljoin(root + "/", val.lstrip("/")))

    return sorted(urls)


async def probe_graphql(
    base_url: str,
    config: dict[str, Any],
    intelligence: IntelligenceStore | None = None,
) -> list[ProbeResult]:
    if not config.get("active_probes", {}).get("graphql", True):
        return []

    proxy = config.get("_proxy_url")
    results: list[ProbeResult] = []

    async with aiohttp.ClientSession() as session:
        for url in _discover_graphql_urls(base_url, intelligence):
            try:
                async with session.post(
                    url,
                    json={"query": INTROSPECTION_QUERY},
                    headers={"Content-Type": "application/json"},
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    body = await resp.text(errors="replace")
                    preview = body[:512]
                    metadata: dict[str, Any] = {"endpoint": url}
                    if resp.status == 200:
                        try:
                            data = json.loads(body)
                            schema = (data.get("data") or {}).get("__schema")
                            if schema:
                                types = schema.get("types") or []
                                metadata["type_count"] = len(types)
                                metadata["type_names"] = [
                                    t.get("name") for t in types[:30]
                                ]
                                metadata["introspection_enabled"] = True
                        except json.JSONDecodeError:
                            pass
                    if resp.status == 200 and metadata.get("introspection_enabled"):
                        results.append(
                            ProbeResult(
                                probe_name="graphql_probe",
                                url=url,
                                status=resp.status,
                                content_type=resp.headers.get("Content-Type", ""),
                                body_preview=preview,
                                metadata=metadata,
                            )
                        )
            except Exception as exc:
                results.append(
                    ProbeResult(
                        probe_name="graphql_probe",
                        url=url,
                        status=0,
                        metadata={"error": str(exc)},
                    )
                )
    return results
