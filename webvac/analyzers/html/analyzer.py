"""HTML surface analyzer — forms, uploads, comments, admin links, auth pages."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from webvac.analyzers.base import BaseAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.models.artifacts import ArtifactType, FormArtifact, HtmlArtifact
from webvac.models.intelligence import IntelligenceCategory, IntelligenceItem

_ADMIN_PATH = re.compile(
    r"/(?:admin|administrator|manage|management|cpanel|backend|wp-admin|"
    r"dashboard|console|controlpanel|sysadmin)(?:/|$|\?)",
    re.I,
)
_AUTH_PATH = re.compile(
    r"/(?:login|signin|sign-in|register|signup|sign-up|forgot|reset-password|"
    r"mfa|otp|sso|oauth|auth)(?:/|$|\?)",
    re.I,
)
_INTERESTING_COMMENT = re.compile(
    r"todo|fixme|hack|xxx|password|secret|api[_-]?key|admin|debug|"
    r"remove|temporary|deprecated|staging|internal",
    re.I,
)
_ROLE_HINT = re.compile(
    r"\b(?:role|roles|permission|isAdmin|is_admin|userType|user_type|"
    r"guest|moderator|superuser)\b",
    re.I,
)


class HtmlAnalyzer(BaseAnalyzer):
    name = "html"

    def supports(self, ctx: AnalysisContext) -> bool:
        if not ctx.is_analyzer_enabled(self.name):
            return False
        return ctx.artifact_store.has_artifacts(ArtifactType.HTML)

    def analyze(self, ctx: AnalysisContext) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        seen_admin: set[str] = set()
        seen_auth: set[str] = set()

        for artifact in ctx.artifact_store.get_all(ArtifactType.HTML):
            if not isinstance(artifact, HtmlArtifact):
                continue
            page = artifact.page_url

            for comment in artifact.comments:
                text = (comment or "").strip()
                if not text or len(text) > 2000:
                    continue
                if _INTERESTING_COMMENT.search(text):
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.FORM,
                            key="html_comment_interesting",
                            value=text[:240],
                            confidence=0.75,
                            affected_url=page,
                        )
                    )
                if _ROLE_HINT.search(text):
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.AUTH,
                            key="authorization_boundary_hint",
                            value=text[:200],
                            confidence=0.55,
                            affected_url=page,
                        )
                    )

            for form in artifact.forms:
                if not isinstance(form, FormArtifact):
                    continue
                items.extend(self._form_items(form, page))

            for link in artifact.links:
                path = urlparse(link).path or link
                if _ADMIN_PATH.search(path) and link not in seen_admin:
                    seen_admin.add(link)
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.ENDPOINT,
                            key="admin_path",
                            value=link,
                            confidence=0.9,
                            affected_url=page,
                        )
                    )
                if _AUTH_PATH.search(path) and link not in seen_auth:
                    seen_auth.add(link)
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.AUTH,
                            key="authentication_page",
                            value=link,
                            confidence=0.85,
                            affected_url=page,
                        )
                    )

            if _ADMIN_PATH.search(urlparse(page).path or ""):
                if page not in seen_admin:
                    seen_admin.add(page)
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.ENDPOINT,
                            key="admin_path",
                            value=page,
                            confidence=1.0,
                            affected_url=page,
                        )
                    )

        return items

    def _form_items(self, form: FormArtifact, page: str) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        has_file = False
        hidden_count = 0
        for field in form.fields:
            ftype = (field.type or "").lower()
            if ftype == "file":
                has_file = True
            if ftype == "hidden":
                hidden_count += 1
                if field.value:
                    items.append(
                        IntelligenceItem(
                            source=self.name,
                            category=IntelligenceCategory.FORM,
                            key="hidden_input",
                            value=f"{field.name or field.id}={field.value[:120]}",
                            confidence=0.9,
                            affected_url=page,
                            context={
                                "action": form.action,
                                "method": form.method,
                                "name": field.name,
                            },
                        )
                    )
            if ftype == "password":
                items.append(
                    IntelligenceItem(
                        source=self.name,
                        category=IntelligenceCategory.AUTH,
                        key="password_form",
                        value=form.action or page,
                        confidence=0.95,
                        affected_url=page,
                        context={"method": form.method},
                    )
                )

        if has_file or "multipart" in (form.enctype or "").lower():
            items.append(
                IntelligenceItem(
                    source=self.name,
                    category=IntelligenceCategory.FORM,
                    key="file_upload",
                    value=form.action or page,
                    confidence=1.0,
                    affected_url=page,
                    context={
                        "method": form.method,
                        "enctype": form.enctype,
                    },
                )
            )

        if form.fields:
            items.append(
                IntelligenceItem(
                    source=self.name,
                    category=IntelligenceCategory.FORM,
                    key="form",
                    value=form.action or page,
                    confidence=1.0,
                    affected_url=page,
                    context={
                        "method": form.method,
                        "field_count": len(form.fields),
                        "hidden_count": hidden_count,
                        "enctype": form.enctype,
                    },
                )
            )
        return items
