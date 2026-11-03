# ADR: ChatGPT-first intelligence and hybrid inference

Status: Accepted for experimentation (2026-11-02)
Related: [Bidirectional intelligence MVP](chatgpt-bidirectional-intelligence.md)

## Decision

ForkHub is a **GitHub intelligence product**, not an AI model reseller.
Its value is durable, evidence-backed knowledge about innovations across upstream,
downstream, and sibling forks. ChatGPT is the initial conversational interface,
not the system of record or a private background worker.

Build a **ChatGPT-first read-only MCP experiment** before expanding the existing
Claude analysis pipeline or adding another backend LLM provider.

### Execution boundaries

| Responsibility | Initial owner |
|---|---|
| GitHub API, repository relationships, pagination | ForkHub backend |
| Caching, durable state, provenance | IntelligenceStore |
| Interactive comparisons and reasoning | Host ChatGPT model |
| Existing scheduled detection/classification | Optional existing backend pipeline |
| Backend-controlled background jobs | ForkHub backend, only when needed |
| End-user scheduled prompts | Explore only if supported for installed custom MCP tools |
| Paid account identity, authorization, quotas | ForkHub backend |

A ChatGPT tool response must contain sufficient structured evidence for the
model to explain the source without assuming AI-generated summaries are verified
facts. The backend cannot invoke the host conversation model as a general free
inference API, inspect its hidden state, or rely on it to persist findings.
Any backend OpenAI API processing is separately metered and billed.

### User experience

Present one ForkHub experience, regardless of which provider produced a finding.
Do not expose model brands as primary navigation. Disclose provider use where
privacy, licensing, user settings, or cost requires it.

Use direction-aware findings:
- upstream: what has changed in an original project that might not exist in my fork?
- downstream: what have others developed using my project?
- sibling: which independent alternatives may apply to my fork?

Separate observed code facts, inferred interpretations, and unknown/untested claims.
Label missing coverage and analysis age. Never call a change 'already merged'
based only on the absence of a commit SHA.

### Commercial strategy

The paid product is persistent monitoring and accumulated intelligence, not
access to conversational model reasoning. Initial pricing hypotheses to test,
not commitments: free exploratory tier; Pro ~$12-19/month; Team ~$49-99/month.
Meter scan frequency, repositories, history, retention, background API inference
and premium jobs. Do not depend on native ChatGPT subscription checkout being
available. Check distribution and payment policies before implementation.

Potential product moat:
- persistent fork lineage, dated evidence and historical comparisons
- semantic clustering and deduplication
- relevance assessed relative to a developer's fork
- useful change alerts, team sharing and integrations
- eventually controlled, tested backfill workflows

### Explicit non-goals for this experiment

- Replacing Claude outright or adding an OpenAI Analyzer immediately
- Autonomous writes to source repositories
- Host-ChatGPT-controlled continuous unattended scanning
- Multi-tenant production rollout without OAuth and authorization
- Assuming custom MCP tools are supported inside scheduled ChatGPT tasks
- Adding a full ChatGPT widget before proving tool usefulness

## Experiment and decision gates

1. Build a **local-only read-only MCP prototype** with no model API calls.
   Tools: tracked repos, cached fork relationships, and cached change signals.
2. Exercise in an MCP inspector, and after secure connectivity is available,
   from ChatGPT with explicit tool calls.
3. Compare the same evidence set against the existing Claude analyzer:
   factual correctness, cited SHA/source traceability, useful insights,
   duplicates, latency, and marginal backend cost.
4. Test scheduled tasks *only if* the current ChatGPT installation supports
   invoking this particular custom MCP app in that surface.
5. Add backend-owned analysis only where proactive consistency, coverage or
   paid SLAs demonstrably require it.

**Exit criteria for the spike:** tools connect and return bounded, honest
structured evidence; conversational responses distinguish factual vs inferred
claims; no background model API costs are incurred by an interactive query;
limitations and authorization are documented.

## Deployment/security gate

The initial prototype is bound to loopback and is for a single trusted
developer. A public HTTPS endpoint or tunnel must not be exposed to arbitrary
users because it lacks app-level OAuth, verified identity, and tenant-scoped
authorization. Bind server identity from authenticated credentials in the hosted
version; never trust an arbitrary tool-supplied username as authorization.
