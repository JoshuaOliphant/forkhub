# Jev follow-through for PR #67

Rerun on 2026-11-10 at executable head `b60b49c`. The earlier subprocess did not
inherit `TYPESAFE_API_KEY`; the credential already existed in the interactive
shell and macOS app launch environment. Running the installed tools through
`/bin/zsh -lic` restored access without printing, persisting or changing the key.
This supersedes the earlier claim that a credential needed to be installed.

## Checks actually run

| Check | Observed result |
| --- | --- |
| `review-risk` | Exit 0; all 44 changed files ranked; structural risk confirmed. |
| `canon-pick` | Exit 0; prove-it-works, boundary-discipline and expand-contract selected, read and applied. |
| `locate` | Exit 0; 13 claims checked, 11 located; verify-name and protocol-declaration claims not confidently located. |
| `triage-finding` | Exit 0; 10 not-a-finding, 2 minor and 1 low-confidence major; independent skeptic checked the remaining claims. |
| `test-value` | Exit 0; no missing source statements or proposed exclusions; no model judgment needed for an empty gap list. |
| `ac-exercised` | Exit 0; all 14 cached acceptance mappings affirmed, `to_read=[]`. |
| `claim-backed` | Exit 0; all seven fresh verification claims backed, `unbacked=[]`. |
| `jev-lint --diff origin/main` | Exit 0; 0 findings from 109 judgments over 76 diff units. |
| Source-unit Jev lint | 221 judgments over 92 touched source units; 13 residual flags reviewed below. This run is **not** reported as clean. |

The source-unit pass reused the installed linter's extractor, rules, thresholds
and judging functions. It selected touched comments/handlers/log calls and
functions containing changed lines, excluding unrelated baseline code.

Initial verification judgments lacked some evidence: test gathering clipped long
tests at 4,000 characters, and combined-log clipping omitted middle summary lines.
A process-local source-gathering limit of 20,000 characters supplied complete
tests; focused, unaltered command-output excerpts supplied the gate summaries.
Installed tool files and judgment thresholds were unchanged. Original and
follow-up outputs are preserved.

## Findings addressed

- `a7826cd`: separate provider/time I/O from pure evidence evaluation; assert
  diagnostics and no I/O for missing references/files in the existing tests.
- `60b05df`: separate pure JUnit interpretation from file reads. Run advisory
  remote freshness last; missing CLI, failed requests and invalid JSON explicitly
  report unknown freshness. Invalid local metadata still raises. Temporary CLI
  executables exercise these outcomes without mocking the implementation.
- `08e7e4a`: directly assert the exported repository, SHA and patch, protecting
  against both readers dropping evidence. Preserve available GitHub credentials
  before test environment cleaning, exposing only a factory closure as a fixture.
- `b60b49c`: remove redundant private docstrings, correct the tool/website read
  contracts and remove the session-specific GraphQL rationale from tracker docs.

## Residual source flags: explicit dispositions

| Flag | Evidence-based disposition |
| --- | --- |
| `agent/tools.py:351` — handler I/O mixing | SDK boundary; pure reference parsing at `:42`, delegated capture/model validation. Storage/uncertainty assertions: `tests/test_agent_tools.py:790`. |
| `services/backfill.py:253` — adoption I/O mixing | Application orchestration binds database/provider/Git boundaries; persistence/refusal and actual-tree results are tested at `tests/test_backfill.py:1435,1461,1487,1995` and `tests/test_backfill_coverage_gaps.py:934,990`. |
| `services/backfill.py:463` — apply/test I/O mixing | Explicit candidate Git/test operation through `_git`; real chronology/final-tree assertions cover effects. Jev triaged this as minor; no needed extra layer demonstrated. |
| `scripts/verify.py:81` — contradictory warning contract | CLI warnings return at `:99-106`; local metadata raises through `:83`. Both promises are asserted at `tests/test_verify.py:125,172`. |
| `services/backfill.py:375` — silent fetch failure | Logs and records filenames, then returns/persists `PATCH_FAILED` and `Partial fetch`; assertions at `tests/test_backfill.py:1435,1461,1487`. |
| `web/data.py:12` — I/O mixing | Presentation read edge consumes shared library views, not duplicate analysis; exact parity at `tests/test_web_data.py:118`. |
| `scripts/verify.py:115` — orchestrator I/O mixing | CLI gate runner; JUnit interpretation, acceptance decisions and freshness comparison are separate pure helpers. |
| `services/evidence.py:112` — silent retrieval failure | Exception becomes a public diagnostic plus unavailable/partial state; state, warning and actual diagnostic asserted at `tests/test_signal_evidence.py:37`. |
| `agent/tools.py:46` — silent JSON parsing failure | Explicit unusable-reference flag is consumed at `:367,390-396` to warn and prevent verified status. Stored interpretation, warning and verification timestamp asserted at `tests/test_agent_tools.py:819-831`. Independent skeptic refuted the low-confidence major and reran both cases successfully. |
| `scripts/verify.py:115` — name hides effects | Documented executable verification entry point; gates/disposable artifacts are advertised behavior. Jev triaged this as minor. |
| `scripts/verify.py:81` — fetch name hides effects | `fetch_remote_cache_warning` explicitly names read-only network access and returns the advisory result its caller prints. |
| `providers/github.py:334` — get name hides effects | Provider retrieval follows existing get-repo/head/rate-limit conventions; immutable request asserted at `tests/test_github_provider.py:653`. |
| `interfaces.py:62` — protocol get name hides effects | Protocol declaration for that retrieval operation, with no implementation hiding additional effects. |

These are refutations/design judgments, not suppressed findings. No actionable
or unjudged finding remains after independent review.

## Fresh verification and scope

The repeatable verifier exited 0: 1,038 unit tests, 4,063/4,063 source statements
(100%), 114 Ruff files, both integration tests, all 14 acceptance mappings,
isolated production import and a nonempty Worker dry-run bundle.

Raw artifacts: `/private/tmp/forkhub-jev-rerun/` (not committed). An optional
setup-plan probe failed in pytest-asyncio; it is not a product test or passing
gate. The documented ambient npm warning remains outside test output. No
installed plugin, global shell configuration, production endpoint, hosted
database or operational cache changed. Live ChatGPT acceptance is still pending
a separately approved rollout.
