-- ABOUTME: Define only the cache columns exposed by ForkHub's read-only MCP tools.
-- ABOUTME: Require a fresh database and preserve relationship insertion order explicitly.
CREATE TABLE tracked_repos (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    tracking_mode TEXT NOT NULL,
    last_synced_at TEXT,
    sync_status TEXT NOT NULL,
    excluded INTEGER NOT NULL
);
CREATE INDEX tracked_repos_name ON tracked_repos(full_name COLLATE NOCASE);
CREATE TABLE signals (
    id TEXT PRIMARY KEY,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id),
    summary TEXT NOT NULL,
    detail TEXT,
    category TEXT NOT NULL,
    significance INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    files_involved TEXT NOT NULL
);
CREATE INDEX signals_repository ON signals(tracked_repo_id, significance DESC, created_at DESC, id);
CREATE TABLE relationship_snapshots (
    username TEXT NOT NULL,
    focus_github_id INTEGER NOT NULL,
    focus_repo TEXT NOT NULL,
    upstream_repo TEXT,
    complete INTEGER NOT NULL,
    pages_scanned INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    last_attempt_at TEXT,
    last_attempt_complete INTEGER,
    last_attempt_pages_scanned INTEGER,
    last_complete_at TEXT,
    PRIMARY KEY (username, focus_github_id)
);
CREATE INDEX relationship_snapshots_name
    ON relationship_snapshots(username, focus_repo COLLATE NOCASE);
CREATE TABLE repository_relationships (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    focus_github_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    source_github_id INTEGER NOT NULL,
    source_repo TEXT NOT NULL,
    target_repo TEXT NOT NULL,
    is_user_repository INTEGER NOT NULL,
    FOREIGN KEY (username, focus_github_id)
        REFERENCES relationship_snapshots(username, focus_github_id)
);
CREATE INDEX repository_relationships_focus ON repository_relationships(username, focus_github_id);
