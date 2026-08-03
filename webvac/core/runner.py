"""
Pipeline orchestrator — wires collectors, analyzers, findings, and output.

Distinct from core/pipeline.py (user-defined data cleaning hooks).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from webvac.active.probe_runner import ProbeRunner
from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.engine import AnalyzerEngine
from webvac.config.scan_profiles import apply_profile
from webvac.findings.engine import FindingsEngine
from webvac.graph.endpoint_graph import EndpointGraph
from webvac.intelligence.store import IntelligenceStore
from webvac.models.scan import ScanMetadata, TargetMetadata
from webvac.scope.scope_manager import CrawlScope, ScopeManager
from webvac.store.artifact_store import ArtifactStore


class PipelineRunner:
    """
    Orchestrates post-crawl analysis and optional active recon.

    Collection is invoked by Crawler via CollectorEngine during Phase B.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("webvac.runner")
        self.analyzer_engine = AnalyzerEngine(logger=self.logger)
        self.findings_engine = FindingsEngine()

    def build_scan_metadata(self, seed_url: str) -> ScanMetadata:
        target = TargetMetadata(
            seed_url=seed_url,
            allowed_domains=self.config.get("allowed_domains", []),
        )
        return ScanMetadata(
            target=target,
            profile=self.config.get("profile", "standard"),
            mode="active" if self.config.get("active_recon") else "passive",
        )

    def build_scope(self, seed_url: str) -> CrawlScope:
        return CrawlScope(
            seed_url=seed_url,
            allowed_domains=self.config.get("allowed_domains", []),
            allow_subdomains=self.config.get("allow_subdomains", False),
            max_depth=self.config.get("max_depth", 3),
            max_pages=self.config.get("max_pages"),
            max_requests=self.config.get("max_requests"),
            exclude_patterns=self.config.get("exclude_patterns", []),
            include_patterns=self.config.get("include_patterns", []),
        )

    def build_analysis_context(
        self,
        artifact_store: ArtifactStore,
        scan: ScanMetadata,
        scope: CrawlScope,
    ) -> AnalysisContext:
        return AnalysisContext(
            artifact_store=artifact_store,
            config=self.config,
            scan=scan,
            scope=scope,
            intelligence=IntelligenceStore(),
            endpoint_graph=EndpointGraph(scan.target.seed_url),
            scope_manager=ScopeManager(scope),
            logger=self.logger,
        )

    async def run_analysis(
        self,
        artifact_store: ArtifactStore,
        scan: ScanMetadata,
        scope: CrawlScope,
    ) -> dict[str, Any]:
        """Phase 2–5: analyze → optional active → findings → persist."""
        ctx = self.build_analysis_context(artifact_store, scan, scope)

        self.logger.info("Running analyzer engine")
        self.analyzer_engine.run(ctx)

        probe_results = []
        if self.config.get("active_recon"):
            self.logger.info("Running active recon")
            probe_results = await ProbeRunner(self.config, logger=self.logger).run(
                scan.target.seed_url,
                intelligence=ctx.intelligence,
            )

        findings = self.findings_engine.run(ctx.intelligence, probe_results)

        scan.completed_at = datetime.now(timezone.utc).isoformat()
        scan.pages_visited = len(artifact_store.page_urls())

        technology_profile = ctx.cache.get("technology_profile", {})

        return {
            "session": scan.to_dict(),
            "scope": scope.to_dict(),
            "technology_profile": technology_profile,
            "intelligence": ctx.intelligence.to_dict(),
            "findings": [f.to_dict() for f in findings],
            "findings_count": self._count_by_severity(findings),
            "endpoint_graph": ctx.endpoint_graph.to_dict(),
            "endpoint_tree": ctx.endpoint_graph.to_tree_lines(),
            "observations_count": ctx.intelligence.count(),
            "active_recon": {
                "enabled": bool(self.config.get("active_recon")),
                "probe_results": [p.to_dict() for p in probe_results],
            },
        }

    def persist_session(
        self,
        output_dir: str,
        scan: ScanMetadata,
        artifact_store: ArtifactStore,
        analysis_result: dict[str, Any],
    ) -> dict[str, str]:
        """
        Deprecated — use Storage.save(..., scan=scan, recon=analysis_result).

        Writes recon bundle files under scraped_data/<target_id>/<scan_id>/.
        """
        from webvac.data.storage import Storage

        storage = Storage(output_dir=output_dir)
        return storage.save(
            [],
            recon=analysis_result,
            artifact_store=artifact_store,
            scan=scan,
            formats=[],
        )

    @staticmethod
    def _count_by_severity(findings) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in findings:
            sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    @classmethod
    def from_profile(
        cls,
        base_config: dict[str, Any],
        profile_name: str,
        **overrides,
    ) -> PipelineRunner:
        config = apply_profile(base_config, profile_name)
        config.update(overrides)
        return cls(config)


def _write_json(path: str, data: Any) -> str:
    import json

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
