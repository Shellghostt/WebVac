"""Origin bypass target — scrape via discovered real IP + Host header."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class OriginTarget:
    """Direct-to-origin access for a Cloudflare-protected hostname."""

    hostname: str
    origin_ip: str
    scheme: str = "https"
    port: int = 443
    expected_title: str = ""
    validated: bool = False
    source: str = "manual"  # manual | probe

    def host_header(self) -> str:
        if (self.scheme == "https" and self.port == 443) or (
            self.scheme == "http" and self.port == 80
        ):
            return self.hostname
        return f"{self.hostname}:{self.port}"

    def vanity_base(self) -> str:
        port = f":{self.port}" if self.port not in (80, 443) else ""
        return f"{self.scheme}://{self.hostname}{port}"

    def resolve_fetch_url(self, url: str) -> str:
        """Map a vanity URL to https://<origin_ip>/path (Host header set separately)."""
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        port_suffix = ""
        if (self.scheme == "https" and self.port != 443) or (
            self.scheme == "http" and self.port != 80
        ):
            port_suffix = f":{self.port}"
        return f"{self.scheme}://{self.origin_ip}{port_suffix}{path}"

    def host_resolver_rule(self) -> str:
        """Chromium --host-resolver-rules entry."""
        return f"MAP {self.hostname} {self.origin_ip}"

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "origin_ip": self.origin_ip,
            "scheme": self.scheme,
            "port": self.port,
            "expected_title": self.expected_title,
            "validated": self.validated,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OriginTarget:
        return cls(
            hostname=data["hostname"],
            origin_ip=data["origin_ip"],
            scheme=data.get("scheme", "https"),
            port=int(data.get("port", 443)),
            expected_title=data.get("expected_title", ""),
            validated=bool(data.get("validated")),
            source=data.get("source", "manual"),
        )
