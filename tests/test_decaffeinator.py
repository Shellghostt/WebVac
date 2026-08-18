from types import SimpleNamespace

from webvac.vapt.decaffeinator import build_decaffeinator_command


def test_build_decaffeinator_command_standard():
    args = SimpleNamespace(
        url="https://example.com",
        vapt_profile="standard",
        depth=3,
        max_pages=None,
        concurrency=2,
        timeout=30000,
        delay_min=0.5,
        vapt_format="json",
        vapt_playwright=False,
        vapt_wayback=False,
        no_headless=False,
        vapt_no_files=False,
    )
    cmd = build_decaffeinator_command(
        args,
        output_dir="out/decaf",
        root="D:/WebVac/trial4/blob-unpacker",
    )
    joined = " ".join(cmd)
    assert "run.py" in cmd[1]
    assert args.url in cmd
    assert "-o" in cmd and "out/decaf" in cmd
    assert "-p" in cmd and "100" in cmd
    assert "--playwright" not in joined
    assert "--wayback" not in joined


def test_build_decaffeinator_command_deep_with_browser_flags():
    args = SimpleNamespace(
        url="https://example.com",
        vapt_profile="deep",
        depth=5,
        max_pages=250,
        concurrency=4,
        timeout=45000,
        delay_min=1.25,
        vapt_format="jsonl",
        vapt_playwright=True,
        vapt_wayback=True,
        no_headless=True,
        vapt_no_files=True,
    )
    cmd = build_decaffeinator_command(
        args,
        output_dir="out/decaf",
        root="D:/WebVac/trial4/blob-unpacker",
    )
    assert "--deep" in cmd
    assert "--playwright" in cmd
    assert "--wayback" in cmd
    assert "--pw-visible" in cmd
    assert "--no-files" in cmd
    assert "jsonl" in cmd
    assert "250" in cmd
