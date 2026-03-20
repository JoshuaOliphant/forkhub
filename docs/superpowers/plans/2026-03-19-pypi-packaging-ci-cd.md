# PyPI Packaging & CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package ForkHub for PyPI distribution with GitHub Actions CI (lint + test) and tag-triggered publishing via Trusted Publishers.

**Architecture:** Two GitHub Actions workflows — `ci.yml` for PR gating (lint + test matrix) and `publish.yml` for tag-triggered PyPI publishing via OIDC. Package metadata enhanced in `pyproject.toml` with hatchling dynamic versioning from `__init__.py`.

**Tech Stack:** hatchling (build backend), GitHub Actions, astral-sh/setup-uv, pypa/gh-action-pypi-publish, ruff, pytest

**Spec:** `docs/superpowers/specs/2026-03-19-pypi-packaging-ci-cd-design.md`

---

### Task 1: Create LICENSE file

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Create the MIT LICENSE file**

```text
MIT License

Copyright (c) 2026 Joshua Oliphant

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: add MIT license file"
```

---

### Task 2: Add version test (TDD)

**Files:**
- Create: `tests/test_packaging.py`

- [ ] **Step 1: Write the failing test**

```python
# ABOUTME: Tests for package metadata and version consistency.
# ABOUTME: Verifies __version__ exists and build metadata is correct.

import re

from forkhub import __version__


def test_version_exists():
    """Package exposes a __version__ string."""
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_is_valid_semver():
    """Version follows semver-like format (X.Y.Z)."""
    assert re.match(r"^\d+\.\d+\.\d+", __version__)


def test_version_matches_importlib_metadata():
    """__version__ matches what importlib.metadata reports."""
    from importlib.metadata import version

    assert __version__ == version("forkhub")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: All 3 tests pass (these test existing behavior before we change anything).

- [ ] **Step 3: Commit**

```bash
git add tests/test_packaging.py
git commit -m "test: add package version and metadata tests"
```

---

### Task 3: Update pyproject.toml with PyPI metadata

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace static version with dynamic versioning**

Remove line `version = "0.1.0"` and add `dynamic = ["version"]` to the `[project]` section. Add a new `[tool.hatch.version]` section:

```toml
[tool.hatch.version]
path = "src/forkhub/__init__.py"
```

- [ ] **Step 2: Add license, keywords, classifiers, and URLs**

Add these fields to `[project]`:

```toml
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
```

Add a new section:

```toml
[project.urls]
Homepage = "https://github.com/JoshuaOliphant/forkhub"
Repository = "https://github.com/JoshuaOliphant/forkhub"
Issues = "https://github.com/JoshuaOliphant/forkhub/issues"
```

- [ ] **Step 3: Remove dead tomli dependency**

Remove this line from `dependencies`:

```toml
"tomli>=2.2,<3;python_version<'3.12'",
```

This dependency can never activate since `requires-python = ">=3.12"`.

- [ ] **Step 4: Re-sync and verify the build works**

```bash
uv sync
uv build
```

Expected: Successfully produces files matching `dist/forkhub-0.1.0*` (sdist and wheel).

Then verify version is still read correctly:

Run: `uv run python -c "import forkhub; print(forkhub.__version__)"`
Expected: `0.1.0`

- [ ] **Step 5: Run the packaging tests to confirm nothing broke**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: All 3 tests pass.

- [ ] **Step 6: Clean up dist and commit**

```bash
rm -rf dist/
git add pyproject.toml
git commit -m "chore: add PyPI metadata, dynamic versioning, remove dead tomli dep"
```

---

### Task 4: Add PyPI badge to README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add badge on line 2 (between heading and description)**

Insert a blank line after `# ForkHub` on line 1, then the badge, then a blank line before the existing description paragraph:

```markdown
# ForkHub

[![PyPI version](https://img.shields.io/pypi/v/forkhub)](https://pypi.org/project/forkhub/)

Monitor GitHub fork constellations with AI-powered analysis.
```

Note: Do NOT add `pip install forkhub` instructions yet — the package is not published. The badge gracefully shows "not found" until first publish. Add pip install instructions after the first successful publish.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add PyPI version badge to README"
```

---

### Task 5: Create CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write ci.yml**

The lint and test jobs run in parallel (no `needs:` dependency between them). Lint runs on Python 3.12 only (ruff doesn't vary by version). Tests run across the 3.12/3.13 matrix.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: uv sync --frozen
      - run: uv run pytest -m "not integration and not slow" -x -q
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint and test workflow"
```

---

### Task 6: Create publish workflow

**Files:**
- Create: `.github/workflows/publish.yml`

- [ ] **Step 1: Write publish.yml**

The `publish` job requires explicit `id-token: write` for OIDC and `contents: read` for checkout (setting any permission resets defaults).

```yaml
name: Publish to PyPI

on:
  push:
    tags: ["v*"]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv sync --frozen
      - run: uv run pytest -m "not integration and not slow" -x -q

  publish:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add PyPI publish workflow with Trusted Publishers"
```

---

### Task 7: Verify everything works end-to-end

**Files:** (no changes, verification only)

- [ ] **Step 1: Run linting**

Run: `uv run ruff check src/ tests/`
Expected: No errors

Run: `uv run ruff format --check src/ tests/`
Expected: All files formatted correctly

- [ ] **Step 2: Run all non-integration tests**

Run: `uv run pytest -m "not integration and not slow" -x -q`
Expected: All tests pass (including the new `test_packaging.py` tests)

- [ ] **Step 3: Verify build produces correct metadata**

```bash
uv build
ls dist/forkhub-*
```

Expected: Two files — an sdist (`.tar.gz`) and a wheel (`.whl`).

- [ ] **Step 4: Verify package metadata**

```bash
uv run python -c "
from importlib.metadata import metadata
m = metadata('forkhub')
print(f'Name: {m[\"Name\"]}')
print(f'Version: {m[\"Version\"]}')
print(f'License: {m[\"License-Expression\"]}')
print(f'Author: {m[\"Author-email\"]}')
"
```

Expected:
```
Name: forkhub
Version: 0.1.0
License: MIT
Author: Joshua Oliphant <joshua.oliphant@hey.com>
```

- [ ] **Step 5: Clean up dist and push**

```bash
rm -rf dist/
git push origin main
```

Expected: CI workflow triggers and both lint and test jobs pass. Check at the repo's Actions tab.

---

## Post-Implementation: Manual Steps (not automated)

These require human action on pypi.org:

1. Go to https://pypi.org/manage/account/publishing/
2. Add a **pending publisher**:
   - Package name: `forkhub`
   - Owner: `JoshuaOliphant`
   - Repository: `forkhub`
   - Workflow: `publish.yml`
   - Environment: (leave blank)
3. Once configured, verify `__version__` in `src/forkhub/__init__.py` matches the tag you're about to create, then tag and push:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Verify at https://pypi.org/project/forkhub/
5. After successful publish, update README.md to add `pip install forkhub` instructions

**If Trusted Publishers OIDC fails:** Fall back to a PyPI API token. Generate one at pypi.org → Account settings → API tokens, add it as a GitHub secret named `PYPI_API_TOKEN`, and update `publish.yml` to use `password: ${{ secrets.PYPI_API_TOKEN }}` in the publish step.
