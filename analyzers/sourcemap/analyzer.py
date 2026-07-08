"""Source map analyzer — recovered paths, imports, secrets in unminified source."""

from __future__ import annotations

import re

from models.artifacts import ArtifactType, JavaScriptArtifact, SourceMapArtifact
from models.intelligence import IntelligenceCategory, IntelligenceItem
from analyzers.base import BaseAnalyzer
from analyzers.context import AnalysisContext
from analyzers.patterns import ENDPOINT_PATTERNS, SECRET_PATTERNS

_IMPORT_RE = re.compile(r"""import\s+.*?from\s+['"]([^'"]+)['"]""")


class SourceMapAnalyzer(BaseAnalyzer):
    name = "sourcemap"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return (
            ctx.artifact_store.has_artifacts(ArtifactType.SOURCE_MAP)
            or any(
                isinstance(a, JavaScriptArtifact) and any(f.source_map_url for f in a.files)
                for a in ctx.artifact_store.get_all(ArtifactType.JAVASCRIPT)
            )
        )

    def _scan_source(
        self, content: str, source_path: str, map_url: str, page_url: str
    ) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for pattern, key in ENDPOINT_PATTERNS:
            for match in pattern.finditer(content):
                endpoint = match.group(1) if match.lastindex else match.group(0)
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.ENDPOINT,
                        key=f"sourcemap_{key}",
                        value=endpoint,
                        confidence=0.9,
                        affected_url=page_url,
                        context={"source_file": source_path, "map_url": map_url},
                    )
                )
        for pattern, key, confidence in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.SECRET,
                        key=f"sourcemap_{key}",
                        value=match.group(0)[:20] + "...",
                        confidence=confidence,
                        affected_url=page_url,
                        context={"source_file": source_path, "map_url": map_url},
                    )
                )
        for match in _IMPORT_RE.finditer(content):
            items.append(
                IntelligenceItem(
                    source=self.name,
                    category=IntelligenceCategory.TECHNOLOGY,
                    key="sourcemap_import",
                    value=match.group(1),
                    confidence=0.85,
                    affected_url=page_url,
                    context={"source_file": source_path},
                )
            )
        return items

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for artifact in ctx.artifact_store.get_all(ArtifactType.SOURCE_MAP):
            if not isinstance(artifact, SourceMapArtifact):
                continue
            for src_path in artifact.sources:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.TECHNOLOGY,
                        key="recovered_source_path",
                        value=src_path,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={"map_url": artifact.map_url, "js_url": artifact.js_url},
                    )
                )
            for src_path, content in artifact.sources_content.items():
                if content:
                    items.extend(
                        self._scan_source(content, src_path, artifact.map_url, artifact.page_url)
                    )
        return items
