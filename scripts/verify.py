# ABOUTME: Run ForkHub's local CI gates and check cached acceptance mappings against fresh tests.
# ABOUTME: Keep verification artifacts, production imports and Worker builds in disposable paths.

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def acceptance_rows(text: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in text.splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"AC-\d+", cells[1]):
            rows.append(tuple(cells))
    if not rows:
        raise ValueError("Acceptance cache contains no criteria")
    return rows


def junit_results(paths: list[Path]) -> dict[str, bool]:
    results = {}
    for path in paths:
        cases = list(ET.parse(path).getroot().iter("testcase"))
        if not cases:
            raise ValueError(f"No tests measured in {path}")
        for case in cases:
            filename = case.attrib["file"]
            module = filename.removesuffix(".py").replace("/", ".")
            classes = case.attrib["classname"].removeprefix(module).strip(".").replace(".", "::")
            name = "::".join(part for part in (filename, classes, case.attrib["name"]) if part)
            passed = not any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
            results[name] = results.get(name, True) and passed
    return results


def check_acceptance(text: str, results: dict[str, bool]) -> list[str]:
    checked = []
    for issue, criterion, node in acceptance_rows(text):
        label = f"{issue} {criterion}"
        if re.fullmatch(r"superseded by #\d+", node):
            checked.append(f"{label}: retired ({node})")
            continue
        if node not in results:
            raise ValueError(f"{label}: named test did not run: {node}")
        if not results[node]:
            raise ValueError(f"{label}: named test did not pass: {node}")
        checked.append(f"{label}: PASS {node}")
    return checked


def cache_freshness(text: str, comments: list[dict]) -> str | None:
    recorded = re.search(r"Cache refreshed: ([^\n]+)", text)
    if recorded is None:
        raise ValueError("Acceptance cache has no refresh timestamp")
    refreshed = datetime.fromisoformat(recorded[1].replace("Z", "+00:00"))
    edited = [
        datetime.fromisoformat(comment["updated_at"].replace("Z", "+00:00"))
        for comment in comments
        if "<!-- forkhub-acceptance -->" in (comment.get("body") or "")
    ]
    if edited and max(edited) > refreshed:
        return "Acceptance cache predates a remote AC-table edit; refresh docs/agents/acceptance.md"
    return None


def run(command: list[str], cwd: Path, environment: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def verify(root: Path, output: Path) -> None:
    environment = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    environment.pop("VIRTUAL_ENV", None)
    output.mkdir(parents=True, exist_ok=False)
    unit = output / "unit.xml"
    integration = output / "workers.xml"
    coverage = output / "coverage.json"
    table = (root / "docs/agents/acceptance.md").read_text()
    pages = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "repos/JoshuaOliphant/forkhub/issues/comments?per_page=100",
                "--paginate",
                "--slurp",
            ],
            cwd=root,
            env=environment,
            text=True,
        )
    )
    warning = cache_freshness(table, [comment for page in pages for comment in page])
    if warning:
        print("WARNING: " + warning, flush=True)
    run(["uv", "sync", "--frozen", "--extra", "claude", "--extra", "mcp"], root, environment)
    run(
        [
            "uv",
            "run",
            "pytest",
            "-x",
            "-q",
            "-o",
            "xfail_strict=true",
            "--junitxml=" + str(unit),
            "-o",
            "junit_family=xunit1",
            "--cov-report=json:" + str(coverage),
        ],
        root,
        environment,
    )
    measured = json.loads(coverage.read_text())["totals"]
    if measured["num_statements"] == 0 or measured["missing_lines"] != 0:
        raise ValueError("Coverage must measure source statements at 100%")
    paths = ["src/", "tests/", "examples/", "deploy/cloudflare/src/", "scripts/verify.py"]
    files = subprocess.check_output(
        ["uv", "run", "ruff", "check", "--show-files", *paths], cwd=root, env=environment, text=True
    ).splitlines()
    if not files:
        raise ValueError("Ruff selected no files")
    print(f"Ruff measured {len(files)} files", flush=True)
    run(["uv", "run", "ruff", "check", *paths], root, environment)
    run(["uv", "run", "ruff", "format", "--check", *paths], root, environment)
    run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_cloudflare_runtime.py",
            "tests/test_signal_provenance_acceptance.py",
            "-o",
            "addopts=",
            "-o",
            "junit_family=xunit1",
            "-o",
            "xfail_strict=true",
            "-m",
            "integration",
            "-x",
            "-q",
            "--junitxml=" + str(integration),
        ],
        root,
        environment,
    )
    production = {**environment, "UV_PROJECT_ENVIRONMENT": str(output / "production-env")}
    run(["uv", "sync", "--frozen", "--no-dev", "--extra", "mcp"], root, production)
    run(
        [
            str(output / "production-env/bin/python"),
            "-c",
            'import importlib.util, runpy; assert importlib.util.find_spec("pytest") is None; '
            'app = runpy.run_path("examples/chatgpt_mcp_cloudflare_access.py"); '
            'assert callable(app["create_app"]); print("Production MCP import passed")',
        ],
        root,
        production,
    )
    checkout = output / "worker-checkout"
    shutil.copytree(root / "src/forkhub", checkout / "src/forkhub")
    project = checkout / "deploy/cloudflare"
    shutil.copytree(
        root / "deploy/cloudflare",
        project,
        ignore=shutil.ignore_patterns(
            ".venv*",
            ".wrangler",
            "node_modules",
            "python_modules",
            "dist",
            "__pycache__",
            ".dev.vars*",
            ".env*",
        ),
    )
    worker_environment = dict(environment)
    worker_environment.pop("UV_PYTHON", None)
    worker_environment.pop("UV_PROJECT_ENVIRONMENT", None)
    run(["npm", "ci"], project, worker_environment)
    bundle = output / "worker-bundle"
    run(
        [
            "uv",
            "run",
            "--python",
            "3.14",
            "pywrangler",
            "deploy",
            "--dry-run",
            "--outdir",
            str(bundle),
        ],
        project,
        worker_environment,
    )
    if not any(path.is_file() for path in bundle.rglob("*")):
        raise ValueError("Worker dry-run produced no bundle files")
    for result in check_acceptance(table, junit_results([unit, integration])):
        print(result)
    print(f"Verified {measured['num_statements']} statements at 100%; artifacts: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="forkhub-verify-")) / "results"
    verify(Path(__file__).resolve().parents[1], output.resolve())


if __name__ == "__main__":
    main()
