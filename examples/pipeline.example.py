"""
Example item pipeline for WebVac (`--pipeline-file`).

Copy to your project (e.g. my_pipeline.py) and pass:
  python -m webvac --url https://example.com --pipeline-file my_pipeline.py

Provide either:
  - PIPELINES = [callable, ...]
  - or a single process_item(item) function

Each callable receives a page dict and must return the dict, or None to drop it.
"""


def drop_empty_titles(item: dict):
    """Drop pages with no title."""
    if not (item.get("title") or "").strip():
        return None
    return item


def strip_long_text(item: dict):
    """Keep text field short for lighter exports."""
    text = item.get("text") or ""
    if len(text) > 5000:
        item = dict(item)
        item["text"] = text[:5000] + "…"
    return item


def tag_example(item: dict):
    item = dict(item)
    meta = dict(item.get("meta") or {})
    meta["pipeline"] = "examples/pipeline.example.py"
    item["meta"] = meta
    return item


# Preferred export: ordered list of callables
PIPELINES = [
    drop_empty_titles,
    strip_long_text,
    tag_example,
]
