"""Technology fingerprint aggregator — cross-source signal fusion."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from webvac.models.artifacts import (
    ArtifactType,
    HtmlArtifact,
    HTTPResponseArtifact,
    JavaScriptArtifact,
    NetworkRequestArtifact,
    StorageArtifact,
)
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import TECH_INLINE_SIGNATURES, TECH_NETWORK_HOSTS, TECH_SCRIPT_SIGNATURES

_SERVER_RE = re.compile(r"nginx[/\s]?(\d+\.\d+)?", re.I)
_EXPRESS_RE = re.compile(r"express", re.I)
_CF_RAY = re.compile(r"cf-ray", re.I)
_WORDPRESS_RE = re.compile(r"wordpress\s*([\d.]+)?", re.I)


class TechAnalyzer(BaseAnalyzer):
    name = "tech"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return True

    def _emit(
        self,
        items: list[IntelligenceItem],
        key: str,
        value: str,
        role: str,
        confidence: float,
        page_url: str,
        source_detail: str,
    ) -> None:
        items.append(
            IntelligenceItem(
                source=self.name,
                category=IntelligenceCategory.TECHNOLOGY,
                key=f"tech_{role}_{key.lower().replace('.', '_').replace(' ', '_')}",
                value={"name": value, "role": role, "confidence": confidence},
                confidence=confidence,
                affected_url=page_url,
                context={"signal_source": source_detail},
            )
        )

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        seen: set[str] = set()

        def once(key: str, *args, **kwargs) -> None:
            dedup = f"{key}:{args[0] if args else ''}"
            if dedup in seen:
                return
            seen.add(dedup)
            self._emit(items, key, *args, **kwargs)

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTTP):
            if not isinstance(artifact, HTTPResponseArtifact):
                continue
            headers = {k.lower(): v for k, v in artifact.response_headers.items()}
            server = headers.get("server", "")
            if server:
                if m := _SERVER_RE.search(server):
                    ver = m.group(1) or ""
                    once("nginx", f"nginx {ver}".strip(), "server", 0.9, artifact.page_url, "Server header")
                else:
                    once(server.split("/")[0], server, "server", 0.85, artifact.page_url, "Server header")
            powered = headers.get("x-powered-by", "")
            if powered and _EXPRESS_RE.search(powered):
                once("express", "Express", "framework", 0.85, artifact.page_url, "X-Powered-By")
            elif powered:
                once(powered, powered, "framework", 0.8, artifact.page_url, "X-Powered-By")
            if any(_CF_RAY.search(k) for k in headers):
                once("cloudflare", "Cloudflare", "cdn", 0.99, artifact.page_url, "cf-ray header")
                once("cloudflare_waf", "Cloudflare", "waf", 0.9, artifact.page_url, "cf-ray header")

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if not isinstance(artifact, HtmlArtifact):
                continue
            generator = artifact.meta.get("generator", "")
            if generator:
                if _WORDPRESS_RE.search(generator):
                    once("wordpress", generator, "cms", 0.95, artifact.page_url, "meta generator")
                else:
                    once(generator, generator, "cms", 0.9, artifact.page_url, "meta generator")
            for url in artifact.script_urls:
                for pattern, name, role, conf in TECH_SCRIPT_SIGNATURES:
                    if pattern.search(url):
                        ver = pattern.search(url).group(1) if pattern.search(url).lastindex else ""
                        label = f"{name} {ver}".strip()
                        once(label, label, role, conf, artifact.page_url, f"script src: {url}")
            for block in artifact.inline_scripts:
                for sig, name, role, conf in TECH_INLINE_SIGNATURES:
                    if sig in block:
                        once(name, name, role, conf, artifact.page_url, f"inline script: {sig}")

        for artifact in ctx.artifact_store.get_all(ArtifactType.JAVASCRIPT):
            if not isinstance(artifact, JavaScriptArtifact):
                continue
            for _page, block in artifact.inline_blocks:
                for sig, name, role, conf in TECH_INLINE_SIGNATURES:
                    if sig in block:
                        once(name, name, role, conf, artifact.page_url, "inline js block")

        for artifact in ctx.artifact_store.get_all(ArtifactType.NETWORK):
            if not isinstance(artifact, NetworkRequestArtifact):
                continue
            host = urlparse(artifact.request_url).netloc.lower()
            for needle, name, role in TECH_NETWORK_HOSTS:
                if needle in host:
                    once(name, name, role, 0.9, artifact.page_url, f"network: {host}")

        for artifact in ctx.artifact_store.get_all(ArtifactType.STORAGE):
            if not isinstance(artifact, StorageArtifact):
                continue
            for key in artifact.local_storage:
                if "ab_" in key.lower() or "flag" in key.lower():
                    once("feature_flags", "A/B testing / feature flags", "third_party", 0.7, artifact.page_url, f"storage key: {key}")

        ctx.cache["technology_profile"] = self._build_profile(items)
        return items

    @staticmethod
    def _build_profile(items: list[IntelligenceItem]) -> dict:
        profile: dict = {
            "server": None,
            "framework": None,
            "frontend": None,
            "cms": None,
            "cdn": None,
            "waf": None,
            "analytics": [],
            "payments": [],
            "third_party": [],
            "libraries": [],
        }
        for item in items:
            if not isinstance(item.value, dict):
                continue
            name = item.value.get("name", "")
            role = item.value.get("role", "")
            conf = item.value.get("confidence", item.confidence)
            entry = {"name": name, "confidence": conf}
            if role == "server":
                profile["server"] = entry
            elif role == "framework":
                profile["framework"] = entry
            elif role == "frontend":
                profile["frontend"] = entry
            elif role == "cms":
                profile["cms"] = entry
            elif role == "cdn":
                profile["cdn"] = entry
            elif role == "waf":
                profile["waf"] = entry
            elif role == "analytics" and name not in profile["analytics"]:
                profile["analytics"].append(name)
            elif role == "payments" and name not in profile["payments"]:
                profile["payments"].append(name)
            elif role == "third_party" and name not in profile["third_party"]:
                profile["third_party"].append(name)
            elif role == "library":
                profile["libraries"].append(entry)
        return profile
