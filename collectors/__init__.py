"""Plugin-based collector framework."""

from collectors.base import BaseCollector, CollectorContext
from collectors.engine import CollectorEngine
from collectors.plugins import discover_collectors

__all__ = ["BaseCollector", "CollectorContext", "CollectorEngine", "discover_collectors"]
