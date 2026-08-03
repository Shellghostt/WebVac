"""
run.py — thin shim to the interactive WebVac launcher.

Prefer:  python run.py
Or:      python -m webvac.cli.interactive
CLI:     python -m webvac --url https://example.com ...
"""

from webvac.cli.interactive import main

if __name__ == "__main__":
    main()
