"""Findings and active probe results — conclusions drawn from webvac.intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class Finding:
    id: str
    severity: Severity
    category: str
    title: str
    description: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    affected_urls: list[str] = field(default_factory=list)
    remediation: str = ""
    cve: Optional[str] = None
    references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity.value,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "affected_urls": self.affected_urls,
            "remediation": self.remediation,
            "cve": self.cve,
            "references": self.references,
        }


@dataclass
class ProbeResult:
    """Active recon result — kept separate from passive intelligence."""

    probe_name: str
    url: str
    status: int
    content_type: str = ""
    size_bytes: int = 0
    body_preview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_name": self.probe_name,
            "url": self.url,
            "status": self.status,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "body_preview": self.body_preview,
            "metadata": self.metadata,
        }
