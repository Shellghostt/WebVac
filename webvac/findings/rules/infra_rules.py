"""Infrastructure finding rules."""

INFRA_RULES = [
    {
        "match": {"category": "endpoint", "key": "admin_path"},
        "severity": "INFO",
        "category": "attack_surface",
        "title_template": "Admin Path Reference",
        "description_template": "Admin path '{value}' referenced at {affected_url}.",
        "remediation": "Ensure admin routes require strong authentication.",
        "references": [],
    },
    {
        "match": {"category": "graphql", "key": "graphql_endpoint"},
        "severity": "INFO",
        "category": "attack_surface",
        "title_template": "GraphQL Endpoint Discovered",
        "description_template": "GraphQL endpoint at {value}.",
        "remediation": "Disable introspection in production if not required.",
        "references": [],
    },
    {
        "match": {"category": "form", "key": "file_upload"},
        "severity": "INFO",
        "category": "attack_surface",
        "title_template": "File Upload Form Detected",
        "description_template": "Upload surface at {value} (page {affected_url}).",
        "remediation": "Validate content types, size, and auth on upload handlers.",
        "references": [],
    },
    {
        "match": {"category": "form", "key": "html_comment_interesting"},
        "severity": "LOW",
        "category": "information_disclosure",
        "title_template": "Interesting HTML Comment",
        "description_template": "Comment on {affected_url}: {value}",
        "remediation": "Strip development comments from production HTML.",
        "references": [],
    },
    {
        "match": {"category": "secret", "key": "sources_content_present"},
        "severity": "HIGH",
        "category": "information_disclosure",
        "title_template": "Source Map Embeds Original Source",
        "description_template": (
            "Source map at {value} includes sourcesContent (full original files)."
        ),
        "remediation": "Do not ship source maps with sourcesContent to production clients.",
        "references": [],
    },
    {
        "match": {"category": "auth", "key": "authentication_page"},
        "severity": "INFO",
        "category": "attack_surface",
        "title_template": "Authentication Page Discovered",
        "description_template": "Auth entry point {value} linked from {affected_url}.",
        "remediation": "Harden login (rate limits, MFA, lockout).",
        "references": [],
    },
]
