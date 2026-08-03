"""JavaScript content analyzer — endpoints and secret patterns."""

from __future__ import annotations

from webvac.models.artifacts import ArtifactType, JavaScriptArtifact, JavaScriptFile
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import ENDPOINT_PATTERNS, SECRET_PATTERNS


class JsAnalyzer(BaseAnalyzer):
    name = "js"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return (
            ctx.artifact_store.has_artifacts(ArtifactType.JAVASCRIPT)
            or ctx.artifact_store.has_artifacts(ArtifactType.HTML)
        )

    def _scan_content(
        self,
        ctx: AnalysisContext,
        content: str,
        file_url: str,
        page_url: str,
    ) -> list[IntelligenceItem]:
        content = self._prettify(content)
        items: list[IntelligenceItem] = []
        for pattern, key in ENDPOINT_PATTERNS:
            for match in pattern.finditer(content):
                endpoint = match.group(1) if match.lastindex else match.group(0)
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.ENDPOINT,
                        key=key,
                        value=endpoint,
                        confidence=0.75,
                        affected_url=page_url or file_url,
                        context={"file": file_url, "match": match.group(0)},
                    )
                )
                ctx.endpoint_graph.add_edge(
                    page_url or file_url,
                    endpoint,
                    source=self.name,
                )
        for pattern, key, confidence in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.SECRET,
                        key=key,
                        value=match.group(0)[:20] + "...",
                        confidence=confidence,
                        affected_url=file_url or page_url,
                        context={"file": file_url, "offset": match.start()},
                    )
                )
        return items

    @staticmethod
    def _prettify(content: str) -> str:
        if "\n" in content and content.count("\n") > 3:
            return content
        try:
            import jsbeautifier

            return jsbeautifier.beautify(content)
        except Exception:
            return content

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []

        for artifact in ctx.artifact_store.get_all(ArtifactType.JAVASCRIPT):
            if not isinstance(artifact, JavaScriptArtifact):
                continue
            for js_file in artifact.files:
                if isinstance(js_file, JavaScriptFile) and js_file.content:
                    items.extend(
                        self._scan_content(
                            ctx, js_file.content, js_file.url, artifact.page_url
                        )
                    )
            for page_url, block in artifact.inline_blocks:
                items.extend(self._scan_content(ctx, block, page_url, page_url))

        return items
