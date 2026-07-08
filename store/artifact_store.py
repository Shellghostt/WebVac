"""
In-memory artifact registry with per-page and session-level storage.

Collectors write; analyzers read. No collector reads from the store.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from models.artifacts import ArtifactType, BaseArtifact
from models.scan import ScanMetadata


def _serialize(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, ArtifactType):
        return obj.value
    if hasattr(obj, "value") and type(obj).__name__ == "Enum":
        return obj.value
    return obj


class ArtifactStore:
    def __init__(self, scan: Optional[ScanMetadata] = None) -> None:
        self.scan = scan
        # page_url -> artifact_type -> list[artifact]
        self._by_url: dict[str, dict[str, list[BaseArtifact]]] = {}
        # session-level artifacts (e.g. aggregated JS)
        self._session: dict[str, list[BaseArtifact]] = {}
        self._request_count: int = 0

    def put(
        self,
        url: str,
        artifact_type: str | ArtifactType,
        artifact: BaseArtifact,
        *,
        session_level: bool = False,
    ) -> None:
        key = (
            artifact_type.value
            if isinstance(artifact_type, ArtifactType)
            else artifact_type
        )
        if session_level:
            self._session.setdefault(key, []).append(artifact)
            return
        bucket = self._by_url.setdefault(url, {})
        bucket.setdefault(key, []).append(artifact)

    def get_all(self, artifact_type: str | ArtifactType) -> list[BaseArtifact]:
        key = (
            artifact_type.value
            if isinstance(artifact_type, ArtifactType)
            else artifact_type
        )
        results: list[BaseArtifact] = []
        for page_bucket in self._by_url.values():
            results.extend(page_bucket.get(key, []))
        results.extend(self._session.get(key, []))
        return results

    def get_for_url(self, url: str) -> dict[str, list[BaseArtifact]]:
        return dict(self._by_url.get(url, {}))

    def page_urls(self) -> list[str]:
        return list(self._by_url.keys())

    def has_artifacts(self, artifact_type: str | ArtifactType) -> bool:
        return len(self.get_all(artifact_type)) > 0

    def increment_requests(self) -> int:
        self._request_count += 1
        return self._request_count

    @property
    def request_count(self) -> int:
        return self._request_count

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"pages": {}, "session": {}}
        for url, types in self._by_url.items():
            out["pages"][url] = {
                t: [_serialize(a) for a in arts] for t, arts in types.items()
            }
        out["session"] = {
            t: [_serialize(a) for a in arts] for t, arts in self._session.items()
        }
        if self.scan:
            out["scan"] = self.scan.to_dict()
        return out

    def persist(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
