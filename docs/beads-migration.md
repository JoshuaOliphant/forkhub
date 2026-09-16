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

## Dropped Beads (Not Migrated)

The following beads were intentionally not migrated:

- **forkhub-87l** — Explore web UI wiring. Already shipped to main.
- **forkhub-qqm** — Web UI. Superseded by other work.

## Historical References

Some spec documents and test files contain historical references to bead IDs
(e.g., `forkhub-xyz`). These references are preserved for historical context in:

- `specs/uat-plan.md` — UAT findings originally tracked as beads
- `specs/backfill-ai-decision.md` — Decision framework originally tracked as forkhub-dvi
- `specs/explore-web-wiring-spec.md` — Completed feature spec

These historical references are now closed/completed work and do not require action.
