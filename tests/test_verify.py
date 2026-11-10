# ABOUTME: Check acceptance mappings against actual JUnit outcomes and remote table timestamps.
# ABOUTME: Reject missing, failed or skipped criteria while retaining retired issue rows.

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from scripts.verify import acceptance_rows, cache_freshness, check_acceptance, junit_results


@pytest.mark.parametrize("text", ["", "| Issue | AC | Test |", "| #35 | AC-1 | a | extra |"])
def test_acceptance_cache_must_contain_criteria(text):
    with pytest.raises(ValueError, match="no criteria"):
        acceptance_rows(text)


def test_acceptance_checks_each_issue_and_reports_retired_rows():
    table = """| Issue | AC | Test |
|---|---|---|
| #35 | AC-1 | `tests/test_models.py::test_shape[value]` |
| #12 | AC-3 | superseded by #35 |
| #35 | AC-2 | tests/test_database.py::TestDatabase::test_evidence |
"""
    output = check_acceptance(
        table,
        {
            "tests/test_models.py::test_shape[value]": True,
            "tests/test_database.py::TestDatabase::test_evidence": True,
        },
    )
    assert output == [
        "#35 AC-1: PASS tests/test_models.py::test_shape[value]",
        "#12 AC-3: retired (superseded by #35)",
        "#35 AC-2: PASS tests/test_database.py::TestDatabase::test_evidence",
    ]


@pytest.mark.parametrize("results,reason", [({}, "did not run"), ({"a": False}, "did not pass")])
def test_acceptance_rejects_missing_or_unsuccessful_test(results, reason):
    with pytest.raises(ValueError, match=reason):
        check_acceptance("| #35 | AC-1 | a |", results)


@pytest.mark.parametrize("outcome", [None, "failure", "error", "skipped"])
def test_junit_reads_module_class_parameter_and_nonpassing_outcomes(tmp_path, outcome):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    case = ET.SubElement(
        suite,
        "testcase",
        {
            "file": "tests/test_models.py",
            "classname": "tests.test_models.TestSignal",
            "name": "test_shape[value]",
        },
    )
    if outcome:
        ET.SubElement(case, outcome)
    path = tmp_path / "results.xml"
    ET.ElementTree(root).write(path)
    assert junit_results([path]) == {
        "tests/test_models.py::TestSignal::test_shape[value]": outcome is None,
    }


def test_junit_rejects_empty_report(tmp_path):
    path = tmp_path / "empty.xml"
    path.write_text("<testsuites />")
    with pytest.raises(ValueError, match="No tests measured"):
        junit_results([path])


def test_junit_does_not_hide_failure_when_test_is_repeated(tmp_path):
    paths = []
    for index, outcome in enumerate(["<failure />", ""]):
        path = tmp_path / f"{index}.xml"
        path.write_text(
            '<testsuites><testsuite><testcase file="tests/test_models.py" '
            'classname="tests.test_models" name="test_shape">'
            + outcome
            + "</testcase></testsuite></testsuites>"
        )
        paths.append(path)
    assert junit_results(paths) == {"tests/test_models.py::test_shape": False}


@pytest.mark.parametrize(
    "updated,marked,stale",
    [
        ("2026-11-09T12:00:00Z", True, False),
        ("2026-11-10T12:00:00Z", True, False),
        ("2026-11-11T12:00:00Z", True, True),
        ("2026-11-11T12:00:00Z", False, False),
    ],
)
def test_acceptance_cache_warns_only_for_newer_remote_table_edits(updated, marked, stale):
    warning = cache_freshness(
        "Cache refreshed: 2026-11-10T12:00:00Z",
        [
            {
                "updated_at": updated,
                "body": "<!-- forkhub-acceptance -->" if marked else None,
            }
        ],
    )
    assert bool(warning) is stale


def test_acceptance_cache_requires_refresh_timestamp():
    with pytest.raises(ValueError, match="no refresh timestamp"):
        cache_freshness("", [])
