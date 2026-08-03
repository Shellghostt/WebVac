"""Rule definitions mapping intelligence to findings."""

from webvac.findings.rules.header_rules import HEADER_RULES
from webvac.findings.rules.secret_rules import SECRET_RULES
from webvac.findings.rules.cookie_rules import COOKIE_RULES
from webvac.findings.rules.storage_rules import STORAGE_RULES
from webvac.findings.rules.network_rules import NETWORK_RULES
from webvac.findings.rules.cloud_rules import CLOUD_RULES
from webvac.findings.rules.auth_rules import AUTH_RULES
from webvac.findings.rules.infra_rules import INFRA_RULES

ALL_RULES = (
    HEADER_RULES
    + SECRET_RULES
    + COOKIE_RULES
    + STORAGE_RULES
    + NETWORK_RULES
    + CLOUD_RULES
    + AUTH_RULES
    + INFRA_RULES
)
