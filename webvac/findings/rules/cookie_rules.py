"""Cookie security finding rules."""

COOKIE_RULES = [
    {
        "match": {"category": "cookie", "key": "cookie_missing_httponly"},
        "severity": "MEDIUM",
        "category": "insecure_cookie",
        "title_template": "Cookie Missing HttpOnly Flag: {value}",
        "description_template": (
            "Cookie '{value}' at {affected_url} is not marked HttpOnly."
        ),
        "remediation": "Set the HttpOnly flag to prevent JavaScript access to session cookies.",
        "references": ["https://owasp.org/www-community/HttpOnly"],
    },
    {
        "match": {"category": "cookie", "key": "cookie_missing_secure"},
        "severity": "MEDIUM",
        "category": "insecure_cookie",
        "title_template": "Cookie Missing Secure Flag: {value}",
        "description_template": (
            "Cookie '{value}' at {affected_url} is not marked Secure."
        ),
        "remediation": "Set the Secure flag so cookies are only sent over HTTPS.",
        "references": ["https://owasp.org/www-community/SecureCookieAttribute"],
    },
    {
        "match": {"category": "cookie", "key": "cookie_missing_samesite"},
        "severity": "LOW",
        "category": "insecure_cookie",
        "title_template": "Cookie Missing SameSite Attribute: {value}",
        "description_template": (
            "Cookie '{value}' at {affected_url} has no SameSite attribute."
        ),
        "remediation": "Set SameSite=Lax or Strict to mitigate CSRF.",
        "references": [],
    },
]
