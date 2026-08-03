"""Canonical data models for artifacts, intelligence, findings, and scan identity."""

from webvac.models.artifacts import (
    ArtifactType,
    BaseArtifact,
    CookieArtifact,
    EndpointArtifact,
    FormArtifact,
    FormField,
    HtmlArtifact,
    HTTPResponseArtifact,
    JavaScriptFile,
    JavaScriptArtifact,
    NetworkRequestArtifact,
    RedirectHop,
    ScreenshotArtifact,
    SourceMapArtifact,
    StorageArtifact,
)
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem
from webvac.models.findings import Finding, ProbeResult, Severity
from webvac.models.scan import ScanMetadata, TargetMetadata

__all__ = [
    "ArtifactType",
    "BaseArtifact",
    "CookieArtifact",
    "EndpointArtifact",
    "FormArtifact",
    "FormField",
    "HtmlArtifact",
    "HTTPResponseArtifact",
    "JavaScriptFile",
    "JavaScriptArtifact",
    "NetworkRequestArtifact",
    "RedirectHop",
    "ScreenshotArtifact",
    "SourceMapArtifact",
    "StorageArtifact",
    "IntelligenceCategory",
    "IntelligenceItem",
    "Finding",
    "ProbeResult",
    "Severity",
    "ScanMetadata",
    "TargetMetadata",
]
