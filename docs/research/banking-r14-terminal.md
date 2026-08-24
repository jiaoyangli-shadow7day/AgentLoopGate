# Banking R14 terminal record

Status: immutable `HOLD` as of 2026-08-24. R14 must not be resumed, refilled,
or extended.

## Frozen identity

- Experiment: `EXP_BANKING_R14`
- Protocol: `BANKING_R14_PROTOCOL_1`, digest
  `sha256:8c6baf57c6f6c339881468e966b3b5522784143e39f88be5a7578ddc3a353de1`
- Study: `BANKING_R14_STUDY_1`, digest
  `sha256:e2afe1330afbc87b0922274af3db1f6fc0ea43b377398962a658a972dc935d96`
- Source revision:
  `tree:sha256:0e2b2ea58bb57f69d6a5604003297870c9cca998b712c52e78c654cbb9325abe`
- Evaluation baseline: `R14_A0`, digest
  `sha256:5c1873205b9598e7458a94e8002c5bebfb0bdb29d279c8aa913970ff56d2024b`
- Paid capability: `AUTH_5FA037EDA2B6782B4C57`, digest
  `sha256:d21a92967513688d101060f88fd996e8b78d692b6c5591bd458e2665ab0d9dd8`
- Formal command wall time: 20,013.89 seconds; maximum RSS 657,424,384
  bytes. Local compute monetary cost remains `unmetered_unknown`.

## Execution result

R14 executed 46 of 125 authorized formal positions: 45 were valid and one was
Infra Invalid. It started 53 task attempts, completed 45, and retained eight
failed attempts, including every recovery retry. It did not start Selection,
Release-ID, Release-OOD, Replay, Promote, publication, or a repository
visibility change.

| Stage or subject | Positions | Result | Exact whole-attempt model cost |
|---|---:|---|---:|
| Update-Source `R14_A0` | 25/25 valid | 7/25 | USD `0.8244735576` |
| External AHE Updater | 4 proposal attempts | 3 selected candidates across required families; 40 calls, 0 unresolved | USD `0.0140907872` |
| Update-Check `R14_A0` | 10/10 valid | 4/10 | USD `0.2986731776` |
| Update-Check `C_AHE_018455531828` | 10/10 valid | 3/10; regressed baseline-success task `task_052` | USD `0.3498881872000000032` |
| Update-Check `C_AHE_3F448BFD7A0D` | 0/1 valid, 1 Infra Invalid | two `CapabilityBindingError` attempts | USD `0.000504` |
| Update-Check `C_AHE_FD23444961C6` | 0/10 started | blocked by prior permanent invalidity | USD `0` observed because it never started |
| Selection | 0/60 started | blocked | USD `0` observed because it never started |

Total exact known model cost is USD `1.4876297096000000032` across 1,974
terminal Agent, User, and Updater calls. Unresolved calls and unknown model-cost
scopes are both zero. This total includes failed attempts; it is not the sum of
retained successful simulations alone.

## What failed and what worked

The second external candidate modified `harness/tools/routing.yaml`. Its frozen
Candidate Check reported `PASS`, but the materialized YAML added fields inside
`capability_binding`. Runtime requires that mapping to equal exactly:

```yaml
capability_binding:
  source: runtime_tool_schema
  reject_unknown_route_targets: true
```

The original semantic validator checked the live baseline bytes plus selected
Diff tokens. It did not apply the patch and validate the prospective candidate
bytes. Both `task_027` attempts therefore failed before an Agent model turn with
`tool routing is not bound to the runtime tool schema`. Two User Simulator calls
had already completed, costing exactly USD `0.00025354` and `0.00025046`.

Protocol 2.0 position fail-fast then worked as designed. Trigger
`sha256:c3a8e491ebb589d91cefe48bdff4c2a0ed22fe17ba5b540fe133548685ef5052`
states `next_position_started=false`. No later position in that batch and no
post-trigger model call started. This prevented 19 remaining Update-Check and
60 Selection positions from running. Their counterfactual cost is not
identifiable and is not claimed as savings.

The runner nevertheless exposed a second control-plane gap: it returned
`formal_evidence_invalid` because the raw tau3 result lacked a valid trial,
rather than sealing a first-class candidate rejection or immutable batch HOLD
with its own batch and cost artifact. The manually audited terminal seal
preserves this fact; it does not manufacture a missing formal batch.

## Successor repair

The successor source now applies guarded patches in an isolated temporary tree
and validates the post-patch YAML before candidate registration. A no-model
regression replay produced:

- `C_AHE_018455531828`: `PASS` (unchanged valid candidate);
- `C_AHE_3F448BFD7A0D`: `REJECT_UNBOUND_CAPABILITY`;
- `C_AHE_FD23444961C6`: `REJECT_UNBOUND_CAPABILITY`.

It also rejects static `capability:` targets in both mapping and YAML list-item
forms. The runner repair now also accepts only a verified fail-fast partial
trial subset, seals it as immutable `HOLD`, retains exact cost, and makes resume
verify-only. A failure before the first Agent turn is explicitly recorded as
`pre_agent_failure_unavailable`: no DSH trace or evidence join is invented.
Agent and User usage ledgers are initialized before the child process so zero
calls remain distinguishable from a missing ledger. A no-model R14-shaped
fixture verifies two exact User calls, zero Agent calls, exact aggregate cost,
the missing denominator, and no re-execution on resume. These repairs do not
alter or backfill R14 and authorize no paid work. A successor must freeze a new
Protocol, Study, source revision, baseline, private CI record, and machine
capability.

Successor repair validation artifact:
`artifacts/research/banking_r14/successor_repair_validation.json`, digest
`sha256:65cbd8cdebd6ab3ea7bd4d7f58a3f937cdd61c47b3cc534c30b568b399b281c8`.

## Scientific interpretation

R14 strengthens the systems claim: AgentLoopGate preserved 45 completed
DeepSeek Harness run references, recorded exact whole-attempt costs, generated
external candidates, observed an A0-bound paired Check, and stopped immediately
after a permanent invalid position. It also demonstrates that the governance
layer can expose defects in candidate generation and its own validation path.

R14 does **not** establish candidate effectiveness or a correct self-evolution
direction. The only fully evaluated candidate scored 3/10 where A0 scored 4/10
and regressed `task_052`; the other two candidates were not fully evaluated,
and Selection never ran. The correct statement is that R14 rejected an
unsupported continuation before Release, not that it found a better harness.

## Authoritative artifacts

- Incident:
  `artifacts/research/banking_r14/candidate_binding_precheck_incident.json`,
  digest
  `sha256:adc16393846689bb875ef56c33b8c45a9401f2c9eda8e041fdfe34fad6091f26`
- Terminal seal: `artifacts/research/banking_r14/formal_execution_seal.json`,
  digest
  `sha256:b82bdbe871fe7e9fefeb62b6075b60f7e7daca55a0c1cfae922d4822247723e5`
- Successor repair validation:
  `artifacts/research/banking_r14/successor_repair_validation.json`, digest
  `sha256:65cbd8cdebd6ab3ea7bd4d7f58a3f937cdd61c47b3cc534c30b568b399b281c8`
- Failed-position raw result:
  `runs/experiments/EXP_BANKING_R14/raw/B_48A834A838339F0D0D17.json`
- Failed-position attempt ledger and trigger:
  `runs/experiments/EXP_BANKING_R14/task_attempts/B_48A834A838339F0D0D17.jsonl`
  and `.position_fail_fast.json`
- Failed-position User usage:
  `runs/experiments/EXP_BANKING_R14/user_model_usage/B_48A834A838339F0D0D17.jsonl`
