"""
Crawl scope management.

Defines allowed domains, depth/page/request limits, and URL exclusion patterns
before the crawler runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from webvac.models.origin import OriginTarget


DEFAULT_IGNORED_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".css", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3",
    ".pdf", ".zip", ".gz", ".tar",
})


@dataclass
class CrawlScope:
    seed_url: str
    allowed_domains: list[str] = field(default_factory=list)
    allow_subdomains: bool = False
    max_depth: int = 3
    max_pages: Optional[int] = 100
    max_requests: Optional[int] = None
    ignored_extensions: frozenset[str] = DEFAULT_IGNORED_EXTENSIONS
    exclude_patterns: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    origin_access: Optional[OriginTarget] = None

    def __post_init__(self) -> None:
        if not self.allowed_domains:
            host = urlparse(self.seed_url).netloc
            self.allowed_domains = [host]

    @property
    def _exclude_regexes(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.exclude_patterns]

    @property
    def _include_regexes(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.include_patterns]

    def is_domain_allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        if self.origin_access and host == self.origin_access.origin_ip:
            return True
        for domain in self.allowed_domains:
            domain = domain.lower()
            if host == domain:
                return True
            if self.allow_subdomains and host.endswith("." + domain):
                return True
        return False

    def is_extension_ignored(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        for ext in self.ignored_extensions:
            if path.endswith(ext):
                return True
        return False

    def matches_url_rules(self, url: str) -> bool:
        if self._include_regexes:
            if not any(r.search(url) for r in self._include_regexes):
                return False
        if any(r.search(url) for r in self._exclude_regexes):
            return False
        return True

    def is_url_in_scope(self, url: str) -> bool:
        if not self.is_domain_allowed(url):
            return False
        if self.is_extension_ignored(url):
            return False
        return self.matches_url_rules(url)

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "allowed_domains": self.allowed_domains,
            "allow_subdomains": self.allow_subdomains,
            "max_depth": self.max_depth,
            "max_pages": self.max_pages,
            "max_requests": self.max_requests,
            "ignored_extensions": sorted(self.ignored_extensions),
            "exclude_patterns": self.exclude_patterns,
            "include_patterns": self.include_patterns,
        }


class ScopeManager:
    """Runtime scope enforcement with request counting."""

    def __init__(self, scope: CrawlScope) -> None:
        self.scope = scope
        self._pages_visited = 0
        self._requests_made = 0

    @property
    def pages_visited(self) -> int:
        return self._pages_visited

    @property
    def requests_made(self) -> int:
        return self._requests_made

    def can_visit_page(self, url: str, depth: int) -> tuple[bool, str]:
        if depth > self.scope.max_depth:
            return False, "max_depth exceeded"
        if self.scope.max_pages is not None and self._pages_visited >= self.scope.max_pages:
            return False, "max_pages exceeded"
        if not self.scope.is_url_in_scope(url):
            return False, "url out of scope"
        return True, ""

    def can_make_request(self) -> tuple[bool, str]:
        if self.scope.max_requests is None:
            return True, ""
        if self._requests_made >= self.scope.max_requests:
            return False, "max_requests exceeded"
        return True, ""

    def record_page_visit(self, url: str) -> None:
        self._pages_visited += 1
        self._requests_made += 1

    def record_request(self) -> None:
        self._requests_made += 1
