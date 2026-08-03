"""
Canonical artifact schemas.

Collectors MUST emit these types. Analyzers depend on artifact types, not
collector implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ArtifactType(str, Enum):
    HTTP = "http"
    HTML = "html"
    JAVASCRIPT = "javascript"
    SOURCE_MAP = "source_map"
    NETWORK = "network"
    STORAGE = "storage"
    COOKIE = "cookie"
    FORM = "form"
    ENDPOINT = "endpoint"
    SCREENSHOT = "screenshot"


@dataclass(frozen=True)
class BaseArtifact:
    """Immutable raw observation from a collector."""

    page_url: str
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def artifact_type(self) -> ArtifactType:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items()}
        data["artifact_type"] = self.artifact_type.value
        return data


@dataclass(frozen=True)
class RedirectHop:
    url: str
    status: int


@dataclass(frozen=True)
class HTTPResponseArtifact(BaseArtifact):
    status: int = 0
    http_version: str = ""
    redirect_chain: tuple[RedirectHop, ...] = ()
    response_headers: dict[str, str] = field(default_factory=dict)
    request_headers: dict[str, str] = field(default_factory=dict)
    set_cookie_raw: tuple[str, ...] = ()
    content_type: str = ""
    content_length: Optional[int] = None

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.HTTP


@dataclass(frozen=True)
class FormField:
    tag: str
    type: str
    name: str
    id: str = ""
    value: str = ""
    placeholder: str = ""
    autocomplete: str = ""
    required: bool = False


@dataclass(frozen=True)
class FormArtifact(BaseArtifact):
    action: str = ""
    method: str = "GET"
    enctype: str = ""
    fields: tuple[FormField, ...] = ()

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.FORM


@dataclass(frozen=True)
class HtmlArtifact(BaseArtifact):
    raw_html: str = ""
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    comments: tuple[str, ...] = ()
    forms: tuple[FormArtifact, ...] = ()
    links: tuple[str, ...] = ()
    script_urls: tuple[str, ...] = ()
    inline_scripts: tuple[str, ...] = ()
    open_graph: dict[str, str] = field(default_factory=dict)
    twitter_card: dict[str, str] = field(default_factory=dict)
    canonical_url: str = ""
    dom_hidden_elements: tuple[dict[str, str], ...] = ()

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.HTML


@dataclass(frozen=True)
class JavaScriptFile:
    url: str
    content: str
    source_map_url: Optional[str] = None
    size_bytes: int = 0


@dataclass(frozen=True)
class JavaScriptArtifact(BaseArtifact):
    """Session-level artifact: JS files discovered across the crawl."""

    files: tuple[JavaScriptFile, ...] = ()
    inline_blocks: tuple[tuple[str, str], ...] = ()  # (page_url, content)

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.JAVASCRIPT


@dataclass(frozen=True)
class SourceMapArtifact(BaseArtifact):
    map_url: str = ""
    sources: tuple[str, ...] = ()
    sources_content: dict[str, str] = field(default_factory=dict)
    js_url: str = ""

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.SOURCE_MAP


@dataclass(frozen=True)
class NetworkRequestArtifact(BaseArtifact):
    request_url: str = ""
    method: str = "GET"
    resource_type: str = ""
    request_headers: dict[str, str] = field(default_factory=dict)
    post_data: Optional[str] = None
    status: int = 0
    response_headers: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    body_preview: str = ""
    initiator: str = ""
    timing_ms: Optional[float] = None
    websocket_messages: tuple[dict[str, str], ...] = ()

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.NETWORK


@dataclass(frozen=True)
class CookieArtifact(BaseArtifact):
    raw: str = ""
    name: str = ""
    value: str = ""
    domain: str = ""
    path: str = ""
    secure: bool = False
    http_only: bool = False
    same_site: str = ""

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.COOKIE


@dataclass(frozen=True)
class StorageArtifact(BaseArtifact):
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)
    document_cookie: str = ""
    indexeddb_databases: tuple[str, ...] = ()
    cache_buckets: tuple[str, ...] = ()

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.STORAGE


@dataclass(frozen=True)
class EndpointArtifact(BaseArtifact):
    """Discovered endpoint reference (path or full URL)."""

    endpoint: str = ""
    method: str = ""
    source: str = ""  # collector or analyzer that observed it
    confidence: float = 1.0

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.ENDPOINT


@dataclass(frozen=True)
class ScreenshotArtifact(BaseArtifact):
    file_path: str = ""
    reason: str = ""

    @property
    def artifact_type(self) -> ArtifactType:
        return ArtifactType.SCREENSHOT
