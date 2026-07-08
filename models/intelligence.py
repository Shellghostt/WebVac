"""
Intelligence items — objective facts, not security conclusions.

Analyzers produce IntelligenceItem objects. The FindingsEngine interprets them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import hashlib
import json


class IntelligenceCategory(str, Enum):
    TECHNOLOGY = "technology"
    ENDPOINT = "endpoint"
    SECRET = "secret"
    AUTH = "auth"
    HEADER = "header"
    STORAGE = "storage"
    NETWORK = "network"
    INFRASTRUCTURE = "infrastructure"
    GRAPHQL = "graphql"
    OAUTH = "oauth"
    CLOUD = "cloud"
    FORM = "form"
    COOKIE = "cookie"


@dataclass
class IntelligenceItem:
    """A structured, interpreted fact — not a finding."""

    source: str
    category: IntelligenceCategory
    key: str
    value: Any
    confidence: float = 1.0
    context: dict[str, Any] = field(default_factory=dict)
    affected_url: str = ""

    @property
    def dedup_key(self) -> str:
        payload = {
            "category": self.category.value,
            "key": self.key,
            "value": str(self.value),
            "affected_url": self.affected_url,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "category": self.category.value,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "context": self.context,
            "affected_url": self.affected_url,
            "dedup_key": self.dedup_key,
        }
