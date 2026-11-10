# Observability

Stack: existing observability harness, lite mode, service `forkhub`.

Recorded check on 2026-11-10:

```text
bash .claude/harness/observability/status.sh --json
vector DOWN; no live PID
```

The script does not currently implement JSON output despite accepting the
argument. It exits zero even when Vector is down; its exit code is not a health
proof. The stack is recorded as broken/unavailable for this verification, not as
an absent stack or successful telemetry proof.

The configured OTLP HTTP endpoint is `http://127.0.0.1:4418` in
`.claude/harness/observability/harness.env`. Instrumentation lives in
`src/forkhub/otel.py`; without the optional OTel dependency group it is a no-op.
No collector is started or reconfigured by verification.

When an operator restores the stack, rerun the status check, exercise the changed
path, and inspect the actual JSONL traces/logs/metrics under
`.claude/harness/observability/data/jsonl/`. An empty or missing data directory is
not evidence that a request ran. Until then, runtime proof comes from the actual
website, database values and authenticated local MCP responses; no live telemetry
claim is made.
