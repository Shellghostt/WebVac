"""Tests for VAPT CLI config merge + sourcemap sourcesContent finding."""

from __future__ import annotations

import argparse
import unittest

from webvac.analyzers.context import AnalysisContext
from webvac.analyzers.sourcemap.analyzer import SourceMapAnalyzer
from webvac.cli.scraper import _apply_vapt_config
from webvac.config.config import DEFAULT_CONFIG
from webvac.graph.endpoint_graph import EndpointGraph
from webvac.intelligence.store import IntelligenceStore
from webvac.models.artifacts import SourceMapArtifact
from webvac.models.scan import ScanMetadata, TargetMetadata
from webvac.scope.scope_manager import CrawlScope, ScopeManager
from webvac.store.artifact_store import ArtifactStore


class TestVaptCliConfig(unittest.TestCase):
    def test_vapt_enables_standard(self):
        args = argparse.Namespace(vapt=True, profile=None, active_recon=False)
        cfg = _apply_vapt_config(dict(DEFAULT_CONFIG), args, "https://example.com/x")
        self.assertTrue(cfg["vapt_enabled"])
        self.assertEqual(cfg["profile"], "standard")
        self.assertTrue(cfg["collectors"]["html"])
        self.assertEqual(cfg["allowed_domains"], ["example.com"])

    def test_profile_deep_active(self):
        args = argparse.Namespace(vapt=False, profile="deep", active_recon=False)
        cfg = _apply_vapt_config(dict(DEFAULT_CONFIG), args, "https://app.test/")
        self.assertTrue(cfg["vapt_enabled"])
        self.assertTrue(cfg["active_recon"])
        self.assertTrue(cfg["analyzers"]["sourcemap"])
        self.assertTrue(cfg["analyzers"]["html"])

    def test_no_flag_unchanged(self):
        args = argparse.Namespace(vapt=False, profile=None, active_recon=False)
        cfg = _apply_vapt_config(dict(DEFAULT_CONFIG), args, "https://example.com/")
        self.assertFalse(cfg["vapt_enabled"])


class TestSourceMapAnalyzer(unittest.TestCase):
    def test_sources_content_leak(self):
        store = ArtifactStore()
        url = "https://example.com/"
        store.put(
            url,
            "source_map",
            SourceMapArtifact(
                page_url=url,
                map_url="https://example.com/app.js.map",
                js_url="https://example.com/app.js",
                sources=("webpack:///src/api/client.ts", "node_modules/foo/index.js"),
                sources_content={
                    "webpack:///src/api/client.ts": 'fetch("/api/v1/secret")',
                },
            ),
        )
        cfg = dict(DEFAULT_CONFIG)
        cfg["analyzers"] = {**cfg.get("analyzers", {}), "sourcemap": True}
        scan = ScanMetadata(target=TargetMetadata(seed_url=url))
        scope = CrawlScope(seed_url=url, allowed_domains=["example.com"])
        ctx = AnalysisContext(
            artifact_store=store,
            config=cfg,
            scan=scan,
            scope=scope,
            intelligence=IntelligenceStore(),
            endpoint_graph=EndpointGraph(url),
            scope_manager=ScopeManager(scope),
        )
        items = SourceMapAnalyzer().analyze(ctx)
        keys = {i.key for i in items}
        self.assertIn("sources_content_present", keys)
        self.assertIn("recovered_app_source", keys)


if __name__ == "__main__":
    unittest.main()
