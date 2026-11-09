# Changelog

## 0.3.1 - 2026-11-09

- publish the package to PyPI (`pip install webvac`) with a tag-triggered release workflow
- single-source the version from `webvac.__version__`
- add a 43-test pytest suite covering proxy parsing, storage, and robots behaviour
- add GitHub Actions CI on Ubuntu and Windows for Python 3.11 and 3.12
- add a Docker image for scrape mode with Patchright Chromium preinstalled
- add `CONTRIBUTING.md` and link it from the README
- fix report HTML generation on Python 3.11 and correct the Contact tab's page index

## 0.3.0 - 2026-08-18

- add an opt-in `--task vapt` workflow powered by De-Caffeinator
- expose De-Caffeinator from the interactive launcher (`python run.py` → VAPT / JS analysis)
- store VAPT artifacts inside the normal scan session layout under `analysis/decaffeinator/`
- vendor De-Caffeinator as the `decaffeinator/` submodule (replacing the old `trial4/` path)
- drop session-report / planning docs and the in-repo `tests/` suite from the public tree
- ignore Cloudflare RUM/beacon traffic in network-debug challenge classification
- enable CapSolver by default when an API key is present (`--captcha-solver none` to disable)
- stamp `meta.completed_at` when scrape/VAPT sessions finish
- expand full project documentation under `docs/` (overview, workflows, architecture deep dives, config, security)
- add task-aware doctor checks for De-Caffeinator root and Node/npx availability
- remove the old in-tree VAPT pipeline and simplify WebVac around scrape-first workflows
- update README setup/docs for `--doctor`, direct-proxy fallback behavior, and the new VAPT task
- license the project under MIT
