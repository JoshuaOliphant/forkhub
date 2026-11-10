# ABOUTME: Captures immutable commit evidence separately from model interpretations.
# ABOUTME: Verifies referenced files and patch completeness through the git provider.
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from forkhub.interfaces import ProviderError
from forkhub.models import EvidenceChange, SignalEvidence

if TYPE_CHECKING:
    from forkhub.interfaces import GitProvider
    from forkhub.models import CommitDetails, FileChange


def patch_is_complete(change: FileChange) -> bool:
    if not change.patch:
        return False
    lines = change.patch.splitlines()
    additions = sum(line.startswith("+") for line in lines)
    deletions = sum(line.startswith("-") for line in lines)
    return additions == change.additions and deletions == change.deletions


def file_patch(change: FileChange) -> str:
    filename = change.filename
    previous = change.previous_filename or filename
    header = [f"diff --git a/{previous} b/{filename}"]
    if change.status == "added":
        header += ["new file mode 100644", "--- /dev/null", f"+++ b/{filename}"]
    elif change.status == "removed":
        header += ["deleted file mode 100644", f"--- a/{filename}", "+++ /dev/null"]
    else:
        if change.status in {"renamed", "copied"}:
            action = "rename" if change.status == "renamed" else "copy"
            header += [f"{action} from {previous}", f"{action} to {filename}"]
        header += [f"--- a/{previous}", f"+++ b/{filename}"]
    return "\n".join(header) + "\n" + (change.patch or "").rstrip("\n") + "\n"


def _verify_evidence(
    evidence: SignalEvidence, retrieved: dict[str, CommitDetails | str]
) -> SignalEvidence:
    evidence = evidence.model_copy(deep=True)
    if not evidence.commit_shas or not evidence.files:
        evidence.warnings.append("No immutable commits or relevant files were supplied.")
        return evidence
    complete = True
    fetched = False
    for sha in evidence.commit_shas:
        commit = retrieved[sha]
        if isinstance(commit, str):
            evidence.warnings.append(commit)
            complete = False
            continue
        fetched = True
        if commit.sha != sha:
            evidence.warnings.append(f"Commit {sha} returned a different SHA.")
            complete = False
            continue
        relevant = [change for change in commit.files if change.filename in evidence.files]
        if not commit.complete or not relevant:
            evidence.warnings.append(f"Commit {sha} has incomplete or unrelated file evidence.")
            complete = False
        for change in relevant:
            patch_complete = patch_is_complete(change)
            if not patch_complete:
                evidence.warnings.append(
                    f"Patch unavailable or incomplete: {sha}:{change.filename}"
                )
                complete = False
            evidence.changes.append(
                EvidenceChange(
                    commit_sha=sha,
                    filename=change.filename,
                    status=change.status,
                    patch=file_patch(change) if patch_complete else None,
                )
            )
    covered = {change.filename for change in evidence.changes if change.patch}
    if not set(evidence.files) <= covered:
        evidence.warnings.append("Some relevant files lack complete immutable patches.")
        complete = False
    evidence.verification_state = (
        "verified" if complete else "partial" if fetched else "unavailable"
    )
    evidence.verified_at = evidence.captured_at if complete else None
    return SignalEvidence.model_validate(evidence.model_dump())


async def capture_evidence(
    provider: GitProvider,
    repository: str,
    commit_shas: list[str],
    files: list[str],
    *,
    now: datetime | None = None,
) -> SignalEvidence:
    """Retrieve commits; failures return unavailable/partial evidence with warnings."""
    evidence = SignalEvidence(
        source_repository=repository,
        commit_shas=commit_shas,
        files=files,
        captured_at=now or datetime.now(UTC),
    )
    retrieved: dict[str, CommitDetails | str] = {}
    if evidence.commit_shas and evidence.files:
        owner, repo = evidence.source_repository.split("/")
        for sha in evidence.commit_shas:
            try:
                retrieved[sha] = await provider.get_commit(owner, repo, sha)
            except (ProviderError, OSError, TimeoutError) as exc:
                retrieved[sha] = f"Commit {sha} could not be retrieved: {exc}"
    return _verify_evidence(evidence, retrieved)
