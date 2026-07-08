"""Browser storage analyzer — tokens, sensitive keys, encoded payloads."""

from __future__ import annotations

import base64
import json
import re

from models.artifacts import ArtifactType, StorageArtifact
from models.intelligence import IntelligenceCategory, IntelligenceItem
from analyzers.base import BaseAnalyzer
from analyzers.context import AnalysisContext
from analyzers.patterns import SECRET_PATTERNS, SENSITIVE_STORAGE_KEYS

_JWT_RE = SECRET_PATTERNS[1][0]


class StorageAnalyzer(BaseAnalyzer):
    name = "storage"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return ctx.artifact_store.has_artifacts(ArtifactType.STORAGE)

    def _scan_kv(
        self, store_name: str, data: dict[str, str], page_url: str
    ) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for key, value in data.items():
            key_lower = key.lower()
            if any(s in key_lower for s in SENSITIVE_STORAGE_KEYS):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.STORAGE,
                        key="sensitive_storage_key",
                        value=key,
                        confidence=0.85,
                        affected_url=page_url,
                        context={"store": store_name},
                    )
                )
            if value and _JWT_RE.search(value):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.SECRET,
                        key="jwt_in_storage",
                        value=value[:24] + "...",
                        confidence=0.9,
                        affected_url=page_url,
                        context={"store": store_name, "key": key},
                    )
                )
            if value and self._looks_like_base64_json(value):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.STORAGE,
                        key="base64_json_payload",
                        value=key,
                        confidence=0.7,
                        affected_url=page_url,
                        context={"store": store_name},
                    )
                )
            if value and re.match(r"^https?://", value):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.ENDPOINT,
                        key="url_in_storage",
                        value=value,
                        confidence=0.8,
                        affected_url=page_url,
                        context={"store": store_name, "key": key},
                    )
                )
        return items

    @staticmethod
    def _looks_like_base64_json(value: str) -> bool:
        if len(value) < 16 or len(value) % 4 != 0:
            return False
        try:
            decoded = base64.b64decode(value, validate=True)
            text = decoded.decode("utf-8")
            json.loads(text)
            return True
        except Exception:
            return False

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for artifact in ctx.artifact_store.get_all(ArtifactType.STORAGE):
            if not isinstance(artifact, StorageArtifact):
                continue
            items.extend(
                self._scan_kv("localStorage", artifact.local_storage, artifact.page_url)
            )
            items.extend(
                self._scan_kv("sessionStorage", artifact.session_storage, artifact.page_url)
            )
            if artifact.indexeddb_databases:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.STORAGE,
                        key="indexeddb_databases",
                        value=list(artifact.indexeddb_databases),
                        confidence=1.0,
                        affected_url=artifact.page_url,
                    )
                )
        return items
