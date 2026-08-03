"""OAuth / SSO signal analyzer."""

from __future__ import annotations

from webvac.models.artifacts import ArtifactType, HtmlArtifact, JavaScriptArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import OAUTH_PATTERNS

_OAUTH_URL_MARKERS = (
    "accounts.google.com",
    "login.microsoftonline.com",
    "github.com/login/oauth",
    "facebook.com/v",
    "auth0.com",
    "okta.com",
)


class OauthAnalyzer(BaseAnalyzer):
    name = "oauth"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return True

    def _scan_text(self, text: str, page_url: str, origin: str) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        for pattern, key, confidence in OAUTH_PATTERNS:
            for match in pattern.finditer(text):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.OAUTH,
                        key=key,
                        value=match.group(0)[:40] + ("..." if len(match.group(0)) > 40 else ""),
                        confidence=confidence,
                        affected_url=page_url,
                        context={"origin": origin},
                    )
                )
        for marker in _OAUTH_URL_MARKERS:
            if marker in text.lower():
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.OAUTH,
                        key="oauth_provider_url",
                        value=marker,
                        confidence=0.85,
                        affected_url=page_url,
                        context={"origin": origin},
                    )
                )
        return items

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if not isinstance(artifact, HtmlArtifact):
                continue
            items.extend(self._scan_text(artifact.raw_html, artifact.page_url, "html"))
            for link in artifact.links:
                for marker in _OAUTH_URL_MARKERS:
                    if marker in link.lower():
                        items.append(
                            IntelligenceItem(
                                source=self.name,
                                category=IntelligenceCategory.OAUTH,
                                key="oauth_login_link",
                                value=link,
                                confidence=0.9,
                                affected_url=artifact.page_url,
                            )
                        )

        for artifact in ctx.artifact_store.get_all(ArtifactType.JAVASCRIPT):
            if not isinstance(artifact, JavaScriptArtifact):
                continue
            for js_file in artifact.files:
                if js_file.content:
                    items.extend(self._scan_text(js_file.content, artifact.page_url, js_file.url))

        return items
