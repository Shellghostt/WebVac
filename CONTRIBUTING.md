# Contributing to WebVac

Thanks for taking the time to contribute. WebVac is a small, actively
maintained project, so focused bug fixes, tests, and documentation improvements
are genuinely useful. This guide covers everything needed to go from a fresh
clone to a mergeable pull request.

If anything here is unclear or out of date, open an issue — that is a
contribution too.

## Good places to start

- Issues labelled [`good first issue`](https://github.com/Shellghostt/WebVac/labels/good%20first%20issue)
- Reproducing a reported bug with a minimal command and posting the output
- Improving docs, examples, or error messages
- Adding tests for behaviour that is currently untested

Before starting on a larger change, open or comment on an issue so we can agree
on the direction. It avoids duplicated work and surprise rework.

## Development setup

### 1. Fork and clone

Fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/<your-username>/WebVac.git
cd WebVac
```

The `decaffeinator/` submodule is only needed for the optional VAPT task
(`--task vapt`). For normal scrape/crawl work you can skip it:

```bash
# optional, VAPT only
git submodule update --init --recursive
```

### 2. Create a virtual environment and install

Windows PowerShell:

```powershell
python -m venv .venv
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& .\.venv\Scripts\Activate.ps1)
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m patchright install
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m patchright install
```

`pip install -e ".[dev]"` installs WebVac in editable mode plus the test
dependencies (`pytest`). If you prefer `requirements.txt`, install it first and
then run `pip install -e ".[dev]"` as well; the extra is what adds pytest.

### 3. Verify the setup

```bash
python -m webvac --doctor
```

The doctor preflight launches a real browser and checks the output directory,
proxies, pipelines, and CapSolver configuration. A few warnings are normal on a
fresh machine (no proxy file, no CapSolver key). Failures mean the environment
is not ready.

## Running the checks

Run these before opening or updating a pull request:

```bash
python -m pytest tests -q
python -m webvac --doctor
```

- The unit tests in `tests/` are browser-free and network-free, so they are fast
  and should pass on any machine.
- The doctor smoke check needs the Patchright browser installed (step 2).

Extra checks that CI also performs:

```bash
python -m compileall -q webvac
```

CI runs on Ubuntu and Windows with Python 3.11 and 3.12. The project supports
**Python 3.11+**, so avoid syntax that only exists in 3.12. In particular, an
f-string expression cannot contain a backslash on 3.11 (PEP 701 is 3.12+); build
that string outside the f-string instead.

### Docker (optional)

If you are changing the container image:

```bash
docker build -t webvac:test .
docker run --rm webvac:test --doctor
docker run --rm webvac:test --help
```

## Branch and pull-request workflow

1. Branch from the latest `main`:

   ```bash
   git fetch origin
   git switch -c fix/short-description origin/main
   ```

   Use a short, descriptive branch name, for example `fix/robots-crawl-delay`,
   `docs/contributing-guide`, or `test/storage-roundtrip`.

2. Keep the change focused. One logical change per pull request is much easier
   to review and merge than a mixed bag of unrelated edits.

3. Add or update tests for behaviour changes. Bug fixes should include a test
   that fails before the fix and passes after it.

4. Commit with a clear message. Conventional prefixes are preferred but not
   enforced:

   ```text
   fix: respect crawl-delay when --ignore-crawl-delay is absent
   test: cover storage round-trip for empty records
   docs: document the Docker workflow
   ci: pin the Ubuntu runner image
   build: add Dockerfile for scrape mode
   ```

5. Push and open a pull request **against `main`**. Describe:

   - what changed and why,
   - how you verified it (commands and output),
   - the issue it closes (`Closes #123`).

6. Make sure CI is green. If a maintainer asks for changes, push follow-up
   commits to the same branch; do not force-push after review unless asked.

7. Pull requests are squash-merged by a maintainer once CI passes and review is
   complete.

## Adding tests

Tests live in `tests/` and use pytest. They should not need a browser, network
access, or real credentials. Use `tmp_path` for filesystem work and keep each
test independent.

A minimal pattern:

```python
def test_something(tmp_path):
    target = tmp_path / "data.json"
    # arrange -> act -> assert
    assert target.exists() is False
```

Run one file or one test while iterating:

```bash
python -m pytest tests/test_storage.py -q
python -m pytest tests/test_proxy.py::test_name -q
```

## Code style

- Follow the existing structure and naming in the package you are editing.
- Keep changes small and readable; avoid unrelated reformatting.
- Prefer the standard library and existing dependencies. Discuss new runtime
  dependencies in an issue first.
- Preserve Python 3.11 compatibility (see the CI note above).
- Do not commit secrets, proxy credentials, session files, `scraped_data/`, or
  local virtual environments. They are covered by `.gitignore`; keep it that way.

## Reporting bugs

A useful bug report includes:

- the exact command you ran (redact secrets),
- what you expected and what happened instead,
- your OS and Python version,
- the output of `python -m webvac --doctor`,
- relevant logs or a small snippet of `{scan_session}/network/*.json` if the
  failure is a blocked/failed page.

Please do not paste credentials, tokens, or private target data into an issue.

## Security

If you believe you have found a security issue, do not open a public issue.
Follow [`docs/SECURITY.md`](docs/SECURITY.md) and report it privately to the
maintainer.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
