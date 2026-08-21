from types import SimpleNamespace
from unittest.mock import patch

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
        root="D:/WebVac/decaffeinator/blob-unpacker",
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
        root="D:/WebVac/decaffeinator/blob-unpacker",
    )
    assert "--deep" in cmd
    assert "--playwright" in cmd
    assert "--wayback" in cmd
    assert "--pw-visible" in cmd
    assert "--no-files" in cmd
    assert "jsonl" in cmd
    assert "250" in cmd


def test_interactive_vapt_menu_builds_task_flags(tmp_path):
    from webvac.cli.interactive import _build_vapt_cmd_args

    run_py = tmp_path / "run.py"
    run_py.write_text("# stub\n", encoding="utf-8")
    answers = iter(
        [
            "deep — max depth, more pages, lower entropy",
            "Yes (--vapt-playwright)",
            "Yes (visible window)",
            "Yes (--vapt-wayback)",
            "No (--vapt-no-files)",
        ]
    )

    with patch(
        "webvac.vapt.decaffeinator.resolve_decaffeinator_root",
        return_value=str(tmp_path),
    ), patch("webvac.cli.interactive.prompt_choice", side_effect=lambda *a, **k: next(answers)):
        cmd = _build_vapt_cmd_args("https://example.com")

    assert cmd[:4] == ["--task", "vapt", "--url", "https://example.com"]
    assert "--vapt-profile" in cmd and "deep" in cmd
    assert "--vapt-playwright" in cmd
    assert "--no-headless" in cmd
    assert "--vapt-wayback" in cmd
    assert "--vapt-no-files" in cmd
