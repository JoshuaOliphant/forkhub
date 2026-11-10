# ABOUTME: Verify minimal cache imports against the existing SQLite MCP reader contract.
# ABOUTME: Check consistent reads, private exclusive output, and rejection of unsafe exports.

from __future__ import annotations

import hashlib
import json
import runpy
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from forkhub.mcp_cache_export import _literal, export_cache
from forkhub.mcp_preview_queries import PreviewQueries
from tests.stubs import make_signal, make_tracked_repo


async def _snapshot(db, path):
    with closing(sqlite3.connect(path)) as connection:
        await db._db.backup(connection)
    return path


@pytest.mark.parametrize("with_evidence", [False, True])
async def test_export_round_trips_contract_and_filters_unrelated_data(db, tmp_path, with_evidence):
    repo = make_tracked_repo(full_name="alice/repo", owner="alice", name="repo", webhook_id=999)
    await db.insert_tracked_repo(repo)
    await db.insert_signal(
        make_signal(
            None,
            repo["id"],
            summary="A 'quoted' change; DROP TABLE signals; — café",
            detail="NUL\x00remains",
            embedding=b"private-vector",
            files_involved=json.dumps(["src/actual.py"]),
            evidence=json.dumps(
                {
                    "source_repository": "alice/fork",
                    "commit_shas": ["b" * 40],
                    "files": ["src/actual.py"],
                    "changes": [
                        {
                            "commit_sha": "b" * 40,
                            "filename": "src/actual.py",
                            "status": "modified",
                            "patch": "@@ -1 +1 @@\n-before\n+after",
                        }
                    ],
                    "verification_state": "verified",
                    "verified_at": "2026-11-10T12:00:00+00:00",
                }
            )
            if with_evidence
            else None,
        )
    )
    for username in ("alice", "bob"):
        await db.save_relationship_snapshot(
            username,
            {
                "focus_github_id": 7,
                "focus_repo": "alice/repo",
                "upstream_repo": "acme/repo",
                "complete": True,
                "pages_scanned": 2,
                "relationships": [
                    {
                        "direction": "upstream",
                        "github_id": 8,
                        "source_repo": "acme/repo",
                        "target_repo": "alice/repo",
                        "is_user_repository": False,
                    },
                    {
                        "direction": "downstream",
                        "github_id": 9,
                        "source_repo": f"{username}/fork",
                        "target_repo": "alice/repo",
                        "is_user_repository": True,
                    },
                ],
            },
        )
    await db.save_relationship_snapshot(
        "alice",
        {
            "focus_github_id": 7,
            "focus_repo": "alice/repo",
            "upstream_repo": None,
            "complete": False,
            "pages_scanned": 1,
            "relationships": [],
        },
    )
    source = await _snapshot(db, tmp_path / "source.db")
    before = hashlib.sha256(source.read_bytes()).digest()
    destination = tmp_path / "private.sql"

    counts = export_cache(source, destination, " ALICE ", confirm_single_user=True)

    assert counts == {
        "tracked_repos": 1,
        "signals": 1,
        "relationship_snapshots": 1,
        "repository_relationships": 2,
    }
    assert destination.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(source.read_bytes()).digest() == before
    sql = destination.read_text()
    assert "BEGIN" not in sql
    assert "COMMIT" not in sql
    assert "private-vector" not in sql
    assert "webhook_id" not in sql
    assert "bob/fork" not in sql
    imported = tmp_path / "imported.db"
    with closing(sqlite3.connect(imported)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(sql)
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert {
            r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")
        } == {"tracked_repos", "signals", "relationship_snapshots", "repository_relationships"}
        assert connection.execute("SELECT username FROM relationship_snapshots").fetchall() == [
            ("alice",)
        ]
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            connection.executescript(sql)
    original_reader = PreviewQueries(source, "alice")
    imported_reader = PreviewQueries(imported, "alice")
    assert (
        imported_reader.list_tracked_repositories() == original_reader.list_tracked_repositories()
    )
    assert imported_reader.get_cached_relationships(
        "ALICE/REPO"
    ) == original_reader.get_cached_relationships("ALICE/REPO")
    signals = imported_reader.list_cached_signals("ALICE/REPO")
    assert signals == original_reader.list_cached_signals("ALICE/REPO")
    evidence = signals["signals"][0]["evidence"]
    if with_evidence:
        assert evidence["source_repository"] == "alice/fork"
        assert evidence["commit_shas"] == ["b" * 40]
        assert evidence["changes"][0]["patch"] == "@@ -1 +1 @@\n-before\n+after"
    else:
        assert evidence is None


async def test_export_sees_committed_wal_rows_without_modifying_source(db, tmp_path):
    await db.insert_tracked_repo(make_tracked_repo(full_name="alice/committed"))
    source = await _snapshot(db, tmp_path / "source.db")
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("UPDATE tracked_repos SET full_name='alice/uncommitted'")
        before = hashlib.sha256(source.read_bytes()).digest()
        export_cache(source, tmp_path / "cache.sql", "alice", confirm_single_user=True)
        assert hashlib.sha256(source.read_bytes()).digest() == before
        assert "alice/committed" in (tmp_path / "cache.sql").read_text()
        assert "alice/uncommitted" not in (tmp_path / "cache.sql").read_text()


@pytest.mark.parametrize("kind", ["existing", "symlink"])
async def test_export_never_overwrites_destination(db, tmp_path, kind):
    source = await _snapshot(db, tmp_path / "source.db")
    retained = tmp_path / "retained.sql"
    retained.write_text("retained")
    destination = retained
    if kind == "symlink":
        destination = tmp_path / "link.sql"
        destination.symlink_to(retained)
    with pytest.raises(FileExistsError):
        export_cache(source, destination, "alice", confirm_single_user=True)
    assert retained.read_text() == "retained"


@pytest.mark.parametrize(
    "username,confirm,message", [("alice", False, "dedicated"), (" ", True, "username")]
)
def test_export_rejects_missing_operator_confirmation(tmp_path, username, confirm, message):
    destination = tmp_path / "cache.sql"
    with pytest.raises(ValueError, match=message):
        export_cache(tmp_path / "missing.db", destination, username, confirm_single_user=confirm)
    assert not destination.exists()


def test_export_missing_source_creates_nothing(tmp_path):
    source = tmp_path / "missing.db"
    destination = tmp_path / "cache.sql"
    with pytest.raises(FileNotFoundError):
        export_cache(source, destination, "alice", confirm_single_user=True)
    assert not source.exists()
    assert not destination.exists()


def test_export_rejects_old_or_invalid_schema_before_creating_output(tmp_path):
    source = tmp_path / "old.db"
    source.touch()
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        export_cache(source, tmp_path / "cache.sql", "alice", confirm_single_user=True)
    assert not (tmp_path / "cache.sql").exists()


@pytest.mark.parametrize("value", [None, "ordinary ' unicode λ", "text\x00after", 3, -4, 1.25])
def test_sql_literals_round_trip_without_executing_data(value):
    with closing(sqlite3.connect(":memory:")) as connection:
        assert connection.execute("SELECT " + _literal(value)).fetchone() == (value,)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), b"blob", 2**53, -(2**53)])
def test_unsupported_sql_values_fail_before_import(value):
    with pytest.raises(ValueError):
        _literal(value)


@pytest.mark.parametrize("statement_bytes", [99_999, 100_000, 100_001])
async def test_export_enforces_d1_statement_byte_boundary(db, tmp_path, statement_bytes):
    repo = make_tracked_repo()
    await db.insert_tracked_repo(repo)
    await db.insert_signal(make_signal(None, repo["id"], detail=""))
    source = await _snapshot(db, tmp_path / "source.db")
    baseline = tmp_path / "baseline.sql"
    export_cache(source, baseline, "alice", confirm_single_user=True)
    statement = next(
        line
        for line in baseline.read_text().splitlines(keepends=True)
        if line.startswith("INSERT INTO signals")
    )
    payload = "x" * (statement_bytes - len(statement.encode("utf-8")))
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("UPDATE signals SET detail = ?", (payload,))
        writer.commit()
    destination = tmp_path / "cache.sql"

    if statement_bytes > 100_000:
        with pytest.raises(ValueError, match="100000 bytes for table signals"):
            export_cache(source, destination, "alice", confirm_single_user=True)
        assert not destination.exists()
    else:
        export_cache(source, destination, "alice", confirm_single_user=True)
        actual = next(
            line
            for line in destination.read_text().splitlines(keepends=True)
            if line.startswith("INSERT INTO signals")
        )
        assert len(actual.encode("utf-8")) == statement_bytes
        with closing(sqlite3.connect(":memory:")) as imported:
            imported.executescript(destination.read_text())
            assert imported.execute("SELECT detail FROM signals").fetchone() == (payload,)


@pytest.mark.parametrize("character", ["é", "'", "\x00"])
async def test_export_checks_encoded_and_escaped_statement_size(db, tmp_path, character):
    repo = make_tracked_repo()
    await db.insert_tracked_repo(repo)
    payload = character * 50_000
    await db.insert_signal(make_signal(None, repo["id"], detail=payload))
    source = await _snapshot(db, tmp_path / "source.db")
    destination = tmp_path / "cache.sql"

    with pytest.raises(ValueError) as failure:
        export_cache(source, destination, "alice", confirm_single_user=True)

    assert str(failure.value) == "D1 SQL statement exceeds 100000 bytes for table signals"
    assert not destination.exists()


async def test_export_command_reports_counts_only_and_requires_confirmation(db, tmp_path, capsys):
    source = await _snapshot(db, tmp_path / "source.db")
    command = runpy.run_path(str(Path(__file__).parents[1] / "examples/export_mcp_cache.py"))[
        "main"
    ]
    arguments = [
        "--source",
        str(source),
        "--destination",
        str(tmp_path / "cache.sql"),
        "--username",
        "alice",
    ]
    with pytest.raises(SystemExit) as missing:
        command(arguments)
    assert missing.value.code == 2
    assert "--confirm-single-user" in capsys.readouterr().err
    command([*arguments, "--confirm-single-user"])
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "tracked_repos": 0,
        "signals": 0,
        "relationship_snapshots": 0,
        "repository_relationships": 0,
    }
