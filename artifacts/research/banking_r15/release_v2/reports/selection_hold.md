# EXP_BANKING_R15 Selection HOLD

AgentLoopGate completed Selection and abstained from nominating a release candidate. This is a normal governed terminal outcome, not an infrastructure failure.

- Decision: `HOLD`
- Reason: `no_candidate_passed_baseline_bound_selection_policy`
- Baseline: `R15_A0`
- Updater-native candidate: `C_AHE_758BDB468FB4`
- AgentLoopGate candidate: `null`
- Release/OOD/Replay batches started after Selection: `0`
- Batch model cost: USD `3.8830976464000000116`
- Updater known model cost: USD `0.0255671416`
- Total known model cost: USD `3.9086647880000000116`
- Overall cost status: `exact`
- Selection digest: `sha256:b5e800793f700e1d096a325961b3f40bac8cd93d12dddbdcbc111d48fa600466`
- Lineage digest: `sha256:162c01c16a486cb3a630a7a0ccfd421fe418bca52e67e1dfd1a8c9f21a620bb9`

## Candidate findings

- `C_AHE_217A9DDE7972`: stable_task_regression:task_062,task_095, no_stable_success_gain, p95_latency_noninferiority
- `C_AHE_758BDB468FB4`: stable_task_regression:task_062,task_095, no_stable_success_gain, p95_latency_noninferiority, timeout_increase
- `C_AHE_B55294C01B2A`: stable_task_regression:task_056,task_062,task_095, no_stable_success_gain, p95_latency_noninferiority

No deployment, promotion, publication, or release action was performed.
