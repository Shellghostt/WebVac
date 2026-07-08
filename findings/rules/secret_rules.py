"""Secret rules — extended for network and sourcemap origins."""

SECRET_RULES = [
    {
        "match": {"category": "secret", "key": "aws_access_key"},
        "severity": "CRITICAL",
        "category": "secret_exposure",
        "title_template": "AWS Access Key Exposed in Client-Side Code",
        "description_template": (
            "An AWS access key pattern was found at {affected_url}."
        ),
        "remediation": (
            "Rotate the key immediately via AWS IAM. "
            "Move secrets to server-side environment variables."
        ),
        "references": ["https://cwe.mitre.org/data/definitions/312.html"],
    },
    {
        "match": {"category": "secret", "key_prefix": "sourcemap_aws"},
        "severity": "CRITICAL",
        "category": "secret_exposure",
        "title_template": "AWS Key in Recovered Source Map",
        "description_template": "AWS key pattern in source map content at {affected_url}.",
        "remediation": "Rotate key and disable public source map exposure.",
        "references": ["https://cwe.mitre.org/data/definitions/312.html"],
    },
    {
        "match": {"category": "secret", "key": "jwt"},
        "severity": "HIGH",
        "category": "token_exposure",
        "title_template": "JWT Pattern Found in Client-Side Code",
        "description_template": (
            "A JWT-like token was observed at {affected_url}."
        ),
        "remediation": "Avoid storing long-lived tokens in client-accessible code.",
        "references": ["https://cwe.mitre.org/data/definitions/522.html"],
    },
    {
        "match": {"category": "secret", "key_prefix": "jwt_in"},
        "severity": "HIGH",
        "category": "token_exposure",
        "title_template": "JWT Pattern in Network Response",
        "description_template": "JWT-like data in a network response at {affected_url}.",
        "remediation": "Avoid returning tokens in API response bodies.",
        "references": [],
    },
    {
        "match": {"category": "secret", "key": "generic_secret"},
        "severity": "MEDIUM",
        "category": "secret_exposure",
        "title_template": "Possible Hardcoded Secret in JavaScript",
        "description_template": "A key=value secret pattern was found at {affected_url}.",
        "remediation": "Review and remove hardcoded credentials from client code.",
        "references": [],
    },
]
