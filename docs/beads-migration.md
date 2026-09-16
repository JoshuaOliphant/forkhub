# Beads to GitHub Issues Migration

This project previously used [beads](https://github.com/gastownhall/beads) for local
issue tracking. As of September 2026, all active issues have been migrated to GitHub
Issues for better visibility and standard tooling.

## Migration Map

The following beads were migrated to GitHub Issues:

| Bead ID | GitHub Issue | Title |
|---------|--------------|-------|
| forkhub-uox | [#28](https://github.com/JoshuaOliphant/forkhub/issues/28) | CLI configures no logging; library warnings rely on logging.lastResort |
| forkhub-3pj | [#29](https://github.com/JoshuaOliphant/forkhub/issues/29) | Document: forkhub sync's agent analysis cannot run inside a Claude Code session |
| forkhub-qsq | [#30](https://github.com/JoshuaOliphant/forkhub/issues/30) | digest-writer AgentDefinition is built but never registered |
| forkhub-73l | [#31](https://github.com/JoshuaOliphant/forkhub/issues/31) | feat: optional event stream emission as JSONL topics |
| forkhub-7qk | [#32](https://github.com/JoshuaOliphant/forkhub/issues/32) | Add analysis CLI primitives for external agents (BYO-LLM) |
| forkhub-4id | [#33](https://github.com/JoshuaOliphant/forkhub/issues/33) | Webhook ingestion (GitHub webhook listener) |
| forkhub-ah6 | [#34](https://github.com/JoshuaOliphant/forkhub/issues/34) | Email notification backend (SMTP) |
| forkhub-7k1 | [#35](https://github.com/JoshuaOliphant/forkhub/issues/35) | True per-commit diff scoping: capture commit SHAs on signals at analysis time |
| forkhub-c4i | [#36](https://github.com/JoshuaOliphant/forkhub/issues/36) | Discord notification backend (webhook) |
| forkhub-ime | [#37](https://github.com/JoshuaOliphant/forkhub/issues/37) | Telegram notification backend |
| forkhub-jcr | [#38](https://github.com/JoshuaOliphant/forkhub/issues/38) | Generic webhook notification backend |
| forkhub-l2u | [#39](https://github.com/JoshuaOliphant/forkhub/issues/39) | Voyage AI embedding provider |
| forkhub-z98 | [#40](https://github.com/JoshuaOliphant/forkhub/issues/40) | OpenAI embedding provider (ada-002) |
| forkhub-00a | [#41](https://github.com/JoshuaOliphant/forkhub/issues/41) | Fork annotations |
| forkhub-bgb | [#42](https://github.com/JoshuaOliphant/forkhub/issues/42) | Fork-of-fork tracking (depth > 1) |
| forkhub-ddb | [#43](https://github.com/JoshuaOliphant/forkhub/issues/43) | Multi-platform support (GitLab, Gitea/Forgejo) |
| forkhub-m7y | [#44](https://github.com/JoshuaOliphant/forkhub/issues/44) | GitHub App (OAuth-based setup) |

## Shipped / Completed (Not Migrated)

The following beads represent work that shipped or was completed before migration:

| Bead ID | Status | Description |
|---------|--------|-------------|
| forkhub-87l | Shipped | Explore web UI wiring — now on main |
| forkhub-qqm | Superseded | Web UI — superseded by other work |
| forkhub-14u | Done | Backfill deterministic path epic |
| forkhub-dvi | Closed | AI layer go/no-go decision — NO-GO accepted |
| forkhub-hgm | Done | Analyzer integration |
| forkhub-0tf | Fixed | New-fork compare-on-first-discovery |
| forkhub-99c | Done | last_pushed_at fallback change detection |
| forkhub-lgh | Done | baseline_attempts cap to bound API calls |

## UAT Findings (Fixed)

The following beads were filed during UAT and subsequently fixed:

| Bead ID | Status | Description |
|---------|--------|-------------|
| forkhub-p18 | Fixed | GitHubProvider lacked get_head_sha |
| forkhub-9ey | Fixed | Vitality gate starved compare on dormant-upstream constellations |
| forkhub-cml | Fixed | ProviderError hierarchy for deleted-fork 404s |
| forkhub-flk | Fixed | store_signal schema validation (files_involved as list) |
| forkhub-sqw | Fixed | Empty GITHUB_TOKEN sent malformed header |
| forkhub-9mv | Fixed | dotenv only loaded from cwd |
| forkhub-zaa | Fixed | Unbounded baseline retry on persistent SHA-fetch failure |
| forkhub-dom | Fixed | Digest showed repo UUID instead of full_name |
| forkhub-r1d | Done | Observability call-site wiring |
| forkhub-m1m | Retracted | False finding (harness error reading $? after pipe) |

## Historical References

Some spec documents and test files contain historical references to bead IDs
(e.g., `forkhub-xyz`). These references are preserved for historical context in:

- `specs/uat-plan.md` — UAT findings originally tracked as beads
- `specs/backfill-ai-decision.md` — Decision framework (forkhub-dvi)
- `specs/backfill-deterministic-plan.md` — Epic (forkhub-14u)
- `specs/explore-web-wiring-spec.md` — Shipped feature (forkhub-87l)
- `tests/test_sync.py` — Test descriptions reference fixed beads
- `tests/test_backfill.py` — Test descriptions reference fixed beads
- `src/forkhub/services/sync.py` — Code comment references forkhub-lgh
- `src/forkhub/services/backfill.py` — Code comment references forkhub-7k1

These historical references document the origin of specific fixes and features.
