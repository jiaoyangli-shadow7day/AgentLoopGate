# AgentLoopGate arXiv paper source

This directory contains the submission-shaped English manuscript for
AgentLoopGate. Creating these files does not authorize arXiv submission or make
the repository public.

## Build

From this directory:

```sh
tectonic main.tex --keep-logs --keep-intermediates
```

The manuscript uses only source-local figures and standard TeX packages that
Tectonic can resolve. The final reviewed PDF is copied to
`output/pdf/agentloopgate-evidence-governed-evolution.pdf`.

## Before submission

1. Replace the collective author line with the Owner-approved personal author
   names, affiliations, and contact information.
2. Confirm repository visibility and artifact URLs under separate publication
   authorization.
3. Re-run `uv run python -m scripts.verify_arxiv_paper --project .` and
   `./scripts/verify_p0.sh` from the repository root.
4. Compile from a clean checkout and visually inspect every page.
5. Submit only `main.tex`, `references.bib`, and the two figure PDFs required by
   the manuscript; do not include ignored raw experiment traces.

The scientific result must remain a Selection `HOLD`: the paper must not imply
that AHE produced a safe positive evolution, that Release was evaluated, or
that the fixture overhead establishes production latency.
