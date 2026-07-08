"""End-to-end scrape test (offline fixture, no network)."""

import os
import shutil
import tempfile
import unittest

from data.page_record import PageRecordBuilder
from data.storage import Storage
from models.scan import ScanMetadata, TargetMetadata
from store.scan_session import ScanSession

TARGET = "http://testphp.vulnweb.com/"
FIXTURE_HTML = """<!DOCTYPE html>
<html><head><title>Acunetix test site</title></head>
<body>
<h1>welcome</h1>
<p>Test site for security scanners.</p>
<a href="categories.php">categories</a>
<a href="artists.php">artists</a>
<form action="search.php" method="GET">
  <input type="text" name="test" placeholder="search art">
  <input type="submit" value="search">
</form>
</body></html>"""


class E2EScrapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_scrape_save_fixture(self):
        out_dir = tempfile.mkdtemp(prefix="webvac_e2e_")
        try:
            target = TargetMetadata(seed_url=TARGET)
            scan = ScanMetadata(target=target, profile="scrape")

            record = PageRecordBuilder().from_html(
                FIXTURE_HTML,
                page_url=TARGET,
                base_url=TARGET,
            )
            self.assertEqual(record.get("status"), "success")
            self.assertIn("Acunetix", record.get("title", ""))
            self.assertTrue(any(l["type"] == "internal" for l in record.get("links", [])))

            ScanSession(out_dir, scan).apply_parent_chain()
            paths = Storage(output_dir=out_dir).save(
                [record],
                formats=["json", "html"],
                scan=scan,
            )
            layout = ScanSession(out_dir, scan).layout_paths()
            for path in (
                os.path.join(layout["scrape"], "data.json"),
                os.path.join(layout["scrape"], "report.html"),
                os.path.join(layout["meta"], "meta.json"),
            ):
                self.assertTrue(os.path.isfile(path), f"missing {path}")

            scan2 = ScanMetadata(target=target, scan_id="scan-follow-up")
            parent = ScanSession(out_dir, scan2).apply_parent_chain()
            self.assertEqual(parent, ScanSession(out_dir, scan).session_name)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
