"""Default credentials panel fingerprinting — EyeWitness-style."""

from __future__ import annotations

from models.artifacts import ArtifactType, HtmlArtifact, HTTPResponseArtifact
from models.intelligence import IntelligenceCategory, IntelligenceItem
from analyzers.base import BaseAnalyzer
from analyzers.context import AnalysisContext
from auth.default_creds import DefaultCredsChecker

_checker = DefaultCredsChecker()


class AuthAnalyzer(BaseAnalyzer):
    name = "auth"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return (
            ctx.artifact_store.has_artifacts(ArtifactType.HTTP)
            or ctx.artifact_store.has_artifacts(ArtifactType.HTML)
        )

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        html_by_url: dict[str, HtmlArtifact] = {}
        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if isinstance(artifact, HtmlArtifact):
                html_by_url[artifact.page_url] = artifact

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTTP):
            if not isinstance(artifact, HTTPResponseArtifact):
                continue
            html = html_by_url.get(artifact.page_url)
            title = html.title if html else ""
            server = artifact.response_headers.get(
                "server", artifact.response_headers.get("Server", "")
            )
            matches = _checker.check(artifact.page_url, title, server)
            for match in matches:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.AUTH,
                        key="default_credentials_panel",
                        value=f"{match['vendor']} — {match['panel']}",
                        confidence=0.85,
                        affected_url=artifact.page_url,
                        context={
                            "vendor": match["vendor"],
                            "panel": match["panel"],
                            "username": match.get("username", ""),
                            "password": match.get("password", ""),
                            "notes": match.get("notes", ""),
                            "reference": match.get("reference", ""),
                        },
                    )
                )
        return items
