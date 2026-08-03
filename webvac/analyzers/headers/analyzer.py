"""HTTP security header analyzer — produces intelligence facts."""

from __future__ import annotations

from webvac.models.artifacts import ArtifactType, HTTPResponseArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext

SECURITY_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-embedder-policy",
    "cross-origin-opener-policy",
)


class HeaderAnalyzer(BaseAnalyzer):
    name = "headers"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return ctx.artifact_store.has_artifacts(ArtifactType.HTTP)

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for artifact in ctx.artifact_store.get_all(ArtifactType.HTTP):
            if not isinstance(artifact, HTTPResponseArtifact):
                continue
            headers_lower = {k.lower(): v for k, v in artifact.response_headers.items()}
            for header in SECURITY_HEADERS:
                if header in headers_lower:
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.HEADER,
                            key=f"header_present_{header.replace('-', '_')}",
                            value=headers_lower[header],
                            confidence=1.0,
                            affected_url=artifact.page_url,
                            context={"header": header},
                        )
                    )
                else:
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.HEADER,
                            key=f"header_missing_{header.replace('-', '_')}",
                            value=True,
                            confidence=1.0,
                            affected_url=artifact.page_url,
                            context={"header": header},
                        )
                    )
            for signal_header in ("server", "x-powered-by", "x-generator", "cf-ray"):
                if signal_header in headers_lower:
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.TECHNOLOGY,
                            key=f"header_signal_{signal_header.replace('-', '_')}",
                            value=headers_lower[signal_header],
                            confidence=0.9,
                            affected_url=artifact.page_url,
                        )
                    )
        return items
