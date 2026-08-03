"""
AnalysisContext — shared context passed to every analyzer.

Avoids large function signatures and centralizes scan state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from webvac.graph.endpoint_graph import EndpointGraph
from webvac.intelligence.store import IntelligenceStore
from webvac.models.scan import ScanMetadata
from webvac.scope.scope_manager import CrawlScope, ScopeManager
from webvac.store.artifact_store import ArtifactStore


@dataclass
class AnalysisContext:
    artifact_store: ArtifactStore
    config: dict[str, Any]
    scan: ScanMetadata
    scope: CrawlScope
    intelligence: IntelligenceStore
    endpoint_graph: EndpointGraph
    scope_manager: Optional[ScopeManager] = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("webvac"))
    cache: dict[str, Any] = field(default_factory=dict)

    def is_analyzer_enabled(self, name: str) -> bool:
        return self.config.get("analyzers", {}).get(name, False)

    def is_collector_enabled(self, name: str) -> bool:
        return self.config.get("collectors", {}).get(name, False)
