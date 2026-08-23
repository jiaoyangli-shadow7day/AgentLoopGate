# Contributing to AgentLoopGate

Thank you for helping improve evidence-governed Agent Harness evolution.

## Before opening a change

- Keep AgentLoopGate independent from the host runtime. Integrations may consume
  public host events, but must not replace native Trace, Persistence, or
  Telemetry.
- Never commit API keys, credentials, raw customer data, private benchmark
  content, ignored runtime evidence, or paid-authorization artifacts.
- Do not weaken frozen Objective, Split, Evaluator, Pricing, Gate, lineage, or
  fail-closed behavior to make an experiment pass.
- Historical Snapshot, Attempt, Trace, Batch, Cost, Incident, and Decision
  records are immutable. Corrections require a new versioned identity.
- AgentLoopGate produces recommendations; changes must not add automatic
  promotion or deployment.

## Development setup

The supported development environment is Python 3.12 with `uv`. The pinned
DeepSeek Harness integration additionally requires Node.js 22.19 or newer and
the repository's Corepack-managed pnpm version.

```sh
uv sync --frozen
./scripts/verify_p0.sh
```

For a focused Python change, run the smallest relevant test first and then the
complete suite:

```sh
uv run pytest tests/unit/<relevant_test>.py -q
uv run pytest -q
```

For the DeepSeek Harness plugin:

```sh
cd integrations/deepseek-harness
corepack pnpm install --frozen-lockfile
corepack pnpm run typecheck
corepack pnpm test
corepack pnpm run build
corepack pnpm run test:conformance
```

## Pull requests

A pull request should explain the user or evidence-governance problem, the
trust-boundary impact, tests performed, and any migration or compatibility
effect. Changes to an execution source must identify every frozen experiment
identity they supersede. Experiment-result claims require content-addressed,
independently verifiable evidence; fixtures must be labeled as synthetic.

All contributions are submitted under the repository's Apache-2.0 license.
