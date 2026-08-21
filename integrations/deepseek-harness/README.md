# @agentloopgate/dsh-plugin

Native DeepSeek Harness Bundle for AgentLoopGate. It observes the public append-only Session event stream, calls the local Python Core through bounded stdio JSONL, and registers four read-only governance tools. It does not provide or replace Session Persistence or Session Telemetry.

The live firehose is reconciled against the same public `session.events` snapshot at every
Session flush. This recovers constructor/resume events that DeepSeek Harness intentionally
does not publish live, while keeping ingestion memory bounded to one configured batch. Core
still requires a continuous cursor; an unrecovered gap remains `evidence_incomplete`.

Compatibility is pinned to DeepSeek Harness `0.1.0-rc.8`, source commit `141eb6fef83422698aef7a981029e843e8161534`, Node `^22.19 || >=24`, and pnpm `11.7.0`.
