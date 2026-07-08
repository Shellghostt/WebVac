"""Base collector interface — collects raw artifacts only."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from models.artifacts import BaseArtifact
from models.scan import ScanMetadata
from scope.scope_manager import ScopeManager
from store.artifact_store import ArtifactStore


@dataclass
class CollectorContext:
    """Shared context for per-page collection."""

    artifact_store: ArtifactStore
    config: dict[str, Any]
    scan: ScanMetadata
    scope_manager: ScopeManager
    base_url: str = ""
    depth: int = 0
    cookies: list[dict] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    name: str = "base"

    @abstractmethod
    def supports(self, ctx: CollectorContext) -> bool:
        """Return True if profile enables this collector."""

    @abstractmethod
    async def collect(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
    ) -> list[BaseArtifact]:
        """Return raw artifacts — no analysis."""
