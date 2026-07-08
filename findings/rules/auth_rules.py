"""Authentication and default credential finding rules."""

AUTH_RULES = [
    {
        "match": {"category": "auth", "key": "default_credentials_panel"},
        "severity": "HIGH",
        "category": "default_credentials",
        "title_template": "Known Admin Panel Detected: {value}",
        "description_template": (
            "A known vendor panel was fingerprinted at {affected_url}. "
            "Default credentials may apply — verify manually."
        ),
        "remediation": (
            "Confirm default passwords are changed. Restrict admin panel access."
        ),
        "references": [],
    },
    {
        "match": {"category": "auth", "key": "authorization_header_sent"},
        "severity": "INFO",
        "category": "auth_observed",
        "title_template": "Authorization Header Observed in Traffic",
        "description_template": (
            "A client request sent an Authorization header from {affected_url}."
        ),
        "remediation": "Ensure tokens are short-lived and not logged.",
        "references": [],
    },
    {
        "match": {"category": "technology", "key": "recovered_source_path"},
        "severity": "MEDIUM",
        "category": "source_map_exposure",
        "title_template": "Source Map Exposes Internal Path: {value}",
        "description_template": (
            "Recovered source file path from source map at {affected_url}."
        ),
        "remediation": "Disable public source maps in production builds.",
        "references": [],
    },
]
