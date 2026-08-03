"""Plugin-based collector framework."""

from webvac.collectors.base import BaseCollector, CollectorContext
from webvac.collectors.engine import CollectorEngine
from webvac.collectors.plugins import discover_collectors

__all__ = ["BaseCollector", "CollectorContext", "CollectorEngine", "discover_collectors"]
