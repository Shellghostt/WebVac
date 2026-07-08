"""
Findings engine — interprets intelligence into security conclusions.

Dedup strategy: merge by (category, rule_category, title) and aggregate URLs/evidence.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from findings.rules import ALL_RULES
from intelligence.store import IntelligenceStore
from models.findings import Finding, ProbeResult, Severity
from models.intelligence import IntelligenceItem

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


class FindingsEngine:
    def __init__(self, rules: Optional[list[dict]] = None) -> None:
        self.rules = rules if rules is not None else ALL_RULES
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"SEC-{self._counter:04d}"

    def _rule_matches(self, rule: dict, item: IntelligenceItem) -> bool:
        match = rule.get("match", {})
        if match.get("category") and item.category.value != match["category"]:
            return False
        if match.get("key") and item.key != match["key"]:
            return False
        key_prefix = match.get("key_prefix")
        if key_prefix and not item.key.startswith(key_prefix):
            return False
        condition = rule.get("condition")
        if condition and not condition(item):
            return False
        return True

    def _format_template(self, template: str, item: IntelligenceItem, header: str) -> str:
        return template.format(
            header=header,
            value=item.value,
            affected_url=item.affected_url,
            key=item.key,
        )

    def _apply_rule(self, rule: dict, item: IntelligenceItem) -> Optional[Finding]:
        header = item.context.get("header", item.key)
        title = rule.get("override_title") or self._format_template(
            rule["title_template"], item, header
        )
        severity = rule.get("override_severity") or rule["severity"]
        if rule.get("condition") and rule["condition"](item):
            severity = rule.get("override_severity", severity)

        return Finding(
            id=self._next_id(),
            severity=Severity(severity),
            category=rule["category"],
            title=title,
            description=self._format_template(rule["description_template"], item, header),
            evidence=[item.to_dict()],
            confidence=item.confidence,
            affected_urls=[item.affected_url] if item.affected_url else [],
            remediation=rule.get("remediation", ""),
            references=list(rule.get("references", [])),
        )

    @staticmethod
    def _intel_dedup_key(rule: dict, item: IntelligenceItem) -> str:
        value_hash = hashlib.sha256(str(item.value).encode()).hexdigest()[:12]
        return (
            f"{rule['category']}:{item.category.value}:{item.key}:{value_hash}"
        )

    def _merge_finding(self, existing: Finding, item: IntelligenceItem) -> None:
        if item.affected_url and item.affected_url not in existing.affected_urls:
            existing.affected_urls.append(item.affected_url)
        existing.evidence.append(item.to_dict())
        existing.confidence = max(existing.confidence, item.confidence)

    def run(
        self,
        intelligence: IntelligenceStore,
        probe_results: Optional[list[ProbeResult]] = None,
    ) -> list[Finding]:
        dedup: dict[str, Finding] = {}

        for item in intelligence.all():
            for rule in self.rules:
                if not self._rule_matches(rule, item):
                    continue
                finding = self._apply_rule(rule, item)
                if not finding:
                    continue
                key = self._intel_dedup_key(rule, item)
                if key in dedup:
                    self._merge_finding(dedup[key], item)
                else:
                    dedup[key] = finding

        findings = list(dedup.values())

        if probe_results:
            findings.extend(self._findings_from_probes(probe_results))

        findings.sort(key=lambda f: (_SEVERITY_RANK.get(f.severity, 99), f.title))
        return findings

    def _findings_from_probes(self, probes: list[ProbeResult]) -> list[Finding]:
        by_url: dict[str, Finding] = {}
        for probe in probes:
            if probe.status not in (200, 201, 204):
                continue
            severity = Severity.HIGH
            if probe.probe_name in ("env_probe",):
                severity = Severity.CRITICAL
            elif probe.probe_name in ("git_probe", "graphql_probe"):
                severity = Severity.HIGH
            elif probe.probe_name in ("files_probe", "swagger_probe"):
                severity = Severity.MEDIUM

            if probe.url in by_url:
                existing = by_url[probe.url]
                existing.evidence.append(probe.to_dict())
                if _SEVERITY_RANK[severity] < _SEVERITY_RANK[existing.severity]:
                    existing.severity = severity
                continue

            finding = Finding(
                id=self._next_id(),
                severity=severity,
                category="active_discovery",
                title=self._probe_title(probe),
                description=self._probe_description(probe),
                evidence=[probe.to_dict()],
                confidence=0.9,
                affected_urls=[probe.url],
                remediation=self._probe_remediation(probe),
                references=[],
            )
            by_url[probe.url] = finding
        return list(by_url.values())

    @staticmethod
    def _probe_title(probe: ProbeResult) -> str:
        if probe.probe_name == "graphql_probe" and probe.metadata.get("introspection_enabled"):
            return f"GraphQL introspection enabled: {probe.url}"
        return f"Sensitive path accessible: {probe.url}"

    @staticmethod
    def _probe_description(probe: ProbeResult) -> str:
        if probe.probe_name == "graphql_probe" and probe.metadata.get("introspection_enabled"):
            count = probe.metadata.get("type_count", 0)
            return (
                f"GraphQL introspection succeeded at {probe.url} "
                f"({count} types exposed)."
            )
        return f"Active probe '{probe.probe_name}' returned HTTP {probe.status}."

    @staticmethod
    def _probe_remediation(probe: ProbeResult) -> str:
        if probe.probe_name == "graphql_probe":
            return "Disable introspection in production GraphQL endpoints."
        if probe.probe_name == "env_probe":
            return "Remove .env files from the web root and rotate any exposed secrets."
        if probe.probe_name == "git_probe":
            return "Block access to .git directory; verify no source code was exposed."
        return "Restrict access or remove exposed sensitive files."
