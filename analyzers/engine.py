"""Runs all discovered analyzers against an AnalysisContext."""

from __future__ import annotations

import logging
from typing import Optional

from analyzers.context import AnalysisContext
from analyzers.plugins import discover_analyzers
from models.intelligence import IntelligenceItem


class AnalyzerEngine:
    def __init__(
        self,
        analyzers: Optional[list] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("webvac.analyzers")
        self._analyzers = analyzers

    def _get_analyzers(self, ctx: AnalysisContext):
        if self._analyzers is not None:
            return self._analyzers
        enabled = ctx.config.get("analyzers", {})
        return discover_analyzers(enabled_only=enabled)

    def run(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        all_items: list[IntelligenceItem] = []
        analyzers = self._get_analyzers(ctx)

        for analyzer in analyzers:
            if not analyzer.supports(ctx):
                self.logger.debug("Skipping analyzer %s (supports=False)", analyzer.name)
                continue
            self.logger.info("Running analyzer: %s", analyzer.name)
            try:
                items = analyzer.analyze(ctx)
                added = ctx.intelligence.add_many(items)
                all_items.extend(items)
                self.logger.info(
                    "Analyzer %s produced %d items (%d new)",
                    analyzer.name,
                    len(items),
                    added,
                )
            except Exception:
                self.logger.exception("Analyzer %s failed", analyzer.name)
        return all_items
