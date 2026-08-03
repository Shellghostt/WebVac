"""Header-related finding rules."""

HEADER_RULES = [
    {
        "match": {"category": "header", "key_prefix": "header_missing_"},
        "severity": "MEDIUM",
        "category": "missing_header",
        "title_template": "Missing Security Header: {header}",
        "description_template": (
            "The response at {affected_url} does not include the "
            "{header} security header."
        ),
        "remediation": "Configure the missing header on your web server or CDN.",
        "references": ["https://owasp.org/www-project-secure-headers/"],
    },
    {
        "match": {"category": "header", "key": "header_present_content-security-policy"},
        "severity": "INFO",
        "category": "header_present",
        "title_template": "Content-Security-Policy Present",
        "description_template": "CSP header value: {value}",
        "remediation": "Review CSP for unsafe-inline or unsafe-eval directives.",
        "references": [],
        "condition": lambda item: "unsafe-inline" in str(item.value)
        or "unsafe-eval" in str(item.value),
        "override_severity": "LOW",
        "override_title": "CSP Contains Unsafe Directives",
    },
]
