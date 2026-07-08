"""Runs enabled collectors for a page visit and session-level collection."""

from __future__ import annotations

import logging
from typing import Optional

from collectors.base import BaseCollector, CollectorContext
from collectors.plugins import discover_collectors
from models.artifacts import BaseArtifact
from store.artifact_store import ArtifactStore


class CollectorEngine:
    def __init__(
        self,
        collectors: Optional[list[BaseCollector]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("webvac.collectors")
        self._collectors = collectors

    def _get_collectors(self, ctx: CollectorContext) -> list[BaseCollector]:
        if self._collectors is not None:
            return self._collectors
        enabled = ctx.config.get("collectors", {})
        return discover_collectors(enabled_only=enabled)

    async def collect_page(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
        network_collector=None,
        endpoint_graph=None,
    ) -> list[BaseArtifact]:
        artifacts: list[BaseArtifact] = []
        for collector in self._get_collectors(ctx):
            if not collector.supports(ctx):
                continue
            if getattr(collector, "session_level", False):
                continue
            if collector.name == "network":
                if network_collector is None:
                    continue
                collector = network_collector
            self.logger.debug("Running collector: %s", collector.name)
            try:
                collected = await collector.collect(
                    ctx, page=page, response=response
                )
                for art in collected:
                    key = art.artifact_type.value
                    ctx.artifact_store.put(art.page_url, key, art)
                    artifacts.append(art)
                    if endpoint_graph and collector.name == "html" and hasattr(art, "links"):
                        for link in art.links:
                            endpoint_graph.add_edge(
                                art.page_url, link, source="html_collector"
                            )
                    if endpoint_graph and collector.name == "network":
                        endpoint_graph.add_edge(
                            art.page_url,
                            art.request_url,
                            method=art.method,
                            source="network_collector",
                        )
            except Exception:
                self.logger.exception("Collector %s failed", collector.name)
        return artifacts

    async def collect_session(self, ctx: CollectorContext) -> list[BaseArtifact]:
        artifacts: list[BaseArtifact] = []
        for collector in self._get_collectors(ctx):
            if not getattr(collector, "session_level", False):
                continue
            if not collector.supports(ctx):
                continue
            if not hasattr(collector, "collect_session"):
                continue
            self.logger.info("Running session collector: %s", collector.name)
            try:
                collected = await collector.collect_session(ctx)
                for art in collected:
                    key = art.artifact_type.value
                    session_level = collector.name == "javascript"
                    ctx.artifact_store.put(
                        art.page_url,
                        key,
                        art,
                        session_level=session_level,
                    )
                    artifacts.append(art)
            except Exception:
                self.logger.exception("Session collector %s failed", collector.name)
        return artifacts
