# ABOUTME: Exercise schema-paired release bundles against real disposable SQLite caches.
# ABOUTME: Reject unverified, truncated, tampered and mismatched release evidence.

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from examples.prepare_signal_release import main
from forkhub.models import CommitDetails, FileChange
from forkhub.services.evidence import capture_evidence
from forkhub.services.signal_release import compare_signal_release, prepare_signal_release
from tests.stubs import make_signal, make_tracked_repo


@pytest.mark.parametrize(
    "case", ["verified", "legacy", "partial", "signals_truncated", "catalog_truncated"]
)
async def test_release_bundle(db, provider, tmp_path, case, capsys):
    repo = make_tracked_repo(full_name="alice/repo")
    await db.insert_tracked_repo(repo)
    sha = "a" * 40
    provider.commits[f"alice/fork@{sha}"] = CommitDetails(
        sha=sha,
        files=[
            FileChange(
                filename="file.py",
                status="modified",
                additions=1,
                deletions=1,
                patch="@@ -1 +1 @@\n-old\n+new",
            )
        ],
        complete=case != "partial",
    )
    evidence = await capture_evidence(provider, "alice/fork", [sha], ["file.py"])
    for _ in range(51 if case == "signals_truncated" else 1):
        await db.insert_signal(
            make_signal(
                None,
                repo["id"],
                files_involved=json.dumps(["file.py"]),
                evidence=None if case == "legacy" else evidence.model_dump_json(),
            )
        )
    if case == "catalog_truncated":
        for index in range(50):
            await db.insert_tracked_repo(
                make_tracked_repo(
                    owner="alice",
                    name=f"repo{index}",
                    full_name=f"alice/repo{index}",
                    github_id=index + 987,
                )
            )
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as connection:
        await db._db.backup(connection)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE signals SET summary = 'committed marker'")
        writer.commit()
        writer.execute("UPDATE signals SET summary = 'uncommitted marker'")
        before = hashlib.sha256(source.read_bytes()).digest()
        output = tmp_path / "release"
        args = [
            "prepare",
            "--source",
            str(source),
            "--output",
            str(output),
            "--username",
            " ALICE ",
            "--repository",
            "alice/repo",
            "--confirm-single-user",
        ]
        if case != "verified":
            with pytest.raises(ValueError, match="50-row|verified immutable"):
                main(args)
            assert not (output / "manifest.json").exists()
            assert source.read_bytes() and hashlib.sha256(source.read_bytes()).digest() == before
            return
        main(args)
        assert '"hosted_acceptance": "pending"' in capsys.readouterr().out
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["counts"]["signals"] == 1
        assert manifest["username"] == "alice"
        assert manifest["authenticated_chatgpt_acceptance"] == "pending"
        assert output.stat().st_mode & 0o777 == 0o700
        for path in output.iterdir():
            assert path.stat().st_mode & 0o777 == 0o600
        assert hashlib.sha256(source.read_bytes()).digest() == before
        with pytest.raises(FileExistsError):
            main(args)
        expected = json.loads((output / "expected.json").read_text())
        assert expected["list_cached_signals"]["signals"][0]["summary"] == "committed marker"
        actual = tmp_path / "actual.json"
        actual.write_text(json.dumps(expected))
        main(["compare", "--bundle", str(output), "--actual", str(actual)])
        assert "parity: PASS" in capsys.readouterr().out
        # A stale release with different warnings must fail even with identical signals.
        expected["list_cached_signals"]["warning"] = "wrong warning"
        with pytest.raises(ValueError, match="responses differ"):
            compare_signal_release(output, expected)
        (output / "expected.json").write_text("{}")
        with pytest.raises(ValueError, match="checksum mismatch"):
            compare_signal_release(output, {})


def test_release_requires_single_user_confirmation(tmp_path):
    with pytest.raises(ValueError, match="dedicated cache"):
        prepare_signal_release(tmp_path / "absent", tmp_path / "output", "alice", "alice/repo")
    assert not (tmp_path / "output").exists()
