"""Plugin-based analyzer framework."""

from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.engine import AnalyzerEngine
from webvac.analyzers.plugins import discover_analyzers

__all__ = [
    "BaseAnalyzer",
    "AnalysisContext",
    "AnalyzerEngine",
    "discover_analyzers",
]
