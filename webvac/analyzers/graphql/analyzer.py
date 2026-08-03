"""GraphQL analyzer — endpoints, operations, introspection signals."""

from __future__ import annotations

from webvac.models.artifacts import ArtifactType, HtmlArtifact, JavaScriptArtifact, NetworkRequestArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import GRAPHQL_PATTERNS


class GraphqlAnalyzer(BaseAnalyzer):
    name = "graphql"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return True

    def _scan_text(self, text: str, page_url: str, origin: str) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for pattern, key in GRAPHQL_PATTERNS:
            for match in pattern.finditer(text):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.GRAPHQL,
                        key=key,
                        value=match.group(0)[:120],
                        confidence=0.85,
                        affected_url=page_url,
                        context={"origin": origin},
                    )
                )
        if "graphql" in text.lower():
            items.append(
                IntelligenceItem(
                    source=self.name,
                    category=IntelligenceCategory.GRAPHQL,
                    key="graphql_reference",
                    value=True,
                    confidence=0.75,
                    affected_url=page_url,
                    context={"origin": origin},
                )
            )
        return items

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []

        for artifact in ctx.artifact_store.get_all(ArtifactType.NETWORK):
            if not isinstance(artifact, NetworkRequestArtifact):
                continue
            if "graphql" in artifact.request_url.lower():
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.GRAPHQL,
                        key="graphql_endpoint",
                        value=artifact.request_url,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={"method": artifact.method},
                    )
                )
                if artifact.post_data:
                    items.extend(
                        self._scan_text(artifact.post_data, artifact.page_url, "network_post")
                    )

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if not isinstance(artifact, HtmlArtifact):
                continue
            for link in artifact.links:
                if "graphql" in link.lower():
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.GRAPHQL,
                            key="graphql_link",
                            value=link,
                            confidence=0.8,
                            affected_url=artifact.page_url,
                        )
                    )
            for block in artifact.inline_scripts:
                items.extend(self._scan_text(block, artifact.page_url, "inline_script"))

        for artifact in ctx.artifact_store.get_all(ArtifactType.JAVASCRIPT):
            if not isinstance(artifact, JavaScriptArtifact):
                continue
            for js_file in artifact.files:
                if js_file.content:
                    items.extend(self._scan_text(js_file.content, artifact.page_url, js_file.url))
            for page_url, block in artifact.inline_blocks:
                items.extend(self._scan_text(block, page_url, "inline_block"))

        return items
