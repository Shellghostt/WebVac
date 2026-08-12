"""Source map analyzer — recovered paths, imports, secrets in unminified source."""

from __future__ import annotations

import re

from webvac.models.artifacts import ArtifactType, JavaScriptArtifact, SourceMapArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import ENDPOINT_PATTERNS, SECRET_PATTERNS

_IMPORT_RE = re.compile(r"""import\s+.*?from\s+['"]([^'"]+)['"]""")
_NODE_MODULES = re.compile(r"(?:^|[\\/])node_modules[\\/]", re.I)
_APP_HINT = re.compile(
    r"(?:^|[\\/])(?:src|app|pages|components|lib|server|api|routes)[\\/]",
    re.I,
)


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

    def _path_kind(self, src_path: str) -> str:
        if _NODE_MODULES.search(src_path):
            return "vendor"
        if _APP_HINT.search(src_path):
            return "app"
        return "other"

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for artifact in ctx.artifact_store.get_all(ArtifactType.SOURCE_MAP):
            if not isinstance(artifact, SourceMapArtifact):
                continue

            if artifact.sources_content:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.SECRET,
                        key="sources_content_present",
                        value=artifact.map_url or artifact.js_url,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={
                            "map_url": artifact.map_url,
                            "js_url": artifact.js_url,
                            "embedded_file_count": len(artifact.sources_content),
                        },
                    )
                )

            for src_path in artifact.sources:
                kind = self._path_kind(src_path)
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.TECHNOLOGY,
                        key="recovered_source_path",
                        value=src_path,
                        confidence=1.0 if kind != "vendor" else 0.7,
                        affected_url=artifact.page_url,
                        context={
                            "map_url": artifact.map_url,
                            "js_url": artifact.js_url,
                            "path_kind": kind,
                        },
                    )
                )
                if kind == "app":
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.TECHNOLOGY,
                            key="recovered_app_source",
                            value=src_path,
                            confidence=0.95,
                            affected_url=artifact.page_url,
                            context={"map_url": artifact.map_url},
                        )
                    )

            for src_path, content in artifact.sources_content.items():
                if content:
                    items.extend(
                        self._scan_source(content, src_path, artifact.map_url, artifact.page_url)
                    )
        return items
