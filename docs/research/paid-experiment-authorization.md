# Paid experiment authorization boundary

AgentLoopGate separates scientific freezing from permission to spend. A valid
Objective, Split, Protocol, Study, Snapshot, credential, and runtime are still
insufficient to start a new paid Batch. Formal config schema 1.2 also names a
private authorization root, normally under `runs/authorizations/<experiment>`.

The authorization directory is runtime evidence and is not execution source.
Adding an authorization therefore cannot silently change the frozen Snapshot
identity. It is not committed to a public package; publication exposes only the
minimum digest and scope needed for provenance.

## Two independent scopes

| Scope | Exact stages | Banking 1.2 positions | Additional binding |
|---|---|---:|---|
| `pre_release_checkpoint` | Update-Source, Update-Check, Selection | 125 | Protocol, Study, execution source and Owner confirmation |
| `release_tail` | Release-ID, Release-OOD, Replay | 450 | The above plus the immutable `SELECT` digest and governed Candidate ID |

The second scope cannot be created from a `HOLD/ABSTAIN` Selection. A sealed
`selection_hold_outcome.json` permanently blocks Release authorization for that
experiment. Existing-only evidence verification never needs paid authorization
and never calls a model.

## Owner action

Do not run either command from a standing automation or infer permission from a
credential being present. After the Owner explicitly authorizes the exact
scope, the operator runs one of:

```sh
agentloopgate experiment authorize-paid \
  --config <formal-config-1.2> \
  --scope pre_release_checkpoint \
  --authorized-by owner \
  --confirm OWNER_AUTHORIZED_PRE_RELEASE_CHECKPOINT \
  --json

agentloopgate experiment authorize-paid \
  --config <formal-config-1.2> \
  --scope release_tail \
  --authorized-by owner \
  --confirm OWNER_AUTHORIZED_RELEASE_TAIL \
  --json
```

The command makes zero model calls and does not start a paid stage. It verifies
the frozen identities, writes one content-addressed authorization, and reports
`paid_execution_started=false`. Repeating the same command only verifies and
reuses identical authorization evidence. A changed actor, source, Protocol,
Study, task-position count, Selection, or scope fails closed.

CLI preflight verifies the pre-Release artifact. `FormalExperimentService`
verifies the applicable artifact again immediately before every new paid
stage, so bypassing the CLI preflight does not bypass authorization. A Release
stage additionally re-verifies the Selection bytes and refuses `HOLD`.

The repository currently contains no authorization for the next experiment;
`PAID_HOLD` remains in force.
