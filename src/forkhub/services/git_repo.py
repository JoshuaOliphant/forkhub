# ABOUTME: Async command/git runner bound to one working-copy directory.
# ABOUTME: Centralizes subprocess + git plumbing so services stay domain-focused.

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)


class GitRepo:
    """An async command/git runner bound to a working-copy directory.

    Owns the "how to run a command/git in this repo" mechanics so callers can
    express git operations as named methods instead of inline subprocess
    plumbing. Every command runs with the repo directory as its cwd.

    Two primitives back everything else:

    - :meth:`run` — generic, never raises; returns a ``CompletedProcess`` with a
      synthesized ``returncode = -1`` on spawn failure or timeout. Callers that
      must distinguish "command ran and said no" from "command couldn't run at
      all" inspect ``returncode < 0``. Also used for non-git commands (tests).
    - :meth:`git` — the must-succeed wrapper that raises
      ``subprocess.CalledProcessError`` on a non-zero exit.

    The remaining methods name a single git operation each, so the git
    knowledge (flags, ordering, which calls may fail) lives here rather than
    sprinkled through the domain layer.
    """

    def __init__(self, repo_path: Path) -> None:
        self._repo_path = repo_path

    # --- primitives -------------------------------------------------------

    async def run(
        self,
        args: Sequence[str],
        *,
        stdin_data: bytes | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess:
        """Run a command as an argument list via ``subprocess_exec`` (no shell).

        Returns a ``CompletedProcess`` with synthesized ``returncode = -1`` on
        spawn failure (missing binary, permission denied) or timeout.
        """
        args = list(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._repo_path),
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.error("Failed to spawn %s: %s", args[0] if args else "<empty>", exc)
            return subprocess.CompletedProcess(
                args=args,
                returncode=-1,
                stdout="",
                stderr=f"failed to spawn {args[0] if args else '<empty>'}: {exc}",
            )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Command timed out after %ds: %s", timeout, " ".join(str(a) for a in args))
            return subprocess.CompletedProcess(
                args=args,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else "",
            stderr=stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "",
        )

    async def git(self, *args: str) -> str:
        """Run a git command and return stdout; raise on a non-zero exit.

        Raises ``subprocess.CalledProcessError`` if the command exits non-zero.
        """
        result = await self.run(["git", *args])
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                ["git", *args],
                output=result.stdout,
                stderr=result.stderr,
            )
        return result.stdout or ""

    # --- introspection (callers inspect returncode) ----------------------

    async def head_branch(self) -> subprocess.CompletedProcess:
        """``git rev-parse --abbrev-ref HEAD`` — the current branch name."""
        return await self.run(["git", "rev-parse", "--abbrev-ref", "HEAD"])

    async def verify_branch(self, name: str) -> subprocess.CompletedProcess:
        """``git rev-parse --verify <name>`` — returncode 0=exists, 1=missing.

        A spawn failure or timeout yields ``returncode = -1`` ("unknown").
        Use :meth:`branch_exists` when the unknown case can be treated as absent.
        """
        return await self.run(["git", "rev-parse", "--verify", name])

    async def branch_exists(self, name: str) -> bool:
        """True only when the branch verifiably exists (rev-parse exit 0)."""
        return (await self.verify_branch(name)).returncode == 0

    # --- mutating operations that may legitimately fail ------------------

    async def apply_3way(self, patch: bytes) -> subprocess.CompletedProcess:
        """``git apply --3way`` reading the patch from stdin (never raises)."""
        return await self.run(["git", "apply", "--3way", "-"], stdin_data=patch)

    async def reset_hard(self) -> subprocess.CompletedProcess:
        """``git reset --hard`` to discard a partially applied / conflicted tree."""
        return await self.run(["git", "reset", "--hard"])

    # --- must-succeed operations (raise on failure) ----------------------

    async def create_branch(self, name: str) -> None:
        """``git checkout -b <name>`` — create and switch to a new branch."""
        await self.git("checkout", "-b", name)

    async def checkout(self, ref: str) -> None:
        """``git checkout <ref>`` (use ``-`` for the previous branch)."""
        await self.git("checkout", ref)

    async def stage(self, paths: Sequence[str]) -> None:
        """``git add -- <paths>`` — stage only the named paths, never ``-A``."""
        await self.git("add", "--", *paths)

    async def commit(self, message: str) -> None:
        """``git commit -m <message>``."""
        await self.git("commit", "-m", message)

    async def delete_branch(self, name: str) -> None:
        """``git branch -D <name>`` — force-delete a branch."""
        await self.git("branch", "-D", name)
