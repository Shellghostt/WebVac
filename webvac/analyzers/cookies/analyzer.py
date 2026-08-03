"""Cookie flag analyzer — Set-Cookie security attributes."""

from __future__ import annotations

import re

from webvac.models.artifacts import ArtifactType, HTTPResponseArtifact, StorageArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext

_SET_COOKIE_SPLIT = re.compile(r",(?=\s*[A-Za-z_][A-Za-z0-9_-]*=)")


def _parse_set_cookie(raw: str) -> dict:
    parts = _SET_COOKIE_SPLIT.split(raw.strip())
    if not parts:
        return {}
    name_value = parts[0].split(";", 1)[0]
    if "=" not in name_value:
        return {}
    name, _, value = name_value.partition("=")
    flags = {"name": name.strip(), "value": value.strip()}
    for part in parts:
        for attr in part.split(";")[1:]:
            token = attr.strip().lower()
            if token == "httponly":
                flags["http_only"] = True
            elif token == "secure":
                flags["secure"] = True
            elif token.startswith("samesite="):
                flags["same_site"] = token.split("=", 1)[1]
            elif token.startswith("domain="):
                flags["domain"] = attr.split("=", 1)[1].strip()
            elif token.startswith("path="):
                flags["path"] = attr.split("=", 1)[1].strip()
    flags.setdefault("http_only", False)
    flags.setdefault("secure", False)
    flags.setdefault("same_site", "")
    return flags


class CookieAnalyzer(BaseAnalyzer):
    name = "cookies"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return (
            ctx.artifact_store.has_artifacts(ArtifactType.HTTP)
            or ctx.artifact_store.has_artifacts(ArtifactType.STORAGE)
        )

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        seen: set[str] = set()

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTTP):
            if not isinstance(artifact, HTTPResponseArtifact):
                continue
            for raw in artifact.set_cookie_raw:
                parsed = _parse_set_cookie(raw)
                if not parsed.get("name"):
                    continue
                cname = parsed["name"]
                dedup = f"{artifact.page_url}:{cname}"
                if dedup in seen:
                    continue
                seen.add(dedup)

                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.COOKIE,
                        key="cookie_observed",
                        value=cname,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context=parsed,
                    )
                )
                if not parsed.get("http_only"):
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.COOKIE,
                            key="cookie_missing_httponly",
                            value=cname,
                            confidence=1.0,
                            affected_url=artifact.page_url,
                            context=parsed,
                        )
                    )
                if not parsed.get("secure"):
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.COOKIE,
                            key="cookie_missing_secure",
                            value=cname,
                            confidence=0.9,
                            affected_url=artifact.page_url,
                            context=parsed,
                        )
                    )
                if not parsed.get("same_site"):
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.COOKIE,
                            key="cookie_missing_samesite",
                            value=cname,
                            confidence=0.9,
                            affected_url=artifact.page_url,
                            context=parsed,
                        )
                    )

        for artifact in ctx.artifact_store.get_all(ArtifactType.STORAGE):
            if not isinstance(artifact, StorageArtifact):
                continue
            if artifact.document_cookie:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.COOKIE,
                        key="document_cookie_present",
                        value=True,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={"length": len(artifact.document_cookie)},
                    )
                )
        return items
