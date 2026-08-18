"""De-Caffeinator task runner for opt-in WebVac VAPT analysis."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from webvac.models.scan import ScanMetadata, TargetMetadata
from webvac.store.scan_session import ScanSession


@dataclass
class DecaffeinatorResult:
    session_dir: str
    output_dir: str
    meta_path: str
    run_report_path: Optional[str]
    summary_path: Optional[str]
    return_code: int


def _default_decaffeinator_root() -> str:
    repo_root = os.path.abspath(os.getcwd())
    return os.path.join(repo_root, "trial4", "blob-unpacker")


def resolve_decaffeinator_root(explicit_root: Optional[str] = None) -> str:
    root = os.path.abspath(explicit_root or _default_decaffeinator_root())
    run_py = os.path.join(root, "run.py")
    if not os.path.isfile(run_py):
        raise FileNotFoundError(
            f"De-Caffeinator launcher not found at {run_py}. "
            "Pass --decaffeinator-root or place it under trial4/blob-unpacker."
        )
    return root


def build_decaffeinator_command(args, *, output_dir: str, root: str) -> list[str]:
    run_py = os.path.join(root, "run.py")
    cmd = [sys.executable, run_py, args.url, "-o", output_dir]

    profile = getattr(args, "vapt_profile", "standard")
    if profile == "quick":
        cmd.append("--quick")
    elif profile == "stealth":
        cmd.append("--stealth")
    elif profile == "deep":
        cmd.append("--deep")

    cmd += [
        "-d",
        str(args.depth),
        "-p",
        str(args.max_pages or 100),
        "-c",
        str(args.concurrency),
        "-t",
        str(args.timeout),
        "--delay",
        str(int((args.delay_min or 0) * 1000)),
        "-f",
        getattr(args, "vapt_format", "json"),
    ]

    if getattr(args, "vapt_playwright", False):
        cmd.append("--playwright")
    if getattr(args, "vapt_wayback", False):
        cmd.append("--wayback")
    if getattr(args, "no_headless", False):
        cmd.append("--pw-visible")
    if getattr(args, "vapt_no_files", False):
        cmd.append("--no-files")

    return cmd


def _write_decaffeinator_meta(
    *,
    session: ScanSession,
    output_dir: str,
    root: str,
    cmd: list[str],
    profile: str,
) -> str:
    path = os.path.join(session.layout_paths()["meta"], "decaffeinator.json")
    payload = {
        "tool": "de-caffeinator",
        "root": root,
        "profile": profile,
        "output_dir": output_dir,
        "command": cmd,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def _discover_report_paths(output_dir: str, target_url: str) -> tuple[Optional[str], Optional[str]]:
    run_report = os.path.join(output_dir, "run-report.json")
    summary = os.path.join(output_dir, "summary.md")
    if os.path.isfile(run_report) or os.path.isfile(summary):
        return (
            run_report if os.path.isfile(run_report) else None,
            summary if os.path.isfile(summary) else None,
        )

    host = (urlparse(target_url).hostname or "").lower()
    if host:
        nested_run_report = os.path.join(output_dir, host, "run-report.json")
        nested_summary = os.path.join(output_dir, host, "summary.md")
        return (
            nested_run_report if os.path.isfile(nested_run_report) else None,
            nested_summary if os.path.isfile(nested_summary) else None,
        )
    return None, None


def run_decaffeinator_task(args) -> DecaffeinatorResult:
    root = resolve_decaffeinator_root(getattr(args, "decaffeinator_root", None))
    target = TargetMetadata(seed_url=args.url)
    scan = ScanMetadata(target=target, profile="decaffeinator", mode="vapt")
    session = ScanSession(args.output, scan)
    session.apply_parent_chain(getattr(args, "parent_scan_id", None))
    session.ensure_dirs()
    session.write_meta("decaffeinator", interrupted=False)

    output_dir = os.path.join(session.session_dir, "analysis", "decaffeinator")
    os.makedirs(output_dir, exist_ok=True)

    cmd = build_decaffeinator_command(args, output_dir=output_dir, root=root)
    meta_path = _write_decaffeinator_meta(
        session=session,
        output_dir=output_dir,
        root=root,
        cmd=cmd,
        profile=getattr(args, "vapt_profile", "standard"),
    )

    print(f"[VAPT] De-Caffeinator root -> {root}")
    print(f"[VAPT] Output -> {output_dir}")
    print(f"[VAPT] Launching: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=root, shell=False)
    run_report_path, summary_path = _discover_report_paths(output_dir, args.url)

    return DecaffeinatorResult(
        session_dir=session.session_dir,
        output_dir=output_dir,
        meta_path=meta_path,
        run_report_path=run_report_path,
        summary_path=summary_path,
        return_code=result.returncode,
    )
