"""Base analyzer interface — produces intelligence, never findings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from models.intelligence import IntelligenceItem

if TYPE_CHECKING:
    from analyzers.context import AnalysisContext


class BaseAnalyzer(ABC):
    """Each analyzer implements a single analysis domain."""

    name: str = "base"

    @abstractmethod
    def supports(self, ctx: AnalysisContext) -> bool:
        """Return True if required artifacts exist and profile enables this analyzer."""

    @abstractmethod
    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        """Return objective facts — never security findings."""
