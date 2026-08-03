"""Cloud asset analyzer — S3, Azure Blob, GCS exposure in client-side content."""

from __future__ import annotations

from webvac.models.artifacts import (
    ArtifactType,
    HtmlArtifact,
    JavaScriptArtifact,
    NetworkRequestArtifact,
    StorageArtifact,
)
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import CLOUD_PATTERNS


class CloudAnalyzer(BaseAnalyzer):
    name = "cloud"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return True

    def _scan_text(self, text: str, page_url: str, origin: str) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for pattern, key, confidence in CLOUD_PATTERNS:
            for match in pattern.finditer(text):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.CLOUD,
                        key=key,
                        value=match.group(0),
                        confidence=confidence,
                        affected_url=page_url,
                        context={"origin": origin},
                    )
                )
        return items

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if isinstance(artifact, HtmlArtifact):
                items.extend(self._scan_text(artifact.raw_html, artifact.page_url, "html"))

        for artifact in ctx.artifact_store.get_all(ArtifactType.JAVASCRIPT):
            if isinstance(artifact, JavaScriptArtifact):
                for js_file in artifact.files:
                    if js_file.content:
                        items.extend(self._scan_text(js_file.content, artifact.page_url, js_file.url))

        for artifact in ctx.artifact_store.get_all(ArtifactType.NETWORK):
            if isinstance(artifact, NetworkRequestArtifact):
                items.extend(self._scan_text(artifact.request_url, artifact.page_url, "network_url"))
                if artifact.body_preview:
                    items.extend(self._scan_text(artifact.body_preview, artifact.page_url, "network_body"))

        for artifact in ctx.artifact_store.get_all(ArtifactType.STORAGE):
            if isinstance(artifact, StorageArtifact):
                blob = " ".join(artifact.local_storage.values()) + " ".join(artifact.session_storage.values())
                items.extend(self._scan_text(blob, artifact.page_url, "storage"))

        return items
