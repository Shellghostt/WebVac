"""Shared CAPTCHA data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class CaptchaType(str, Enum):
    """Supported CAPTCHA families.

    The six reCAPTCHA demo variants map 1:1:
      v2, v2 invisible, v2 callback, v2 enterprise, v3, v3 enterprise.
    """

    UNKNOWN = "unknown"
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V2_INVISIBLE = "recaptcha_v2_invisible"
    RECAPTCHA_V2_CALLBACK = "recaptcha_v2_callback"
    RECAPTCHA_V2_ENTERPRISE = "recaptcha_v2_enterprise"
    RECAPTCHA_V3 = "recaptcha_v3"
    RECAPTCHA_V3_ENTERPRISE = "recaptcha_v3_enterprise"
    HCAPTCHA = "hcaptcha"
    TURNSTILE = "turnstile"


@dataclass
class CaptchaInfo:
    """Parameters required to create a solver task."""

    captcha_type: CaptchaType
    website_url: str
    website_key: str = ""
    page_action: str = ""
    is_invisible: bool = False
    is_enterprise: bool = False
    user_agent: str = ""
    proxy: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def solvable(self) -> bool:
        return bool(
            self.website_key
            and self.captcha_type
            not in (CaptchaType.UNKNOWN,)
        )

    @property
    def is_recaptcha(self) -> bool:
        return self.captcha_type.value.startswith("recaptcha_")


@dataclass
class SolverResult:
    success: bool
    token: str = ""
    error: Optional[str] = None
    provider: str = ""
    task_id: str = ""
    raw: Optional[dict[str, Any]] = None
