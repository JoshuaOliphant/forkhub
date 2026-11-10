# ABOUTME: Tests immutable evidence capture and truthful verification states.
# ABOUTME: Exercises provider commit identity, relevant file association and patch completeness.
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from forkhub.models import (
    CommitDetails,
    EvidenceChange,
    FileChange,
    Signal,
    SignalCategory,
    SignalEvidence,
)
from forkhub.services.evidence import capture_evidence, file_patch

SHA = "a" * 40
NOW = datetime(2026, 11, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("verified", "verified"),
        ("missing_commit", "unavailable"),
        ("missing_files", "unavailable"),
        ("missing_shas", "unavailable"),
        ("wrong_sha", "partial"),
        ("paginated", "partial"),
        ("unrelated", "partial"),
        ("binary", "partial"),
        ("truncated", "partial"),
        ("missing_file", "partial"),
    ],
)
async def test_capture_verifies_only_complete_relevant_commit_evidence(provider, case, expected):
    files = [] if case == "missing_files" else ["file.py"]
    if case == "missing_file":
        files.append("missing.py")
    shas = [] if case == "missing_shas" else [SHA]
    change = FileChange(
        filename="other.py" if case == "unrelated" else "file.py",
        status="modified",
        additions=2 if case == "truncated" else 1,
        deletions=1,
        patch=None if case == "binary" else "@@ -1 +1 @@\n-old\n+value",
    )
    if case != "missing_commit":
        provider.commits[f"alice/repo@{SHA}"] = CommitDetails(
            sha="b" * 40 if case == "wrong_sha" else SHA,
            files=[change],
            complete=case != "paginated",
        )
    evidence = await capture_evidence(provider, "alice/repo", shas, files, now=NOW)
    assert evidence.verification_state == expected
    assert evidence.commit_shas == shas
    assert evidence.source_repository == "alice/repo"
    assert evidence.files == files
    assert evidence.verified_at == (NOW if expected == "verified" else None)
    assert evidence.captured_at == NOW
    assert provider.commit_calls == (
        [] if case in {"missing_files", "missing_shas"} else [f"alice/repo@{SHA}"]
    )
    assert bool(evidence.warnings) == (expected != "verified")
    if case == "missing_commit":
        assert evidence.warnings[0].startswith(f"Commit {SHA} could not be retrieved:")
        assert "Commit unavailable" in evidence.warnings[0]
    if expected == "verified":
        assert evidence.changes[0].patch is not None
        assert evidence.changes[0].patch.endswith("-old\n+value\n")
        assert "diff --git a/file.py b/file.py" in evidence.changes[0].patch


@pytest.mark.parametrize("status", ["added", "removed", "modified", "renamed", "copied"])
def test_file_patch_preserves_change_paths(status):
    change = FileChange(
        filename="file.py",
        previous_filename="old.py",
        status=status,
        additions=1,
        deletions=0,
        patch="@@ -0,0 +1 @@\n+value\n",
    )
    patch = file_patch(change)
    assert patch.startswith("diff --git a/old.py b/file.py\n")
    assert patch.endswith("+value\n")
    if status in {"renamed", "copied"}:
        action = "rename" if status == "renamed" else "copy"
        assert f"{action} from old.py\n{action} to file.py" in patch
    if status == "added":
        assert "--- /dev/null" in patch
    if status == "removed":
        assert "+++ /dev/null" in patch


@pytest.mark.parametrize(
    "changes",
    [[], [{"commit_sha": SHA, "filename": "other.py", "status": "added", "patch": "patch"}]],
)
def test_verified_evidence_requires_patch_for_every_commit_and_file(changes):
    with pytest.raises(ValidationError, match="patches"):
        SignalEvidence(
            source_repository="alice/repo",
            commit_shas=[SHA],
            files=["file.py"],
            changes=changes,
            verification_state="verified",
            verified_at=NOW,
        )


def test_verified_evidence_requires_commits_files_and_time():
    with pytest.raises(ValidationError, match="requires commits"):
        SignalEvidence(source_repository="alice/repo", verification_state="verified")


@pytest.mark.parametrize("sha", ["main", "abcdef", "z" * 40])
async def test_capture_rejects_mutable_or_invalid_refs(provider, sha):
    with pytest.raises(ValidationError):
        await capture_evidence(provider, "alice/repo", [sha], ["file.py"])
    assert provider.commit_calls == []


def test_signal_hydrates_persisted_evidence_without_inventing_legacy_provenance():
    evidence = SignalEvidence(source_repository="alice/repo", commit_shas=[SHA])
    signal = Signal.model_validate(
        {
            "tracked_repo_id": "r",
            "category": "fix",
            "summary": "interpretation",
            "evidence": evidence.model_dump_json(),
        }
    )
    assert signal.evidence == evidence
    assert (
        Signal(tracked_repo_id="r", category=SignalCategory.FIX, summary="legacy").evidence is None
    )


@pytest.mark.parametrize(
    "override", [{"patch": None}, {"filename": "alien.py"}, {"commit_sha": "b" * 40}]
)
def test_verified_evidence_rejects_unpatchable_or_unrelated_changes(override):
    change = {"commit_sha": SHA, "filename": "file.py", "status": "added", "patch": "patch"}
    with pytest.raises(ValidationError, match="Verified changes"):
        SignalEvidence(
            source_repository="alice/repo",
            commit_shas=[SHA],
            files=["file.py"],
            verified_at=NOW,
            verification_state="verified",
            changes=[EvidenceChange.model_validate({**change, **override})],
        )


def test_verified_evidence_requires_timezone_aware_timestamp():
    with pytest.raises(ValidationError, match="timezone-aware"):
        SignalEvidence(
            source_repository="alice/repo",
            commit_shas=[SHA],
            files=["file.py"],
            verified_at=datetime(2026, 11, 10),
            verification_state="verified",
            changes=[
                EvidenceChange(commit_sha=SHA, filename="file.py", status="added", patch="patch")
            ],
        )


@pytest.mark.parametrize(
    "field,value", [("commit_shas", [SHA, SHA]), ("files", ["file.py", "file.py"])]
)
def test_evidence_rejects_duplicate_commit_or_file_references(field, value):
    with pytest.raises(ValidationError, match="unique"):
        SignalEvidence(source_repository="alice/repo", **{field: value})


async def test_signal_rejects_verified_evidence_for_different_files(provider):
    provider.commits[f"alice/repo@{SHA}"] = CommitDetails(
        sha=SHA,
        files=[
            FileChange(
                filename="file.py",
                status="added",
                additions=1,
                deletions=0,
                patch="@@ -0,0 +1 @@\n+value",
            )
        ],
    )
    evidence = await capture_evidence(provider, "alice/repo", [SHA], ["file.py"])
    with pytest.raises(ValidationError, match="must match signal"):
        Signal(
            tracked_repo_id="r",
            category=SignalCategory.FIX,
            summary="claim",
            files_involved=["different.py"],
            evidence=evidence,
        )
    assert (
        Signal(
            tracked_repo_id="r",
            category=SignalCategory.FIX,
            summary="claim",
            files_involved=["file.py"],
            evidence=evidence,
        ).evidence
        == evidence
    )


def test_evidence_rejects_empty_file_names():
    with pytest.raises(ValidationError, match="at least 1 character"):
        SignalEvidence(source_repository="alice/repo", files=[""])
