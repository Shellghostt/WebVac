"""
Historical scan session paths and parent-scan chaining.

Layout:
    scraped_data/
        <domain>_<target_id>/
            scans/
                <YYYYMMDD_HHMMSS>_<scan_id>/
                    scrape/     report.html, data.json, ...
                    recon/      findings, intelligence, recon reports
                    artifacts/  artifacts.json
                    network/    per-page network debug dumps
                    assets/
                        pdfs/
                        sourcemaps/
                        screenshots/
                    meta/       session.json, meta.json
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional

from webvac.models.scan import ScanMetadata


def _domain_slug(domain: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")
    return slug or "target"


class ScanSession:
    """Resolves on-disk paths for a target scan."""

    def __init__(self, output_dir: str, scan: ScanMetadata) -> None:
        self.output_dir = output_dir
        self.scan = scan
        self.target_id = scan.target.target_id
        self.scan_id = scan.scan_id
        self.domain_slug = _domain_slug(scan.target.domain)
        self.target_dir = os.path.join(
            output_dir, f"{self.domain_slug}_{self.target_id[:8]}"
        )
        try:
            ts = datetime.fromisoformat(
                scan.started_at.replace("Z", "+00:00")
            ).strftime("%Y%m%d_%H%M%S")
        except ValueError:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_name = f"{ts}_{self.scan_id[:8]}"
        self.session_dir = os.path.join(self.target_dir, "scans", self.session_name)

    def layout_paths(self) -> dict[str, str]:
        base = self.session_dir
        return {
            "root": base,
            "scrape": os.path.join(base, "scrape"),
            "recon": os.path.join(base, "recon"),
            "artifacts": os.path.join(base, "artifacts"),
            "network": os.path.join(base, "network"),
            "assets_pdfs": os.path.join(base, "assets", "pdfs"),
            "assets_sourcemaps": os.path.join(base, "assets", "sourcemaps"),
            "assets_screenshots": os.path.join(base, "assets", "screenshots"),
            "meta": os.path.join(base, "meta"),
        }

    def ensure_dirs(self) -> None:
        for path in self.layout_paths().values():
            os.makedirs(path, exist_ok=True)

    def apply_parent_chain(self, explicit_parent: Optional[str] = None) -> Optional[str]:
        parent = explicit_parent or self.latest_scan_id()
        self.scan.parent_scan_id = parent
        return parent

    def latest_scan_id(self, *, exclude: Optional[str] = None) -> Optional[str]:
        scans_root = os.path.join(self.target_dir, "scans")
        if not os.path.isdir(scans_root):
            return None
        candidates = [
            name
            for name in os.listdir(scans_root)
            if os.path.isdir(os.path.join(scans_root, name))
            and name != (exclude or "")
        ]
        if not candidates:
            return None
        candidates.sort()
        return candidates[-1]

    def write_meta(
        self,
        slug: str,
        *,
        interrupted: bool = False,
        origin_access: Optional[dict] = None,
    ) -> str:
        path = os.path.join(self.layout_paths()["meta"], "meta.json")
        payload = {
            "target_id": self.target_id,
            "scan_id": self.scan_id,
            "parent_scan_id": self.scan.parent_scan_id,
            "session_name": self.session_name,
            "slug": slug,
            "domain": self.scan.target.domain,
            "seed_url": self.scan.target.seed_url,
            "profile": self.scan.profile,
            "mode": self.scan.mode,
            "started_at": self.scan.started_at,
            "completed_at": self.scan.completed_at,
            "interrupted": interrupted,
            "layout": {
                "scrape": "scrape/",
                "recon": "recon/",
                "artifacts": "artifacts/",
                "network": "network/",
                "assets": "assets/",
                "meta": "meta/",
            },
        }
        if origin_access:
            payload["origin_access"] = origin_access
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return path
