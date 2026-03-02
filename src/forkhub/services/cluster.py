# ABOUTME: Cluster detection service using vector similarity.
# ABOUTME: Groups similar signals across forks using pairwise cosine distance in Python.

from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import EmbeddingProvider

from forkhub.models import Cluster


class ClusterService:
    """Groups similar signals from independent forks into clusters.

    Uses an EmbeddingProvider to generate vector embeddings for signal summaries,
    then compares them pairwise using cosine distance. Signals from different forks
    with high similarity and overlapping file paths form clusters.
    """

    def __init__(self, db: Database, embedding_provider: EmbeddingProvider) -> None:
        self._db = db
        self._embedding_provider = embedding_provider

    async def update_clusters(self, repo_id: str) -> list[Cluster]:
        """Embed unembedded signals and discover or grow clusters.

        1. Fetch signals missing embeddings
        2. Generate and store embeddings
        3. Compare signals pairwise to find cluster candidates
        4. Create or update clusters in the database
        """
        # Step 1: Get all signals for this repo
        all_signals = await self._db.list_signals(repo_id)
        if not all_signals:
            return []

        # Step 2: Identify unembedded signals and generate embeddings
        unembedded = [s for s in all_signals if s["embedding"] is None]
        if unembedded:
            texts = [s["summary"] for s in unembedded]
            embeddings = await self._embedding_provider.embed(texts)
            for signal, embedding in zip(unembedded, embeddings, strict=True):
                embedding_bytes = json.dumps(embedding).encode("utf-8")
                await self._db._db.execute(
                    "UPDATE signals SET embedding = ? WHERE id = ?",
                    (embedding_bytes, signal["id"]),
                )
                signal["embedding"] = embedding_bytes
            await self._db._db.commit()

        # Refresh all signals with their embeddings
        all_signals = await self._db.list_signals(repo_id)

        # Parse embeddings from stored bytes
        signals_with_embeddings = []
        for s in all_signals:
            if s["embedding"] is not None:
                embedding = json.loads(s["embedding"])
                signals_with_embeddings.append((s, embedding))

        if len(signals_with_embeddings) < 2:
            return []

        # Step 3: Load existing clusters and their members
        existing_clusters = await self._db.list_clusters(repo_id)
        cluster_members: dict[str, set[str]] = {}  # cluster_id -> set of signal_ids
        cluster_fork_ids: dict[str, set[str]] = {}  # cluster_id -> set of fork_ids

        for cluster_row in existing_clusters:
            cid = cluster_row["id"]
            cursor = await self._db._db.execute(
                "SELECT signal_id, fork_id FROM cluster_members WHERE cluster_id = ?",
                (cid,),
            )
            members = await cursor.fetchall()
            cluster_members[cid] = {m["signal_id"] for m in members}
            cluster_fork_ids[cid] = {m["fork_id"] for m in members}

        # Track which signals are already in clusters
        assigned_signals = set()
        for members in cluster_members.values():
            assigned_signals.update(members)

        # Step 4: Find pairs that should cluster (among newly embedded signals)
        newly_embedded_ids = {s["id"] for s in unembedded} if unembedded else set()
        new_clusters: list[Cluster] = []
        updated_cluster_ids: set[str] = set()

        # For each newly embedded signal, check against all other signals
        for _i, (sig_i, emb_i) in enumerate(signals_with_embeddings):
            if sig_i["id"] not in newly_embedded_ids:
                continue

            # Try to add to an existing cluster first
            added_to_cluster = False
            for cid, member_ids in cluster_members.items():
                # Check if this signal is similar to any member of the cluster
                for _j, (sig_j, emb_j) in enumerate(signals_with_embeddings):
                    if sig_j["id"] not in member_ids:
                        continue
                    dist = self._cosine_distance(emb_i, emb_j)
                    should_add = (
                        self._should_cluster(sig_i, sig_j, dist)
                        and sig_i["id"] not in cluster_members[cid]
                    )
                    if should_add:
                        await self._db.add_cluster_member({
                            "cluster_id": cid,
                            "signal_id": sig_i["id"],
                            "fork_id": sig_i["fork_id"],
                        })
                        cluster_members[cid].add(sig_i["id"])
                        cluster_fork_ids[cid].add(sig_i["fork_id"])
                        assigned_signals.add(sig_i["id"])
                        # Update fork_count on the cluster
                        new_fork_count = len(cluster_fork_ids[cid])
                        now_iso = datetime.now(UTC).isoformat()
                        await self._db._db.execute(
                            "UPDATE clusters SET fork_count = ?, updated_at = ? WHERE id = ?",
                            (new_fork_count, now_iso, cid),
                        )
                        await self._db._db.commit()
                        updated_cluster_ids.add(cid)
                        added_to_cluster = True
                        break
                if added_to_cluster:
                    break

            if added_to_cluster:
                continue

            # Try to form a new cluster with another unassigned signal
            for _j, (sig_j, emb_j) in enumerate(signals_with_embeddings):
                if sig_j["id"] == sig_i["id"]:
                    continue
                if sig_j["id"] in assigned_signals and sig_i["id"] in assigned_signals:
                    continue

                dist = self._cosine_distance(emb_i, emb_j)
                if self._should_cluster(sig_i, sig_j, dist):
                    # Create new cluster
                    signals_in_cluster = [sig_i, sig_j]
                    label = self._generate_cluster_label(signals_in_cluster)
                    cluster_id = str(uuid4())
                    fork_ids = {sig_i["fork_id"], sig_j["fork_id"]}
                    now_iso = datetime.now(UTC).isoformat()

                    # Get common files for the pattern
                    files_i = set(json.loads(sig_i["files_involved"]))
                    files_j = set(json.loads(sig_j["files_involved"]))
                    common_files = list(files_i & files_j)

                    cluster_dict = {
                        "id": cluster_id,
                        "tracked_repo_id": repo_id,
                        "label": label,
                        "description": f"Cluster of {len(fork_ids)} forks with similar changes",
                        "files_pattern": json.dumps(common_files),
                        "fork_count": len(fork_ids),
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    }
                    await self._db.insert_cluster(cluster_dict)

                    for sig in signals_in_cluster:
                        await self._db.add_cluster_member({
                            "cluster_id": cluster_id,
                            "signal_id": sig["id"],
                            "fork_id": sig["fork_id"],
                        })
                        assigned_signals.add(sig["id"])

                    cluster_members[cluster_id] = {s["id"] for s in signals_in_cluster}
                    cluster_fork_ids[cluster_id] = fork_ids

                    cluster = Cluster(
                        id=cluster_id,
                        tracked_repo_id=repo_id,
                        label=label,
                        description=cluster_dict["description"],
                        files_pattern=common_files,
                        fork_count=len(fork_ids),
                    )
                    new_clusters.append(cluster)
                    break

        # Build return list: new clusters + updated existing clusters
        result = list(new_clusters)
        for cid in updated_cluster_ids:
            # Fetch the updated cluster from DB
            cursor = await self._db._db.execute("SELECT * FROM clusters WHERE id = ?", (cid,))
            row = await cursor.fetchone()
            if row:
                cluster = Cluster(
                    id=row["id"],
                    tracked_repo_id=row["tracked_repo_id"],
                    label=row["label"],
                    description=row["description"],
                    files_pattern=json.loads(row["files_pattern"])
                    if isinstance(row["files_pattern"], str)
                    else row["files_pattern"],
                    fork_count=row["fork_count"],
                )
                result.append(cluster)

        return result

    async def get_clusters(self, repo_id: str, min_size: int = 2) -> list[Cluster]:
        """Retrieve existing clusters filtered by minimum fork count."""
        rows = await self._db.list_clusters(repo_id)
        clusters = []
        for row in rows:
            if row["fork_count"] >= min_size:
                clusters.append(
                    Cluster(
                        id=row["id"],
                        tracked_repo_id=row["tracked_repo_id"],
                        label=row["label"],
                        description=row["description"],
                        files_pattern=json.loads(row["files_pattern"])
                        if isinstance(row["files_pattern"], str)
                        else row["files_pattern"],
                        fork_count=row["fork_count"],
                    )
                )
        return clusters

    def _should_cluster(
        self,
        signal_a: dict,
        signal_b: dict,
        distance: float,
        threshold: float = 0.3,
    ) -> bool:
        """Determine whether two signals should be grouped into a cluster.

        Requirements:
        - Signals must be from different forks
        - Cosine distance must be below the threshold
        - Signals must have overlapping files (same file or same directory)
        """
        # Must be from different forks
        if signal_a["fork_id"] == signal_b["fork_id"]:
            return False

        # Distance must be below threshold
        if distance >= threshold:
            return False

        # Must have overlapping files or directories
        files_a = (
            json.loads(signal_a["files_involved"])
            if isinstance(signal_a["files_involved"], str)
            else signal_a["files_involved"]
        )
        files_b = (
            json.loads(signal_b["files_involved"])
            if isinstance(signal_b["files_involved"], str)
            else signal_b["files_involved"]
        )

        # Check for exact file overlap
        if set(files_a) & set(files_b):
            return True

        # Check for directory overlap (same parent directory)
        dirs_a = {os.path.dirname(f) for f in files_a if f}
        dirs_b = {os.path.dirname(f) for f in files_b if f}
        return bool(dirs_a & dirs_b)

    def _generate_cluster_label(self, signals: list[dict]) -> str:
        """Derive a human-readable label from common categories and files.

        Combines the most common category with the most common file or directory
        mentioned across the signals.
        """
        # Count categories
        categories = Counter()
        all_files: list[str] = []
        for sig in signals:
            categories[sig["category"]] += 1
            files = (
                json.loads(sig["files_involved"])
                if isinstance(sig["files_involved"], str)
                else sig["files_involved"]
            )
            all_files.extend(files)

        # Most common category
        top_category = categories.most_common(1)[0][0] if categories else "changes"

        # Find common files across signals
        file_counts = Counter(all_files)
        if file_counts:
            top_file = file_counts.most_common(1)[0][0]
            # Extract just the filename without extension for readability
            basename = os.path.basename(top_file)
            name_without_ext = os.path.splitext(basename)[0] if basename else ""
            if name_without_ext:
                return f"{top_category} in {name_without_ext}"

        return f"{top_category} changes"

    def _cosine_distance(self, a: list[float], b: list[float]) -> float:
        """Compute cosine distance (1 - cosine similarity) between two vectors.

        Returns 1.0 if either vector is zero-length (maximally dissimilar).
        """
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))

        if mag_a == 0.0 or mag_b == 0.0:
            return 1.0

        similarity = dot / (mag_a * mag_b)
        # Clamp to [-1, 1] to handle floating point errors
        similarity = max(-1.0, min(1.0, similarity))
        return 1.0 - similarity
