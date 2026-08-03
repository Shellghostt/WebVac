"""Shared regex patterns for analyzer plugins."""

from __future__ import annotations

import re

ENDPOINT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"""['"](/api/[^'"]+)['"]"""), "api_path"),
    (re.compile(r"""['"](/v\d+/[^'"]+)['"]"""), "versioned_api"),
    (re.compile(r"""['"](/graphql[^'"]*)['"]"""), "graphql"),
    (re.compile(r"""['"](/internal/[^'"]+)['"]"""), "internal_path"),
    (re.compile(r"""['"](/admin[^'"]*)['"]"""), "admin_path"),
    (re.compile(r"""['"](/auth[^'"]*)['"]"""), "auth_path"),
    (re.compile(r"""['"](/rest/[^'"]+)['"]"""), "rest_path"),
    (re.compile(r"""['"](/search[^'"]*)['"]"""), "search_path"),
    (re.compile(
        r"""['"](/[a-zA-Z0-9_\-\./]*(?:api|v\d+|graphql|admin|auth|login|logout|rest|search|data|internal|upload|download)[a-zA-Z0-9_\-\./]*)['"]"""
    ), "api_like_path"),
    (re.compile(r"""(?:fetch|axios)\s*\(\s*['"]([^'"#\s]{5,})['"]"""), "fetch_call"),
    (re.compile(r"""\.\s*(?:get|post|put|delete|patch)\s*\(\s*['"]([^'"#\s]{5,})['"]"""), "verb_call"),
    (re.compile(r"wss?://[^\s'\"]+"), "websocket_url"),
]

SECRET_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_access_key", 0.95),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "jwt", 0.85),
    (
        re.compile(
            r"(?i)(api[_-]?key|secret|password|token|auth)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
        "generic_secret",
        0.6,
    ),
]

CLOUD_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"[a-z0-9.-]+\.s3\.amazonaws\.com"), "s3_bucket", 0.9),
    (re.compile(r"s3://[a-z0-9.-]+"), "s3_uri", 0.9),
    (re.compile(r"[a-z0-9]+\.blob\.core\.windows\.net"), "azure_blob", 0.9),
    (re.compile(r"storage\.googleapis\.com/[a-z0-9._-]+"), "gcs_bucket", 0.9),
]

OAUTH_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\d{12}-[a-z0-9]+\.apps\.googleusercontent\.com"), "google_oauth_client", 0.95),
    (re.compile(r"(?i)fb\d{10,}"), "facebook_app_id", 0.8),
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "github_oauth_token", 0.9),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "github_pat", 0.95),
]

GRAPHQL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(query|mutation|subscription)\s+\w+"), "graphql_operation"),
    (re.compile(r"__schema"), "graphql_introspection"),
]

SENSITIVE_STORAGE_KEYS = frozenset({
    "token", "auth", "session", "key", "secret", "userid", "user_id",
    "role", "access_token", "refresh_token", "id_token", "api_key",
    "jwt", "bearer", "credential", "password",
})

DEBUG_JSON_KEYS = frozenset({"stack", "trace", "debug", "exception", "error_trace"})

TECH_SCRIPT_SIGNATURES: list[tuple[re.Pattern, str, str, float]] = [
    (re.compile(r"jquery[.-](\d+\.\d+\.\d+)"), "jQuery", "library", 0.99),
    (re.compile(r"react[.-](\d+\.\d+\.\d+)"), "React", "frontend", 0.95),
    (re.compile(r"vue[.-](\d+\.\d+\.\d+)"), "Vue.js", "frontend", 0.95),
    (re.compile(r"angular[.-](\d+\.\d+\.\d+)"), "Angular", "frontend", 0.95),
    (re.compile(r"next[.-](\d+\.\d+\.\d+)"), "Next.js", "framework", 0.95),
]

TECH_INLINE_SIGNATURES: list[tuple[str, str, str, float]] = [
    ("__NEXT_DATA__", "Next.js", "framework", 0.98),
    ("__reactFiber", "React", "frontend", 0.95),
    ("__NUXT__", "Nuxt.js", "framework", 0.95),
    ("ng-version", "Angular", "frontend", 0.9),
]

TECH_NETWORK_HOSTS: list[tuple[str, str, str]] = [
    ("google-analytics.com", "Google Analytics", "analytics"),
    ("googletagmanager.com", "Google Tag Manager", "analytics"),
    ("sentry.io", "Sentry", "analytics"),
    ("stripe.com", "Stripe", "payments"),
    ("hotjar.com", "Hotjar", "third_party"),
    ("intercom.io", "Intercom", "third_party"),
]
