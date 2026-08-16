#!/usr/bin/env python3
"""
Headed CapSolver watch-demo (standalone — not wired into run.py).

  python examples/captcha_watch_demo.py
  python examples/captcha_watch_demo.py --only v2 --pause 8 --keep-open
  python examples/captcha_watch_demo.py --url https://www.google.com/recaptcha/api2/demo
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from webvac.cli.captcha_demo import DEMO_URLS, run_captcha_demo_from_args


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Watch CapSolver solve captcha test pages in a headed browser"
    )
    ap.add_argument("--only", help=f"Comma-separated: {', '.join(DEMO_URLS)}")
    ap.add_argument(
        "--url",
        action="append",
        default=[],
        help="Custom test page URL (repeatable)",
    )
    ap.add_argument("--pause", type=float, default=5.0)
    ap.add_argument("--settle-ms", type=int, default=2500)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--keep-open", action="store_true")
    ap.add_argument(
        "--headless",
        action="store_true",
        help="Run CapSolver demo without a visible window (default is headed for watching)",
    )
    args = ap.parse_args()
    args.captcha_demo = True
    args.captcha_demo_only = args.only
    args.captcha_demo_url = None
    args.captcha_demo_pause = args.pause
    args.captcha_demo_settle_ms = args.settle_ms
    args.captcha_timeout = args.timeout
    args.captcha_demo_keep_open = args.keep_open
    args.captcha_api_key = None
    args.headless = bool(args.headless)
    args.no_headless = not args.headless
    raise SystemExit(asyncio.run(run_captcha_demo_from_args(args)))


if __name__ == "__main__":
    main()
