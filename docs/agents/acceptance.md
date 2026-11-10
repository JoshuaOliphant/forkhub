# Acceptance-test cache

Cache refreshed: 2026-11-10T16:22:28Z

This committed bulk cache retains mappings for open and closed issues. Add new
issue rows without deleting earlier rows. When a later issue replaces a criterion,
replace its Test cell with `superseded by #N`. Publish the matching table on its
issue with marker `<!-- forkhub-acceptance -->`; refresh this timestamp whenever
that table changes. The verification command reads remote issue comments in one
paginated request and warns if a marked table was edited after this cache.

The identifiers below normalize the prose requirements of #35; they do not claim
that the source issue originally used numbered acceptance criteria.

| Issue | AC | Test |
|---|---|---|
| #35 | AC-1 | tests/test_agent_tools.py::test_store_signal_captures_provenance_independently[True] |
| #35 | AC-1 | tests/test_signal_evidence.py::test_capture_verifies_only_complete_relevant_commit_evidence[verified-verified] |
| #35 | AC-2 | tests/test_database.py::test_signal_evidence_migration_preserves_legacy_rows |
| #35 | AC-2 | tests/test_mcp_cache_export.py::test_export_round_trips_contract_and_filters_unrelated_data[True] |
| #35 | AC-2 | tests/test_mcp_cache_export.py::test_export_round_trips_contract_and_filters_unrelated_data[False] |
| #35 | AC-3 | tests/test_agent_tools.py::test_store_signal_captures_provenance_independently[False] |
| #35 | AC-4 | tests/test_backfill_coverage_gaps.py::test_backfill_applies_two_cited_commits_without_unrelated_changes |
| #35 | AC-5 | tests/test_web_app.py::test_signal_evidence_inspection_and_immutable_links[verified] |
| #35 | AC-5 | tests/test_cloudflare_runtime.py::test_local_workers_and_d1_preserve_authenticated_cache_contract |
| #35 | AC-6 | tests/test_web_app.py::test_empty_signal_cache_does_not_claim_no_changes |
| #35 | AC-6 | tests/test_web_app.py::test_signal_evidence_inspection_and_immutable_links[unavailable] |
| #35 | AC-6 | tests/test_web_app.py::test_signal_evidence_inspection_and_immutable_links[partial] |
| #35 | AC-6 | tests/test_mcp_preview_queries.py::test_signal_evidence_and_cache_freshness_are_separate[d1-inaccessible-None-stale-verified] |
| #35 | AC-7 | tests/test_signal_provenance_acceptance.py::test_real_commit_signal_matches_website_export_and_authenticated_mcp |

AC-1 records source identity, immutable commits and relevant changes at creation.
AC-2 persists and exports evidence while leaving legacy signals unverified.
AC-3 exposes capture through the tool and shared service; analyzer prompts also
require full source SHAs in application order. AC-4 limits provenance-backed
backfill to cited changes. AC-5 gives both interfaces matching evidence and
uncertainty. AC-6 covers empty, stale, partial, unavailable and verified responses.
AC-7 checks a real public commit through disposable storage and local interfaces.

These checks never authorize a deployment, existing-database migration or live
ChatGPT rollout. Live hosted acceptance remains a separate operator decision.
