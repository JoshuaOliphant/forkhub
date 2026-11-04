# Relationship snapshot retention

ForkHub maintains two separate concepts for cached fork relationships:

- **Saved snapshot:** the most recent complete graph, when one is available.
- **Latest attempt:** whether the most recent discovery finished, when it ran,
  and how many pages were inspected.

An incomplete GitHub discovery caused by pagination limits, inaccessible
parents, or rate limits must not erase complete evidence already collected.

## Storage behavior

- First partial scan: store its partial graph as explicitly incomplete.
- Without a complete snapshot: each partial scan replaces the preceding partial
  graph, even when it contains fewer relationships.
- Partial scan after a complete scan: retain existing graph, its snapshot
  timestamp, repository names and edges; update attempt coverage/timestamp only.
  Renames observed only in a partial scan wait until a complete scan succeeds.
- Further partial scans: keep the complete graph; update last-attempt status.
- Successful complete scan: atomically replace the graph and clear stale
  attempt status.
- Different users and stable GitHub repository IDs remain separate.
- Existing SQLite databases receive additive nullable metadata columns.

The data may still be outdated: retaining evidence is **not** claiming it is
current. The MCP preview returns `last_attempt_at`,
`last_attempt_complete`, `last_attempt_pages_scanned`,
`last_complete_at`, and `preserved_complete_snapshot`. If a complete
snapshot survives an unsuccessful refresh, the warning explicitly says the
relationships may be stale. The primary cached snapshot API continues
returning the stored graph with its original `complete` value.

## Remaining work

- Persist detailed error and coverage reasons for partial attempts.
- Resolve repository rename/alias lookup by stable GitHub ID.
- Add bounded pagination for large relationship graphs.
- Add proper tenant ownership and authorization for hosted MCP.
- Propagate freshness metadata through the final intelligence APIs, not
  only the preview.
