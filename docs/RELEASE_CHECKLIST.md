# WebVac release checklist

Use this before pushing a meaningful change, cutting a release, or handing the repo to another operator.

---

## 1. Environment sanity

- `python -m patchright install` has been run on the machine that will execute scrapes.
- Virtualenv / dependencies are installed and import cleanly.
- `git submodule update --init --recursive` has been run if `--task vapt` is expected to work.
- `decaffeinator/blob-unpacker/run.py` exists locally.

---

## 2. Doctor checks

Run:

```bash
python -m webvac --doctor
```

If you use VAPT, also run:

```bash
python -m webvac --doctor --task vapt --url https://example.com
```

Verify:

- Patchright launches successfully
- output directory is writable
- proxy file loads
- dead proxies only warn if direct-IP fallback is acceptable
- CapSolver key behavior matches expectation
- De-Caffeinator root and `node` / `npx` are available for VAPT

---

## 3. CapSolver behavior

- If `capsolver.key` or `CAPSOLVER_API_KEY` is present, remember CapSolver is **enabled by default**.
- If a run must not spend solver credits, pass:

```bash
python -m webvac --captcha-solver none --url https://example.com
```

- Do not commit real API keys.

---

## 4. Proxy behavior

- Confirm whether `proxies.txt` is intended to be used.
- If proxies are dead, remember WebVac will continue on the **real IP** by design.
- If that is not acceptable for the target, fix or remove the proxy file before running.

---

## 5. Auth / local secrets

- `auth_creds.json`, `capsolver.key`, `proxies.txt`, `sessions/`, and `.env` remain local only.
- If session encryption is required, set `WEBVAC_SESSION_KEY`.
- No screenshots, dumps, or session files with sensitive data are being committed.

---

## 6. Scrape / crawl smoke checks

Recommended minimums after meaningful runtime changes:

- single-page scrape against a known-good JS site
- small crawl (`--max-pages 3` or `5`)
- auth-wall detection sanity check
- one run with network debug enabled

Suggested commands:

```bash
python -m webvac --url https://example.com --mode single
python -m webvac --url https://example.com --mode crawl --depth 2 --max-pages 5
```

---

## 7. VAPT smoke checks

If VAPT-related code or docs changed:

```bash
python -m webvac --task vapt --url https://example.com --vapt-profile quick
```

Verify:

- output lands under `analysis/decaffeinator/`
- `meta/meta.json` gets `completed_at`
- `meta/decaffeinator.json` is written

---

## 8. Docs / changelog

- Root `README.md` still matches actual defaults and flags.
- `docs/` references match current code behavior.
- `CHANGELOG.md` mentions user-visible behavior changes.

---

## 9. Git hygiene

- No local secrets staged
- No accidental screenshots / dumps staged
- No stale generated files staged unless intentional
- Submodule path is still `decaffeinator/`

Quick checks:

```bash
git status --short
git submodule status
```

---

## 10. PyPI publish

Publishing runs from the tag-driven `Release` workflow
(`.github/workflows/release.yml`) using PyPI Trusted Publishing, so no API token
is stored in the repository.

One-time setup:

- Create the `webvac` project on PyPI, or add a pending trusted publisher so the
  first successful run creates it.
- Trusted publisher fields: owner `Shellghostt`, repository `WebVac`, workflow
  `release.yml`.

Before tagging:

- `python -m build` and `python -m twine check dist/*` pass locally.
- `webvac/__init__.py` `__version__` equals the intended tag (`vX.Y.Z`).
- `CHANGELOG.md` has an entry for the version.

Then publish:

```bash
git tag v0.3.0
git push origin v0.3.0
```

The workflow refuses to publish if the tag and package version disagree. After
it completes, verify with `pip install webvac` in a clean environment.

---

## 11. Release-ready outcome

You are in good shape when:

- doctor passes or only has understood warnings
- scrape path works
- VAPT path works if advertised
- docs match behavior
- secrets stay local
