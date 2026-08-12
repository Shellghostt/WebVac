"""Tests for HTML surface analyzer + form/comment parse enhancements."""

from __future__ import annotations

import unittest

from webvac.analyzers.html.analyzer import HtmlAnalyzer
from webvac.analyzers.context import AnalysisContext
from webvac.config.config import DEFAULT_CONFIG
from webvac.data.html_parser import HtmlPageParser
from webvac.graph.endpoint_graph import EndpointGraph
from webvac.intelligence.store import IntelligenceStore
from webvac.models.artifacts import FormArtifact, FormField, HtmlArtifact
from webvac.models.scan import ScanMetadata, TargetMetadata
from webvac.scope.scope_manager import CrawlScope, ScopeManager
from webvac.store.artifact_store import ArtifactStore


class TestHtmlParserSurface(unittest.TestCase):
    def test_hidden_value_upload_and_comments(self):
        html = """
        <html><body>
        <!-- TODO remove admin debug -->
        <form action="/upload" method="post" enctype="multipart/form-data">
          <input type="hidden" name="csrf" value="tok123">
          <input type="file" name="resume">
        </form>
        <a href="/admin/users">Admin</a>
        </body></html>
        """
        rec = HtmlPageParser().build_from_html(
            html, page_url="https://example.com/", base_url="https://example.com/"
        )
        self.assertTrue(any("TODO" in c for c in rec["html_comments"]))
        form = rec["forms"][0]
        self.assertTrue(form["has_file_upload"])
        hidden = [f for f in form["fields"] if f["type"] == "hidden"][0]
        self.assertEqual(hidden["value"], "tok123")


class TestHtmlAnalyzer(unittest.TestCase):
    def test_emits_upload_admin_comment(self):
        store = ArtifactStore()
        url = "https://example.com/app"
        store.put(
            url,
            "html",
            HtmlArtifact(
                page_url=url,
                title="App",
                comments=("TODO: remove /admin debug panel",),
                forms=(
                    FormArtifact(
                        page_url=url,
                        action="/upload",
                        method="POST",
                        enctype="multipart/form-data",
                        fields=(
                            FormField(tag="input", type="hidden", name="csrf", value="abc"),
                            FormField(tag="input", type="file", name="f"),
                        ),
                    ),
                ),
                links=("https://example.com/admin/dashboard",),
            ),
        )
        cfg = dict(DEFAULT_CONFIG)
        cfg["analyzers"] = {**cfg.get("analyzers", {}), "html": True}
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
        items = HtmlAnalyzer().analyze(ctx)
        keys = {i.key for i in items}
        self.assertIn("file_upload", keys)
        self.assertIn("hidden_input", keys)
        self.assertIn("html_comment_interesting", keys)
        self.assertIn("admin_path", keys)


if __name__ == "__main__":
    unittest.main()
