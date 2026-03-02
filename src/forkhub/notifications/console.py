# ABOUTME: Console notification backend using Rich for formatted terminal output.
# ABOUTME: Default notification backend — renders digests as beautiful terminal output.

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console

from forkhub.cli.formatting import render_digest
from forkhub.models import DeliveryResult, Digest


class ConsoleBackend:
    """Notification backend that renders digests to the terminal using Rich.

    Implements the NotificationBackend protocol defined in interfaces.py.
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    async def deliver(self, digest: Digest) -> DeliveryResult:
        """Render the digest to the console using Rich formatting."""
        render_digest(self._console, digest)

        return DeliveryResult(
            backend_name=self.backend_name(),
            success=True,
            delivered_at=datetime.now(tz=UTC),
        )

    def backend_name(self) -> str:
        """Return the name of this backend."""
        return "console"
