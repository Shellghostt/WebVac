"""Export source map artifacts to files on disk."""

from __future__ import annotations

import hashlib
import json
import os
import re

from webvac.models.artifacts import ArtifactType, SourceMapArtifact
from webvac.store.artifact_store import ArtifactStore


def export_sourcemaps(store: ArtifactStore, dest_dir: str) -> list[dict]:
    os.makedirs(dest_dir, exist_ok=True)
    exported: list[dict] = []
    for art in store.get_all(ArtifactType.SOURCE_MAP):
        if not isinstance(art, SourceMapArtifact):
            continue
        digest = hashlib.sha256(art.map_url.encode()).hexdigest()[:10]
        base = re.sub(r"[^\w.\-]+", "_", os.path.basename(art.map_url))[:60]
        map_path = os.path.join(dest_dir, f"{base}_{digest}.map")
        with open(map_path, "w", encoding="utf-8") as f:
            payload = {
                "map_url": art.map_url,
                "js_url": art.js_url,
                "sources": list(art.sources),
                "sources_content": art.sources_content,
            }
            json.dump(payload, f, ensure_ascii=False, indent=2)
        exported.append({"map_url": art.map_url, "path": map_path})
        for src_path, content in (art.sources_content or {}).items():
            if not content:
                continue
            safe = re.sub(r"[^\w.\-/]+", "_", src_path).strip("_")[:120]
            src_out = os.path.join(dest_dir, f"{digest}_{safe}")
            os.makedirs(os.path.dirname(src_out) or dest_dir, exist_ok=True)
            try:
                with open(src_out, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                pass
    if exported:
        print(f"[Assets] Exported {len(exported)} source map(s) -> {dest_dir}")
    return exported
