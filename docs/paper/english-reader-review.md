# English manuscript unfamiliar-reader review

Status: completed for the open-source manuscript revision

This document records a structured AI-simulated reading review. It is not a
human-subject study and is not reported as empirical usability evidence. The
purpose is editorial: test whether readers who know the AI field but have no
prior AgentLoopGate context can reconstruct the paper's argument without
guessing project-specific terminology.

## Review rubric

Each reader must be able to answer five questions after one pass:

1. What problem does AgentLoopGate solve?
2. What is a harness candidate, and how does it move through the evaluation
   pipeline?
3. What was evaluated in Banking R15?
4. Why did the system return HOLD?
5. What does the paper establish, and what does it explicitly not establish?

A blocking issue is an undefined term, symbol, or stage boundary that prevents
one of these answers. A non-blocking issue may slow an audit of the appendix but
does not change the reader's understanding of the main argument.

## Reader 1: language-agent researcher

Assumed background: understands tool-using language agents, reflection, prompt
optimization, and interactive benchmarks; does not know AgentLoopGate, its
experiment names, or its artifact schema.

### First-pass obstacles

- A candidate was introduced symbolically as `C_i` before the paper said what
  changed in a candidate.
- `Update-Source`, `Update-Check`, `Selection`, and the Release stages appeared
  as internal names rather than a continuous experimental story.
- `stable success` could be read as either repeated-trial reliability or a
  single successful task outcome.
- The early `H0/L0/L1/L2` labels imposed an unnecessary memory burden.

### Revision and second-pass result

The paper now defines a candidate as an immutable snapshot of permitted harness
assets, explains stable success and the R15 trial count, adds a plain-language
walk through every stage, and removes the H/L shorthand from the main
explanation. The simulated reader can now explain that AgentLoopGate judges
proposals independently rather than generating a new model, and can distinguish
candidate generation from positive evolution. Result: pass.

## Reader 2: ML systems and evaluation researcher

Assumed background: understands experimental isolation, paired comparisons,
bootstrap intervals, provenance, and release gates; does not know the Banking
task layout or the project's stage names.

### First-pass obstacles

- `125 positions` lacked a definition of the experimental unit.
- The paper referred to six isolated pools without naming their roles or
  clarifying that Replay reuses a preregistered earlier set.
- Release-ID, Release-OOD, and Replay were listed before their evaluation
  purposes were explained.
- The candidate-effectiveness claim and the governance-system claim were easy
  to conflate.

### Revision and second-pass result

The paper now defines a position as one stage-by-variant-by-task-by-trial
execution, names the stage-specific pools and replay set, explains each Release
stage at first use, and repeats the claim boundary in the abstract,
introduction, results, discussion, limitations, and conclusion. The simulated
reader can reconstruct the 25 + 40 + 60 pre-Release matrix and explain why a
paired HOLD is positive governance evidence but not positive self-evolution.
Result: pass.

## Reader 3: agent-platform engineer

Assumed background: builds agent runtimes and telemetry integrations; does not
know the project's Python schemas, DeepSeek Harness plugin internals, or the
meaning of content-addressed receipts.

### First-pass obstacles

- The evidence-layer labels described storage levels before explaining the
  concrete path from a native trace to a release decision.
- `bounded updater` did not immediately say what access was limited or what
  kinds of assets could change.
- The DeepSeek Harness section explained coexistence but did not summarize the
  reusable capabilities a developer receives.
- `lexicographic gate` was accurate but less accessible than an ordered set of
  release prerequisites.

### Revision and second-pass result

The paper now follows one execution from native trace, to source reference, to
normalized run, to study evidence; renames the updater and gate in plain
language; gives examples of mutable harness assets; and states the three plugin
outcomes: verifiable native-trace linkage, normalized run/cost facts, and an
evidence-based decision about whether evaluation may advance. The simulated
reader can identify the integration boundary without assuming that
AgentLoopGate replaces persistence or OpenTelemetry. Result: pass.

## Residual reading cost

The P0--R14 formation table and the claim-to-artifact maps remain dense because
they preserve audit identifiers, costs, and repository paths. They are placed
in the appendix and are not required to understand the main argument. A reader
who wants to reproduce or audit the claims will still need familiarity with
content hashes and experiment artifacts; that is an intended property of the
artifact section rather than an unexplained dependency of the main text.

## Final editorial acceptance

All three simulated readers can recover the paper's problem, mechanism,
experiment, result, and claim limits without prior project knowledge. No
blocking project-specific symbol or stage name remains undefined before it is
needed in the main narrative.
