"""Unit tests for the output format writers (issue: core test suite).

Uses the legacy (no scan metadata) layout under a tmp directory, so no
browser, network, or scan session is involved.
"""

import csv
import json
import sqlite3

from webvac.data.storage import Storage

PAGES = [
    {
        "url": "https://example.com/a",
        "title": "Page A",
        "status": 200,
        "word_count": 42,
        "meta": {"description": "first"},
        "links": [{"href": "https://example.com/b", "text": "B"}],
    },
    {
        "url": "https://example.com/b",
        "title": "Page B",
        "status": 404,
        "word_count": 3,
        "meta": {"description": "second"},
        "links": [],
    },
]


def save(tmp_path, formats):
    storage = Storage(output_dir=str(tmp_path))
    return storage.save(PAGES, label="example", formats=formats)


class TestJsonWriter:
    def test_json_round_trip(self, tmp_path):
        paths = save(tmp_path, ["json"])
        with open(paths["json"], encoding="utf-8") as fh:
            assert json.load(fh) == PAGES


class TestCsvWriter:
    def test_csv_flattens_and_unions_keys(self, tmp_path):
        paths = save(tmp_path, ["csv"])
        with open(paths["csv"], newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert rows[0]["url"] == "https://example.com/a"
        assert rows[0]["meta.description"] == "first"
        # lists are JSON-stringified by the flattener
        assert json.loads(rows[0]["links"])[0]["href"] == "https://example.com/b"
        assert rows[1]["title"] == "Page B"


class TestSqliteWriter:
    def test_sqlite_rows_and_json_columns(self, tmp_path):
        paths = save(tmp_path, ["sqlite"])
        conn = sqlite3.connect(paths["sqlite"])
        try:
            rows = conn.execute(
                "SELECT url, status, title FROM pages ORDER BY url"
            ).fetchall()
            assert rows == [
                ("https://example.com/a", "200", "Page A"),
                ("https://example.com/b", "404", "Page B"),
            ]
            meta = conn.execute(
                "SELECT meta_json FROM pages WHERE url = ?", (PAGES[0]["url"],)
            ).fetchone()[0]
            assert json.loads(meta) == {"description": "first"}
        finally:
            conn.close()


class TestMarkdownWriter:
    def test_markdown_contains_titles_and_urls(self, tmp_path):
        paths = save(tmp_path, ["markdown"])
        text = open(paths["markdown"], encoding="utf-8").read()
        assert "Page A" in text
        assert "https://example.com/b" in text


class TestSaveBehaviour:
    def test_empty_data_saves_nothing(self, tmp_path):
        storage = Storage(output_dir=str(tmp_path))
        assert storage.save([], formats=["json"]) == {}

    def test_unknown_format_is_skipped(self, tmp_path):
        paths = save(tmp_path, ["json", "bogus"])
        assert "json" in paths
        assert "bogus" not in paths

    def test_flatten_deep_dict_becomes_json_string(self):
        storage = Storage.__new__(Storage)
        deep = {"a": {f"k{i}": i for i in range(15)}}
        flat = storage._flatten(deep)
        assert json.loads(flat["a"]) == deep["a"]

    def test_url_slug_uses_domain(self):
        storage = Storage.__new__(Storage)
        assert storage._url_slug("https://www.sub.example.com/some/path") == "sub_example_com"
        assert storage._url_slug("not a url") == "scrape"
