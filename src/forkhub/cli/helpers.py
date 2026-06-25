# ABOUTME: Common async runner and service initialization for CLI commands.
# ABOUTME: Provides async_command decorator and get_services() factory.

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from forkhub.config import ForkHubSettings
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider
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


@asynccontextmanager
async def open_db(db: Database | None = None) -> AsyncIterator[Database]:
    """Yield a connected database for a CLI ``_impl`` that needs no provider.

    Tests inject ``db`` (yielded as-is, left open for the caller). When absent,
    one is built via :func:`get_services` and closed on exit. This replaces the
    ``owns_db`` boilerplate for read-only/db-only commands.
    """
    owns_db = db is None
    if db is None:
        _settings, db, _provider = await get_services()
    try:
        yield db
    finally:
        if owns_db:
            await db.close()


@asynccontextmanager
async def open_services(
    db: Database | None = None,
    provider: GitProvider | None = None,
) -> AsyncIterator[tuple[ForkHubSettings | None, Database, GitProvider]]:
    """Yield ``(settings, db, provider)`` for a CLI ``_impl`` needing a provider.

    Tests inject ``db`` and ``provider`` (yielded as-is, left open) and receive
    ``settings = None`` — matching the old hand-written boilerplate, where
    settings were only loaded on the auto-build path. Callers that need
    settings on the injected path fall back to :func:`load_settings` themselves.

    Lifecycle rule: own and close **only a database this builds**. When ``db``
    is injected but ``provider`` is not, a provider is built on its own from
    settings — without constructing a throwaway database — so the injected
    ``db`` is never disturbed and nothing leaks.
    """
    settings: ForkHubSettings | None = None
    owns_db = db is None
    if db is None:
        settings, db, built_provider = await get_services()
        if provider is None:
            provider = built_provider
    elif provider is None:
        from forkhub.config import load_settings
        from forkhub.providers.github import GitHubProvider

        provider = GitHubProvider(load_settings().github.token)
    try:
        yield settings, db, provider
    finally:
        if owns_db:
            await db.close()
