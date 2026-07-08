"""Storage-related finding rules."""

STORAGE_RULES = [
    {
        "match": {"category": "secret", "key": "jwt_in_storage"},
        "severity": "HIGH",
        "category": "token_exposure",
        "title_template": "JWT Stored in Browser Storage",
        "description_template": (
            "A JWT-like value was found in browser storage at {affected_url}."
        ),
        "remediation": "Use HttpOnly cookies or short-lived tokens instead of localStorage.",
        "references": ["https://cwe.mitre.org/data/definitions/522.html"],
    },
    {
        "match": {"category": "storage", "key": "sensitive_storage_key"},
        "severity": "LOW",
        "category": "sensitive_storage",
        "title_template": "Sensitive Key in Browser Storage: {value}",
        "description_template": (
            "Storage key '{value}' at {affected_url} may contain sensitive data."
        ),
        "remediation": "Review stored values for secrets or PII exposure.",
        "references": [],
    },
]
