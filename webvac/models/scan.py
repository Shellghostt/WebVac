"""Scan and target identity for historical comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
import hashlib
import uuid


def _target_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or parsed.path).lower().rstrip("/")
    return hashlib.sha256(host.encode()).hexdigest()[:12]


@dataclass
class TargetMetadata:
    """Stable identity for a crawl target."""

    seed_url: str
    target_id: str = ""
    domain: str = ""
    allowed_domains: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.target_id:
            self.target_id = _target_id_from_url(self.seed_url)
        if not self.domain:
            self.domain = urlparse(self.seed_url).netloc


@dataclass
class ScanMetadata:
    """Per-run scan identity."""

    target: TargetMetadata
    scan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_scan_id: Optional[str] = None
    profile: str = "standard"
    mode: str = "passive"
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    pages_visited: int = 0
    crawler_version: str = "2.1.0"

    def to_dict(self) -> dict:
        return {
            "scan_id": self.scan_id,
            "parent_scan_id": self.parent_scan_id,
            "target_id": self.target.target_id,
            "seed_url": self.target.seed_url,
            "domain": self.target.domain,
            "profile": self.profile,
            "mode": self.mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "pages_visited": self.pages_visited,
            "crawler_version": self.crawler_version,
        }
