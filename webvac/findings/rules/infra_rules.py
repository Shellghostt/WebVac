"""Infrastructure finding rules."""

INFRA_RULES = [
    {
        "match": {"category": "endpoint", "key": "admin_path"},
        "severity": "INFO",
        "category": "attack_surface",
        "title_template": "Admin Path Reference in Client Code",
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
]
