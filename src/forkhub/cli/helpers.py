# ABOUTME: Common async runner and service initialization for CLI commands.
# ABOUTME: Provides async_command decorator and get_services() factory.

from __future__ import annotations

import asyncio
from functools import wraps
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forkhub.config import ForkHubSettings
    from forkhub.database import Database
    from forkhub.providers.github import GitHubProvider


def async_command(f):
    """Decorator to run an async function as a Typer command."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


async def get_services(
    settings: ForkHubSettings | None = None,
) -> tuple[ForkHubSettings, Database, GitHubProvider]:
    """Initialize and return common services tuple.

    Returns (settings, db, provider) with the database already connected.
    Caller is responsible for closing the database when done.
    """
    from forkhub.config import get_db_path, load_settings
    from forkhub.database import Database
    from forkhub.providers.github import GitHubProvider

    if settings is None:
        settings = load_settings()
    db = Database(get_db_path(settings))
    await db.connect()
    provider = GitHubProvider(settings.github.token)
    return settings, db, provider
