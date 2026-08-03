"""
Intelligence store — objective facts from webvac.analyzers.

FindingsEngine interprets these into security conclusions.
"""

from __future__ import annotations

from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem


class IntelligenceStore:
    def __init__(self) -> None:
        self._items: list[IntelligenceItem] = []
        self._seen: set[str] = set()

    def add(self, item: IntelligenceItem) -> bool:
        """Add item; returns False if duplicate by dedup_key."""
        if item.dedup_key in self._seen:
            return False
        self._seen.add(item.dedup_key)
        self._items.append(item)
        return True

    def add_many(self, items: list[IntelligenceItem]) -> int:
        return sum(1 for item in items if self.add(item))

    def all(self) -> list[IntelligenceItem]:
        return list(self._items)

    def by_category(self, category: IntelligenceCategory) -> list[IntelligenceItem]:
        return [i for i in self._items if i.category == category]

    def by_source(self, source: str) -> list[IntelligenceItem]:
        return [i for i in self._items if i.source == source]

    def count(self) -> int:
        return len(self._items)

    def to_dict(self) -> list[dict]:
        return [item.to_dict() for item in self._items]

    def persist(self, path: str) -> str:
        import json
        import os

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path
