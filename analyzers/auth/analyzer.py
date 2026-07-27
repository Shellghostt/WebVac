"""Default credentials panel fingerprinting + auth cookie flag analysis."""

from __future__ import annotations

from models.artifacts import (
    ArtifactType,
    CookieArtifact,
    HtmlArtifact,
    HTTPResponseArtifact,
)
from models.intelligence import IntelligenceCategory, IntelligenceItem
from analyzers.base import BaseAnalyzer
from analyzers.context import AnalysisContext
from auth.default_creds import DefaultCredsChecker
from auth.cookie_audit import audit_cookies

_checker = DefaultCredsChecker()


class AuthAnalyzer(BaseAnalyzer):
    name = "auth"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return (
            ctx.artifact_store.has_artifacts(ArtifactType.HTTP)
            or ctx.artifact_store.has_artifacts(ArtifactType.HTML)
            or ctx.artifact_store.has_artifacts(ArtifactType.COOKIE)
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

        # Cookie flag audit — VAPT only (scrape-safe login warnings live in cookie_audit)
        if ctx.config.get("vapt_enabled"):
            cookie_dicts: list[dict] = []
            page_url = ""
            for artifact in ctx.artifact_store.get_all(ArtifactType.COOKIE):
                if not isinstance(artifact, CookieArtifact):
                    continue
                page_url = artifact.page_url or page_url
                cookie_dicts.append({
                    "name": artifact.name,
                    "value": artifact.value,
                    "httpOnly": artifact.http_only,
                    "secure": artifact.secure,
                    "sameSite": artifact.same_site,
                })

            for issue in audit_cookies(cookie_dicts, page_url=page_url):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.AUTH,
                        key=issue["key"],
                        value=issue["cookie_name"],
                        confidence=0.8,
                        affected_url=issue.get("affected_url") or page_url,
                        context={
                            "severity": issue["severity"],
                            "message": issue["message"],
                        },
                    )
                )
        return items
