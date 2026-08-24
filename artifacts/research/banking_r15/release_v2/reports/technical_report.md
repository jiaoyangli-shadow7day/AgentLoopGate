# EXP_BANKING_R15: evidence-governed Selection HOLD

## Abstract

AgentLoopGate evaluated three external AHE Harness proposals against a frozen A0 baseline on an identical 15-task Banking Selection population. No proposal achieved a strict stable-task gain without regression, so the system emitted HOLD and made zero Release calls. Two candidates tied A0 in aggregate while exchanging gained and lost tasks, demonstrating why paired evidence is necessary. This is evidence for governance utility, not for a positive or generalizable self-evolution effect.

## Method

The statistical unit is the task. Each candidate is compared with A0 using the preregistered deterministic paired bootstrap (10,000 resamples, 95% nearest-rank interval). Intervals are descriptive for the frozen task set; the candidates are dependent proposals and no multiplicity-adjusted or cross-domain claim is made. Cost is exact valid-run mean model cost.

## Selection results

| Variant | Stable success | Gains | Regressions | Paired net | 95% interval for rate difference | Mean model cost (USD) |
|---|---:|---|---|---:|---:|---:|
| C1 | 6/15 | 017, 096 | 062, 095 | 0 | [-0.2666666666666666666666666667, 0.2666666666666666666666666667] | 0.03234137946666666666666666667 |
| C2 | 5/15 | 017, 090 | 056, 062, 095 | -1 | [-0.3333333333333333333333333333, 0.2] | 0.03336626309333333333333333333 |
| C3 | 6/15 | 017, 090 | 062, 095 | 0 | [-0.2666666666666666666666666667, 0.2666666666666666666666666667] | 0.03397075882666666666666666667 |

A0 scored 6/15. All three candidates regressed tasks 062 and 095; all gained task 017. The observed intervals include zero, and the zero-regression prerequisite fails regardless of interval width.

## Diagnosis and system evidence

The 25 valid Update-Source runs contained 19 failed tasks: 3 primary tool-selection failures and 16 primary state-verification failures. Registered DeepSeek Harness fixture evidence separately verifies JSONL/SQLite native persistence, observer completeness, event-hash equivalence, and OTel coexistence.

## Cost accounting

All nine formal batches cost USD 3.8830976464000000116; external Updater calls cost USD 0.0255671416; exact known model cost was USD 3.9086647880000000116. Unknown model-cost scope: none. Local compute monetary cost is unmetered/unknown rather than zero.

## Conclusion and limitations

AgentLoopGate prevented unsupported promotion that aggregate scoring could have obscured. R15 does not validate a Release candidate, AHE superiority, production-load plugin latency, or cross-domain transfer. Release-ID, OOD, and Replay were correctly not run. A future guided updater requires a new frozen identity and untouched confirmation tasks.

## Evidence binding

- Private outcome: `sha256:827ed2a5b3337832c49cd255f17568fad3a58fe201860311d66decb83ba0bdc3`
- Selection: `sha256:b5e800793f700e1d096a325961b3f40bac8cd93d12dddbdcbc111d48fa600466`
- Statistics: `sha256:8bc2da84cefc7ed100947401a6277d9fab49109ce29d065f91b064a3a2f5b8ba`
- Publication authorization: not granted by package creation
