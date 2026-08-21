# Changelog

## 0.3.0 - 2026-08-18

- add an opt-in `--task vapt` workflow powered by De-Caffeinator
- expose De-Caffeinator from the interactive launcher (`python run.py` → VAPT / JS analysis)
- store VAPT artifacts inside the normal scan session layout under `analysis/decaffeinator/`
- vendor De-Caffeinator as the `decaffeinator/` submodule (replacing the old `trial4/` path)
- add task-aware doctor checks for De-Caffeinator root and Node/npx availability
- remove the old in-tree VAPT pipeline and simplify WebVac around scrape-first workflows
- update README setup/docs for `--doctor`, direct-proxy fallback behavior, and the new VAPT task
- license the project under MIT
