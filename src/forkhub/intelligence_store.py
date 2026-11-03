# ABOUTME: Storage boundary for persistent fork intelligence.
# ABOUTME: Keeps domain services independent from SQLite and future storage backends.

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from forkhub.services.relationships import RelationshipSnapshot

if TYPE_CHECKING:
    from forkhub.database import Database


@runtime_checkable
class IntelligenceStore(Protocol):
    """Persist and retrieve relationship snapshots scoped to one user."""

    async def save_relationship_snapshot(
        self, user_id: str, snapshot: RelationshipSnapshot
    ) -> None: ...

    async def get_relationship_snapshot(
        self, user_id: str, repository: str
    ) -> RelationshipSnapshot | None: ...


class SQLiteIntelligenceStore:
    """SQLite-backed intelligence storage using the existing Database lifecycle."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_relationship_snapshot(
        self, user_id: str, snapshot: RelationshipSnapshot
    ) -> None:
        await self._db.save_relationship_snapshot(user_id, snapshot.model_dump())

    async def get_relationship_snapshot(
        self, user_id: str, repository: str
    ) -> RelationshipSnapshot | None:
        row = await self._db.get_relationship_snapshot(user_id, repository)
        if row is None:
            return None
        return RelationshipSnapshot.model_validate(row)
