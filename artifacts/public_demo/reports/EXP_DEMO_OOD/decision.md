# Decision D_8FC46902C44F8662

- Candidate: `C_DEMO_OOD`
- Baseline: `S_A0`
- Decision: **HOLD**
- Decision digest: `sha256:7d8674642dd16995da808104f37d654b14c79e3d9e1f1fc984af859cfce4ec4d`
- Reason: OOD stable-task effect is below the frozen noninferiority margin

## Promotion gates

| Gate | Status | Evidence |
|---|---|---|
| evaluation_integrity | pass | `fixture:gates/C_DEMO_OOD/evaluation_integrity` |
| leakage | pass | `fixture:gates/C_DEMO_OOD/leakage` |
| critical_violation | pass | `fixture:gates/C_DEMO_OOD/critical_violation` |
| id_effect | pass | `fixture:gates/C_DEMO_OOD/id_effect` |
| ood_noninferiority | fail | `fixture:gates/C_DEMO_OOD/ood_noninferiority` |
| replay | not_evaluated | `fixture:gates/C_DEMO_OOD/replay` |
| reliability | not_evaluated | `fixture:gates/C_DEMO_OOD/reliability` |
| cost | not_evaluated | `fixture:gates/C_DEMO_OOD/cost` |
| latency | not_evaluated | `fixture:gates/C_DEMO_OOD/latency` |

`SHIP_RECOMMENDED` is not a deployment; human CLI approval is still required.
