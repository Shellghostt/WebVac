"""Network traffic analyzer — API endpoints, response leaks, GraphQL errors."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from webvac.models.artifacts import ArtifactType, NetworkRequestArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.patterns import DEBUG_JSON_KEYS, SECRET_PATTERNS

_API_PATH = re.compile(r"^/api/|^/v\d+/|^/graphql|/internal/|/admin/", re.I)
_VERBOSE_ERROR = re.compile(
    r"traceback \(most recent call last\)|sqlsyntaxerror|ora-\d{5}|"
    r"mysql_fetch|pg_query|sqlite3\.|mongodb\.error|exception in|"
    r"stack trace|at [\w.$]+\([^)]+\.java:\d+\)|webpack://|"
    r"django\.|rails\.|laravel|symfony|werkzeug|fastapi\.exceptions",
    re.I,
)


class NetworkAnalyzer(BaseAnalyzer):
    name = "network"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return ctx.artifact_store.has_artifacts(ArtifactType.NETWORK)

    def _scan_body(self, artifact: NetworkRequestArtifact) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        body = artifact.body_preview or ""
        if not body:
            return items

        for pattern, key, confidence in SECRET_PATTERNS:
            if pattern.search(body):
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.SECRET,
                        key=f"{key}_in_response",
                        value=key,
                        confidence=confidence * 0.9,
                        affected_url=artifact.page_url,
                        context={
                            "request_url": artifact.request_url,
                            "method": artifact.method,
                        },
                    )
                )

        try:
            data = json.loads(body)
            if isinstance(data, dict):
                for k in data:
                    if k.lower() in DEBUG_JSON_KEYS:
                        items.append(
                            IntelligenceItem(
                                source=self.name,
                                category=IntelligenceCategory.NETWORK,
                                key="debug_object_in_response",
                                value=k,
                                confidence=0.85,
                                affected_url=artifact.page_url,
                                context={"request_url": artifact.request_url},
                            )
                        )
                if "errors" in data and "graphql" in artifact.request_url.lower():
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.GRAPHQL,
                            key="graphql_error_response",
                            value=str(data["errors"])[:200],
                            confidence=0.9,
                            affected_url=artifact.page_url,
                            context={"request_url": artifact.request_url},
                        )
                    )
        except json.JSONDecodeError:
            pass

        return items

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        seen_endpoints: set[str] = set()

        for artifact in ctx.artifact_store.get_all(ArtifactType.NETWORK):
            if not isinstance(artifact, NetworkRequestArtifact):
                continue

            parsed = urlparse(artifact.request_url)
            path = parsed.path or artifact.request_url
            endpoint_key = f"{artifact.method}:{artifact.request_url}"
            if endpoint_key not in seen_endpoints:
                seen_endpoints.add(endpoint_key)
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.ENDPOINT,
                        key="network_request",
                        value=artifact.request_url,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={
                            "method": artifact.method,
                            "resource_type": artifact.resource_type,
                            "status": artifact.status,
                            "content_type": artifact.content_type,
                        },
                    )
                )
                ctx.endpoint_graph.add_edge(
                    artifact.page_url,
                    artifact.request_url,
                    method=artifact.method,
                    source=self.name,
                )

            if _API_PATH.search(path) or "graphql" in path.lower():
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.ENDPOINT,
                        key="api_endpoint_observed",
                        value=artifact.request_url,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={"method": artifact.method},
                    )
                )

            auth = artifact.request_headers.get("authorization") or artifact.request_headers.get("Authorization")
            if auth:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.AUTH,
                        key="authorization_header_sent",
                        value=auth[:20] + "..." if len(auth) > 20 else auth,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={"request_url": artifact.request_url},
                    )
                )

            if artifact.resource_type == "websocket" or artifact.websocket_messages:
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.ENDPOINT,
                        key="websocket_endpoint",
                        value=artifact.request_url,
                        confidence=1.0,
                        affected_url=artifact.page_url,
                        context={
                            "frame_count": len(artifact.websocket_messages or ()),
                        },
                    )
                )

            if artifact.status >= 400 and artifact.resource_type in (
                "document", "xhr", "fetch",
            ):
                body = artifact.body_preview or ""
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.NETWORK,
                        key="error_response",
                        value=f"{artifact.status} {artifact.request_url}",
                        confidence=0.9,
                        affected_url=artifact.page_url,
                        context={
                            "status": artifact.status,
                            "request_url": artifact.request_url,
                            "body_preview": body[:200],
                        },
                    )
                )
                if body and _VERBOSE_ERROR.search(body):
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.NETWORK,
                            key="verbose_error_page",
                            value=f"{artifact.status} {artifact.request_url}",
                            confidence=0.85,
                            affected_url=artifact.page_url,
                            context={"status": artifact.status, "snippet": body[:240]},
                        )
                    )

            items.extend(self._scan_body(artifact))

        return items
