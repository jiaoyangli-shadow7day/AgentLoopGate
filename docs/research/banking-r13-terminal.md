# Banking R13 terminal record

Status: immutable `HOLD`. This document reports the frozen execution; it does
not authorize a rerun, extension, Release, Promote, publication, or submission.

## Frozen identity and scope

- Experiment: `EXP_BANKING_R13`
- Protocol: `sha256:645374c2e757564efcdf97f7f03820526821d711a2a6919cd8b51020a7234848`
- Study: `sha256:5a629b98bd876000ef3b0e12cd80358af4dd285cf7fe19e535fed5f4cc19f011`
- Execution source: `tree:sha256:acf909334915b3dde4a8fc5dd7df4adc4d2fa1db4cb0e77fc801715a70ac9c1a`
- Evaluation baseline: `R13_A0`,
  `sha256:166954514197e3010dcb97de2034d0ae81eb24c8ee46a078ba2fe654b72ead2c`
- Authorization: `AUTH_6B5EFF560128F606EEE3`, limited to the external
  Updater and 25/40/60 pre-Release checkpoint
- Terminal batch: `B_283F2CDCA978213E1AE7`,
  `sha256:757843c7277d6b12d91babc12fa1c299a1b142c33c99bfd8e74020e5b3a69b8d`

## Actual result

All 25 Update-Source positions ran in 8,827,992 ms. Twenty-four were valid,
four were business successes, and `task_048` was Infra Invalid after both
frozen attempts failed. The decision-grade denominator was therefore
incomplete and the batch sealed `HOLD` for `infra_invalid:1` and
`missing_valid_trials`. Pass@1 on the valid subset was `4/24`; it is descriptive
only and is not a complete Source-batch result.

The external Updater made zero calls and produced zero candidates. Update-Check,
Selection, Release-ID/OOD/Replay, Decision, deployment, and Promote all remained
at zero. R13 therefore establishes neither candidate effectiveness nor a
positive self-evolution direction.

`task_020`, which was Infra Invalid in R11, completed normally under the R13
source but failed its business evaluator. This is an observational repair
signal, not a controlled causal estimate.

## Cost, time, retries, and traces

- Exact valid-run Agent cost: USD `0.5747094192`
- Exact valid-run User cost: USD `0.08893360`
- Exact valid-run total: USD `0.6636430192`
- Whole-attempt observed cost lower bound: USD `0.6692124248000000062`
- Unknown scope: the terminal `task_048` User Provider DNS failure returned no
  token or billing evidence; it is unavailable, never USD `0`
- Calls: 742 Agent and 192 User; two task retries, one recovered and one
  exhausted
- Local compute monetary cost: `unmetered_unknown`
- DeepSeek Harness native trace references: 25/25 verified, 811,695 final events
  in total; AgentLoopGate retained references and neither replaced nor deleted
  the host trace

## Position-level waste incident

The cross-stage gate behaved correctly, but the batch scheduler did not stop
after `task_048` had permanently exhausted its retry budget at execution
position 13. It ran all 12 later positions, consuming a task-duration sum of
6,329,212 ms (about 1 h 45 min), 588 terminal model calls, and exact known cost
USD `0.4686327800`. These are observed tail quantities, not a causal effect
estimate.

Before any successor paid work, Protocol must freeze
`stop_before_next_position_after_permanent_infra_invalid_v1`. A no-model
fault-injection acceptance must prove that a non-final permanent infrastructure
failure prevents the next position from starting while preserving the failed
attempt and all earlier cost, trace, raw, and lineage evidence. The resulting
batch must remain immutable `HOLD`, with zero Updater or downstream calls.

The repair is now implemented as Protocol 2.0 and passed deterministic failure
injection, resume-zero-call verification, 206 Python tests, 13 TypeScript tests,
sdist→wheel, DeepSeek Harness conformance/build/pack, and a 307-file
Secret/direct-PII scan with zero findings. It also scopes candidate diagnostics
to the current Experiment and runs a DNS-only Provider precheck without sending
credentials or an HTTP request. The content-addressed calibration is
[`position_fail_fast_calibration.json`](../../artifacts/research/banking_r14/position_fail_fast_calibration.json),
digest `sha256:b098b61edb3ec5bfa6fe80c7e96eeac9540b6bd2c162a999996975f2b056e573`.
This repair does not modify R13 and does not itself create or authorize a paid
successor experiment.

## Claim boundary

R13 supports the systems claim that AgentLoopGate preserves native DeepSeek
Harness traces, records independent attempt/cost evidence, names unknown cost,
and blocks every downstream stage on an incomplete Source denominator. It also
provides direct evidence for a scheduler-efficiency defect. It does not show
that an Updater candidate works, that a correct self-evolution direction was
found, or that the total Provider cost is exactly the reported lower bound.

Authoritative machine records:

- [`formal_execution_seal.json`](../../artifacts/research/banking_r13/formal_execution_seal.json)
- [`fail_fast_incident.json`](../../artifacts/research/banking_r13/fail_fast_incident.json)
