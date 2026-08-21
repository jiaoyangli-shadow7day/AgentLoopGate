# Decision D_5022F72AFD915DE4

- Candidate: `C_DEMO_COST`
- Baseline: `S_A0`
- Decision: **HOLD**
- Decision digest: `sha256:c9bb413eb54d691c6a60c9a7d6117a3b7bd68d2c6cfd624a2244b67b04852fa7`
- Reason: mean cost ratio exceeds the frozen limit

## Promotion gates

| Gate | Status | Evidence |
|---|---|---|
| evaluation_integrity | pass | `fixture:gates/C_DEMO_COST/evaluation_integrity` |
| leakage | pass | `fixture:gates/C_DEMO_COST/leakage` |
| critical_violation | pass | `fixture:gates/C_DEMO_COST/critical_violation` |
| id_effect | pass | `fixture:gates/C_DEMO_COST/id_effect` |
| ood_noninferiority | pass | `fixture:gates/C_DEMO_COST/ood_noninferiority` |
| replay | pass | `fixture:gates/C_DEMO_COST/replay` |
| reliability | pass | `fixture:gates/C_DEMO_COST/reliability` |
| cost | fail | `fixture:gates/C_DEMO_COST/cost` |
| latency | not_evaluated | `fixture:gates/C_DEMO_COST/latency` |

`SHIP_RECOMMENDED` is not a deployment; human CLI approval is still required.
