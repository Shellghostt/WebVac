#!/usr/bin/env python3
"""Generate docs/webvac-architecture.pdf from the one-page HTML diagram."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "docs", "webvac-architecture-one-page.html")
PDF = os.path.join(ROOT, "docs", "webvac-architecture.pdf")


def _html_uri() -> str:
    return "file:///" + HTML.replace("\\", "/")


def _try_chrome_family() -> bool:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for exe in candidates:
        if not exe or not os.path.isfile(exe):
            continue
        cmd = [
            exe,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={PDF}",
            _html_uri(),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
            if os.path.isfile(PDF) and os.path.getsize(PDF) > 500:
                print(f"[OK] PDF written: {PDF}")
                return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
    return False


def main() -> int:
    if not os.path.isfile(HTML):
        print(f"[Error] Missing {HTML}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(PDF), exist_ok=True)

    if _try_chrome_family():
        return 0

    # Fallback: open HTML and print instructions
    print("[Info] Could not auto-generate PDF (Chrome/Edge headless not found).")
    print(f"[Info] Open in browser and Print → Save as PDF (landscape):")
    print(f"       {HTML}")
    if sys.platform == "win32":
        os.startfile(HTML)  # noqa: S606 — Windows convenience
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", HTML])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
