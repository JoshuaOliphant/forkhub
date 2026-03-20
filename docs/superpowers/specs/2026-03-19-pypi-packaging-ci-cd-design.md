# PyPI Packaging & CI/CD Pipeline Design

## Overview

Package ForkHub for distribution on PyPI and add GitHub Actions workflows for continuous integration (lint + test) and automated publishing on tag push via Trusted Publishers.

## Goals

1. Publishable to PyPI as `forkhub` with complete metadata
2. CI pipeline gates PRs with lint and unit tests
3. Tag-based publishing with OIDC Trusted Publishers (no stored API tokens)
4. README badge for PyPI version

## Non-Goals

- Publishing to conda-forge or other registries
- Integration/slow tests in CI (require API keys and model downloads)
- Automated version bumping or changelog generation
- Publishing docs to Read the Docs

---

## 1. Package Metadata Changes

### pyproject.toml additions

```toml
[project]
license = "MIT"
keywords = ["github", "forks", "ai", "monitoring", "claude", "agent"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Version Control :: Git",
    "Typing :: Typed",
]

[project.urls]
Homepage = "https://github.com/JoshuaOliphant/forkhub"
Repository = "https://github.com/JoshuaOliphant/forkhub"
Issues = "https://github.com/JoshuaOliphant/forkhub/issues"
```

Note: `license = "MIT"` uses PEP 639 SPDX format, supported by hatchling >= 1.24. Hatchling auto-discovers `LICENSE` in the root, so no `license-files` directive is needed.

### Clean up dead dependency

Remove `"tomli>=2.2,<3;python_version<'3.12'"` — since `requires-python = ">=3.12"`, this dependency can never activate.

### Single source of truth for version

Configure hatchling to read the version from `src/forkhub/__init__.py` instead of maintaining it in two places:

```toml
[project]
dynamic = ["version"]   # remove the static version = "0.1.0" line

[tool.hatch.version]
path = "src/forkhub/__init__.py"
```

Hatchling will read `__version__ = "0.1.0"` from `__init__.py` as the single source of truth.

### LICENSE file

Standard MIT license file in repo root with copyright holder "Joshua Oliphant".

### Build configuration

Hatchling defaults use `.gitignore` to determine sdist contents, which should exclude `.env` and other untracked files. No explicit `[tool.hatch.build]` config needed since the `.gitignore` already covers `.env`.

### README.md badge

Add PyPI version badge at the top:

```markdown
[![PyPI version](https://img.shields.io/pypi/v/forkhub)](https://pypi.org/project/forkhub/)
```

### Existing py.typed

`src/forkhub/py.typed` already exists, so the `Typing :: Typed` classifier is accurate.

---

## 2. CI Workflow (`.github/workflows/ci.yml`)

**Triggers:** push to `main`, all pull requests

**Strategy:** Matrix across Python 3.12 and 3.13

### Jobs

#### `lint`
- Checkout code
- Install uv via `astral-sh/setup-uv@v5`
- `uv sync --frozen`
- `uv run ruff check src/ tests/`
- `uv run ruff format --check src/ tests/`

Note: Lint job runs on Python 3.12 only (no matrix needed — ruff doesn't vary by Python version).

#### `test`
- Checkout code
- Install uv via `astral-sh/setup-uv@v5` with `python-version: ${{ matrix.python-version }}`
- `uv sync --frozen`
- `uv run pytest -m "not integration and not slow" -x -q`

Matrix definition:
```yaml
strategy:
  matrix:
    python-version: ["3.12", "3.13"]
```

The `python-version` input to `astral-sh/setup-uv@v5` handles both installing the Python version and making it available to uv — no separate `uv python install` step needed.

Both jobs run in parallel (no dependency between them).

---

## 3. Publish Workflow (`.github/workflows/publish.yml`)

**Triggers:** push of tags matching `v*`

### Jobs

#### `test` (safety gate)
- Same as CI test job (Python 3.12 only, no matrix needed)
- Must pass before publish

#### `publish` (needs: test)
- Checkout code
- Install uv via `astral-sh/setup-uv@v5`
- `uv build` (produces sdist + wheel in `dist/`)
- Publish to PyPI using `pypa/gh-action-pypi-publish@release/v1`

Permissions required at the job level:
```yaml
permissions:
  id-token: write    # OIDC token for Trusted Publishers
  contents: read     # checkout access (must be explicit when setting permissions)
```

### Trusted Publishers Setup

Before the first tag-triggered publish, configure on pypi.org:
1. Go to pypi.org → Your projects → forkhub → Publishing (or "Add a new pending publisher" if first time)
2. Add GitHub as a Trusted Publisher:
   - Owner: `JoshuaOliphant`
   - Repository: `forkhub`
   - Workflow: `publish.yml`
   - Environment: (leave blank)

For a brand-new package, use "pending publisher" at https://pypi.org/manage/account/publishing/ — this reserves the name and configures trust before any upload.

---

## 4. Release Process

To cut a release:

```bash
# 1. Bump __version__ in src/forkhub/__init__.py (single source of truth)
# 2. Commit the version bump
git add src/forkhub/__init__.py
git commit -m "release: v0.1.0"
# 3. Tag and push
git tag v0.1.0
git push origin main --tags
# 4. publish.yml runs: test → build → publish to PyPI
```

---

## 5. Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add license, classifiers, URLs, keywords; remove static version; remove dead tomli dep; add hatch version config |
| `LICENSE` | Create | MIT license text |
| `.github/workflows/ci.yml` | Create | Lint + test on push/PR (create `.github/workflows/` directory) |
| `.github/workflows/publish.yml` | Create | Build + publish on tag |
| `README.md` | Modify | Add PyPI badge |
| `src/forkhub/__init__.py` | Verify | Confirm `__version__` exists (it does) |

---

## 6. Testing the Pipeline

Before the first real publish:
1. Merge CI workflow to `main`, verify lint+test jobs pass
2. Configure Trusted Publisher (pending publisher) on pypi.org
3. Tag `v0.1.0` and push to trigger publish workflow
4. Verify package appears at https://pypi.org/project/forkhub/

Skip TestPyPI — the safety gate (tests must pass before publish) plus Trusted Publishers (no secrets to leak) make the risk of a direct-to-PyPI first publish acceptable.

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| PyPI name `forkhub` taken before we publish | Name currently available; publish promptly |
| Trusted Publisher OIDC fails on first attempt | Fall back to API token in GitHub secret |
| `sentence-transformers` heavy dependency surprises users | Document in README; consider optional extras in future |
