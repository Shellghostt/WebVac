"""Network response finding rules."""

NETWORK_RULES = [
    {
        "match": {"category": "network", "key": "debug_object_in_response"},
        "severity": "MEDIUM",
        "category": "information_disclosure",
        "title_template": "Debug/Stack Data in API Response",
        "description_template": (
            "Response at {affected_url} contains a debug field '{value}'."
        ),
        "remediation": "Disable debug output in production API responses.",
        "references": ["https://cwe.mitre.org/data/definitions/209.html"],
    },
    {
        "match": {"category": "graphql", "key": "graphql_error_response"},
        "severity": "LOW",
        "category": "graphql_disclosure",
        "title_template": "GraphQL Error Object in Response",
        "description_template": (
            "GraphQL error details observed at {affected_url}."
        ),
        "remediation": "Sanitize GraphQL error messages in production.",
        "references": [],
    },
]
