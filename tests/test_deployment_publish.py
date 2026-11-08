# ABOUTME: Exercise the deployment unit's actual SQLite snapshot publication commands.
# ABOUTME: Verify WAL consistency, atomic reader replacement, and preservation after failures.

from __future__ import annotations

import hashlib
import shlex
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest


def _publish(state_root: Path) -> None:
    unit = Path(__file__).resolve().parents[1] / "deploy/systemd/forkhub-publish.service"
    for line in unit.read_text().splitlines():
        if line.startswith(("ExecStartPre=", "ExecStart=")):
            arguments = shlex.split(line.split("=", 1)[1])
            executable = shutil.which(Path(arguments[0]).name)
            assert executable is not None, f"Required deployment executable: {arguments[0]}"
            arguments[0] = executable
            arguments = [arg.replace("/var/lib/forkhub", str(state_root)) for arg in arguments]
            result = subprocess.run(arguments, check=True, capture_output=True, text=True)
            assert result.stderr == ""


def test_publication_preserves_committed_wal_snapshot_and_replaces_readers(tmp_path):
    source = tmp_path / "cache/forkhub.db"
    target = tmp_path / "published/mcp.db"
    source.parent.mkdir()
    target.parent.mkdir()
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("CREATE TABLE cache_values (value TEXT)")
        writer.execute("INSERT INTO cache_values VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO cache_values VALUES ('uncommitted')")
        source_before = hashlib.sha256(source.read_bytes()).digest()

        _publish(tmp_path)

        assert hashlib.sha256(source.read_bytes()).digest() == source_before
        assert target.stat().st_mode & 0o777 == 0o640
        assert not target.with_suffix(".db.next").exists()
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as old_reader:
            old_reader.execute("BEGIN")
            assert old_reader.execute("SELECT * FROM cache_values").fetchall() == [("committed",)]
            assert old_reader.execute("PRAGMA journal_mode").fetchone() == ("delete",)
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                old_reader.execute("INSERT INTO cache_values VALUES ('forbidden')")

            writer.rollback()
            writer.execute("INSERT INTO cache_values VALUES ('updated')")
            writer.commit()
            _publish(tmp_path)

            assert old_reader.execute("SELECT * FROM cache_values").fetchall() == [("committed",)]
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as new_reader:
                assert new_reader.execute("SELECT * FROM cache_values").fetchall() == [
                    ("committed",),
                    ("updated",),
                ]
                assert new_reader.execute("PRAGMA quick_check").fetchone() == ("ok",)


@pytest.mark.parametrize("source_state", ["missing", "corrupt"])
def test_failed_publication_preserves_previous_snapshot(tmp_path, source_state):
    source = tmp_path / "cache/forkhub.db"
    target = tmp_path / "published/mcp.db"
    source.parent.mkdir()
    target.parent.mkdir()
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("CREATE TABLE cache_values (value TEXT)")
        writer.execute("INSERT INTO cache_values VALUES ('retained')")
        writer.commit()
    _publish(tmp_path)
    before = hashlib.sha256(target.read_bytes()).digest()
    if source_state == "missing":
        source.unlink()
    else:
        source.write_bytes(b"not a SQLite database")

    with pytest.raises(subprocess.CalledProcessError) as failure:
        _publish(tmp_path)

    assert failure.value.returncode != 0
    if source_state == "corrupt":
        assert "not a database" in failure.value.stderr
    assert hashlib.sha256(target.read_bytes()).digest() == before
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as reader:
        assert reader.execute("SELECT * FROM cache_values").fetchall() == [("retained",)]
