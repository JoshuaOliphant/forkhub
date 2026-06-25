# ABOUTME: Tests for the GitRepo command/git runner collaborator.
# ABOUTME: Covers the run/git primitives (relocated from BackfillService tests).

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from forkhub.services.git_repo import GitRepo

if TYPE_CHECKING:
    from pathlib import Path


class TestRun:
    """The generic, never-raising command primitive."""

    async def test_runs_command_and_returns_stdout(self, tmp_path: Path):
        """run() executes the command and captures stdout without a shell."""
        result = await GitRepo(tmp_path).run(["echo", "hello"])
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.stdout.strip() == "hello"
        assert result.returncode == 0

    async def test_does_not_expand_shell_metacharacters(self, tmp_path: Path):
        """Args are literal — no shell expansion of $HOME etc."""
        result = await GitRepo(tmp_path).run(["echo", "$HOME"])
        assert result.stdout.strip() == "$HOME"

    async def test_passes_stdin_data(self, tmp_path: Path):
        """stdin_data bytes are forwarded to the process stdin."""
        result = await GitRepo(tmp_path).run(["cat"], stdin_data=b"patch content")
        assert result.stdout == "patch content"

    async def test_times_out_and_returns_minus_one(self, tmp_path: Path):
        """A timeout is reported as returncode -1, not an exception."""
        result = await GitRepo(tmp_path).run(["sleep", "10"], timeout=1)
        assert result.returncode == -1
        assert "timed out" in result.stderr.lower()

    async def test_spawn_failure_returns_minus_one(self, tmp_path: Path):
        """A missing binary is reported as returncode -1 with a spawn message."""
        result = await GitRepo(tmp_path).run(["/nonexistent_binary_xyz_abc_123"])
        assert result.returncode == -1
        assert "nonexistent_binary" in result.stderr


class TestGit:
    """The must-succeed git wrapper that raises on a non-zero exit."""

    async def test_returns_stdout_on_success(self, tmp_path: Path):
        """git() returns the command's stdout when it exits zero."""
        out = await GitRepo(tmp_path).git("--version")
        assert "git version" in out

    async def test_raises_called_process_error_on_failure(self, tmp_path: Path):
        """A non-zero git exit raises CalledProcessError (tmp_path is no repo)."""
        with pytest.raises(subprocess.CalledProcessError):
            await GitRepo(tmp_path).git("rev-parse", "--verify", "HEAD")
