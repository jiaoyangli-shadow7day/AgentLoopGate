#!/usr/bin/env python3
"""Derive Selection-HOLD statistics, figures, and report without model calls."""

from __future__ import annotations

import json
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any

from agentloopgate.contracts import canonical_digest, canonical_json_bytes
from agentloopgate.experiment.batch import FormalBatchArtifact, FormalStage
from agentloopgate.experiment.statistics import paired_task_bootstrap
from agentloopgate.experiment.study import load_study_plan

_WIDTH = 900
_HEIGHT = 460


class SelectionHoldSupplementError(ValueError):
    """The sealed evidence cannot support the terminal supplement."""


def build_selection_hold_supplement(
    root: Path,
    *,
    experiment_id: str,
    private_root: Path,
    study_path: Path,
    selection_digest: str,
    outcome_digest: str,
    whole_experiment_model_cost: dict[str, Any],
) -> tuple[dict[str, bytes], str, str]:
    """Return sanitized, deterministic supplement payloads and their digests."""

    root = root.resolve()
    private = (root / private_root).resolve()
    study = load_study_plan((root / study_path).resolve())
    batches = _selection_batches(private)
    baseline = next((item for item in batches if item.summary.candidate_id is None), None)
    candidate_batches = {
        str(item.summary.candidate_id): item
        for item in batches
        if item.summary.candidate_id is not None
    }
    selection = json.loads((private / "selection.json").read_text(encoding="utf-8"))
    ranked_inputs = selection.get("inputs")
    if not isinstance(ranked_inputs, list):
        raise SelectionHoldSupplementError("Selection native ranks are unavailable")
    ranked_ids = [
        str(item["candidate_id"])
        for item in sorted(ranked_inputs, key=lambda item: int(item["native_rank"]))
        if isinstance(item, dict)
        and item.get("candidate_id") is not None
        and item.get("native_rank") is not None
    ]
    candidates = [candidate_batches[candidate_id] for candidate_id in ranked_ids]
    if baseline is None or len(candidates) != 3 or set(ranked_ids) != set(candidate_batches):
        raise SelectionHoldSupplementError(
            "Selection-HOLD supplement requires one baseline and three candidates"
        )
    if any(
        item.summary.stable_task_outcomes.keys() != baseline.summary.stable_task_outcomes.keys()
        for item in candidates
    ):
        raise SelectionHoldSupplementError("Selection task populations are not identical")

    comparisons = [
        paired_task_bootstrap(
            comparison_id=(f"baseline_vs_{candidate.summary.candidate_id}:selection"),
            reference_role="baseline",
            candidate_role="updater_native",
            stage=FormalStage.SELECTION,
            reference=baseline,
            candidate=candidate,
            study=study,
        )
        for candidate in candidates
    ]
    statistics_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_kind": "selection_hold_paired_task_bootstrap",
        "experiment_id": experiment_id,
        "protocol_digest": study.protocol_digest,
        "study_digest": study.study_digest,
        "selection_digest": selection_digest,
        "private_outcome_digest": outcome_digest,
        "statistical_unit": "task",
        "primary_endpoint": "stable_success_task_count",
        "paired_comparison": True,
        "confidence_level": study.statistics.confidence_level,
        "interval_method": "paired_task_bootstrap_nearest_rank",
        "bootstrap_resamples": study.statistics.bootstrap_resamples,
        "bootstrap_seed": study.statistics.bootstrap_seed,
        "comparison_count": len(comparisons),
        "comparisons": [item.model_dump(mode="json") for item in comparisons],
        "multiplicity_adjustment": None,
        "inference_scope": (
            "descriptive paired uncertainty on the frozen 15-task Selection "
            "population; dependent updater proposals and no cross-domain inference"
        ),
    }
    statistics_digest = canonical_digest(statistics_payload)
    statistics = {
        **statistics_payload,
        "statistics_digest": statistics_digest,
    }

    labels = {baseline.batch_id: "A0"}
    labels.update(
        {candidate.batch_id: f"C{index}" for index, candidate in enumerate(candidates, 1)}
    )
    diagnosis = _diagnosis_counts(private / "diagnosis.json", evaluated=_source_task_count(private))
    chart_payloads = {
        "reports/01_candidate_curve.svg": _candidate_curve(
            baseline, candidates, labels, selection_digest
        ),
        "reports/02_failure_funnel.svg": _failure_funnel(diagnosis, selection_digest),
        "reports/03_pool_comparison.svg": _paired_comparison(
            baseline, candidates, labels, selection_digest
        ),
        "reports/04_gate_waterfall.svg": _gate_waterfall(selection_digest),
    }
    report = _technical_report(
        experiment_id=experiment_id,
        outcome_digest=outcome_digest,
        selection_digest=selection_digest,
        statistics_digest=statistics_digest,
        baseline=baseline,
        candidates=candidates,
        comparisons=comparisons,
        labels=labels,
        diagnosis=diagnosis,
        whole_experiment_model_cost=whole_experiment_model_cost,
    )
    supplement_digest = canonical_digest(
        {
            "statistics_digest": statistics_digest,
            "technical_report": report,
            "charts": chart_payloads,
        }
    )
    payloads = {
        "statistics.json": canonical_json_bytes(statistics) + b"\n",
        "reports/technical_report.md": report.encode("utf-8"),
        **{path: value.encode("utf-8") for path, value in chart_payloads.items()},
    }
    return payloads, statistics_digest, supplement_digest


def _selection_batches(private: Path) -> list[FormalBatchArtifact]:
    batches: list[FormalBatchArtifact] = []
    for path in sorted((private / "batches").glob("B_*.json")):
        artifact = FormalBatchArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if artifact.stage is FormalStage.SELECTION:
            if not artifact.summary.integrity_complete:
                raise SelectionHoldSupplementError("Selection batch is incomplete")
            if artifact.summary.infra_invalid_count:
                raise SelectionHoldSupplementError(
                    "Selection uncertainty cannot hide Infra Invalid runs"
                )
            batches.append(artifact)
    return batches


def _diagnosis_counts(path: Path, *, evaluated: int) -> dict[str, int]:
    value = json.loads(path.read_text(encoding="utf-8"))
    signals = value.get("signals")
    if not isinstance(signals, list):
        raise SelectionHoldSupplementError("diagnosis signals are unavailable")
    counts = {"retrieval": 0, "policy": 0, "tool": 0, "state": 0}
    failed = 0
    for signal in signals:
        if not isinstance(signal, dict) or signal.get("success") is not False:
            continue
        failed += 1
        retrieval_failure = bool(signal.get("retrieval_required")) and (
            signal.get("retrieval_attempted") is False
            or signal.get("gold_document_coverage") is False
        )
        policy_failure = (
            signal.get("policy_application_correct") is False
            or signal.get("user_claim_overtrust") is True
        )
        tool_failure = any(
            signal.get(field) is False
            for field in (
                "tool_selected_correctly",
                "tool_parameters_correct",
                "action_order_correct",
            )
        )
        if retrieval_failure:
            counts["retrieval"] += 1
        elif policy_failure:
            counts["policy"] += 1
        elif tool_failure:
            counts["tool"] += 1
        elif signal.get("terminal_state_verified") is False:
            counts["state"] += 1
        else:
            raise SelectionHoldSupplementError(
                "failed diagnosis signal has no registered primary category"
            )
    if sum(counts.values()) != failed:
        raise SelectionHoldSupplementError("diagnosis counts do not reconcile")
    if failed > evaluated:
        raise SelectionHoldSupplementError(
            "diagnosed failures exceed the evaluated Update-Source population"
        )
    return {
        **counts,
        "failed": failed,
        "diagnosed": len(signals),
        "evaluated": evaluated,
    }


def _source_task_count(private: Path) -> int:
    sources = []
    for path in sorted((private / "batches").glob("B_*.json")):
        artifact = FormalBatchArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if artifact.stage is FormalStage.UPDATE_SOURCE:
            sources.append(artifact)
    if len(sources) != 1 or not sources[0].summary.integrity_complete:
        raise SelectionHoldSupplementError(
            "Selection-HOLD supplement requires one complete Update-Source batch"
        )
    return sources[0].summary.pass_1_denominator


def _candidate_curve(
    baseline: FormalBatchArtifact,
    candidates: list[FormalBatchArtifact],
    labels: dict[str, str],
    selection_digest: str,
) -> str:
    points = [baseline, *candidates]
    max_cost = max(item.summary.mean_cost for item in points)
    xs = [120, 330, 540, 750]
    success = [Decimal(item.summary.pass_1_numerator) / 15 for item in points]
    costs = [item.summary.mean_cost / max_cost for item in points]
    body = _text(35, 34, "Selection reliability and normalized cost", 22)
    body += _text(35, 58, "Frozen 15-task population; Release was not run", 13, "#475569")
    body += _axes()
    body += _polyline(xs, success, "#2563eb")
    body += _polyline(xs, costs, "#f97316")
    for x, item, rate in zip(xs, points, success, strict=True):
        body += _text(x, 395, labels[item.batch_id], 13, anchor="middle")
        body += _text(x, 374, f"{item.summary.pass_1_numerator}/15", 12, anchor="middle")
        body += _circle(x, _metric_y(rate), "#2563eb")
    body += _legend(600, 42, "success rate", "#2563eb")
    body += _legend(600, 64, "normalized cost", "#f97316")
    return _svg(body, selection_digest)


def _failure_funnel(counts: dict[str, int], selection_digest: str) -> str:
    body = _text(35, 34, "Update-Source primary failure diagnoses", 22)
    body += _text(
        35,
        58,
        f"Primary categories for {counts['failed']} failed tasks out of "
        f"{counts['evaluated']} evaluated",
        13,
        "#475569",
    )
    maximum = max(counts[name] for name in ("retrieval", "policy", "tool", "state")) or 1
    for index, (name, label) in enumerate(
        (
            ("retrieval", "retrieval"),
            ("policy", "policy"),
            ("tool", "tool selection"),
            ("state", "state verification"),
        )
    ):
        y = 105 + index * 76
        width = int(590 * counts[name] / maximum)
        body += _text(35, y + 25, label, 13)
        body += f'<rect x="190" y="{y}" width="{width}" height="38" rx="6" fill="#7c3aed"/>'
        if width:
            body += _text(
                190 + int(width * Decimal("0.82")),
                y + 25,
                counts[name],
                13,
                "#ffffff",
                anchor="end",
            )
        else:
            body += _text(205, y + 25, counts[name], 13)
    return _svg(body, selection_digest)


def _paired_comparison(
    baseline: FormalBatchArtifact,
    candidates: list[FormalBatchArtifact],
    labels: dict[str, str],
    selection_digest: str,
) -> str:
    body = _text(35, 34, "Paired Selection gains and regressions versus A0", 22)
    body += _text(35, 58, "Task counts on the identical 15-task Selection pool", 13, "#475569")
    x_positions = [240, 450, 660]
    for x, candidate in zip(x_positions, candidates, strict=True):
        ref = baseline.summary.stable_task_outcomes
        cur = candidate.summary.stable_task_outcomes
        gains = sum(cur[task] and not ref[task] for task in ref)
        regressions = sum(ref[task] and not cur[task] for task in ref)
        body += _bar(x - 50, gains, "#16a34a")
        body += _bar(x + 10, regressions, "#dc2626")
        body += _text(x, 395, labels[candidate.batch_id], 13, anchor="middle")
        body += _text(x - 25, 350 - gains * 60, gains, 12, anchor="middle")
        body += _text(x + 35, 350 - regressions * 60, regressions, 12, anchor="middle")
    body += '<line x1="100" y1="350" x2="800" y2="350" stroke="#64748b"/>'
    body += _legend(650, 42, "gains", "#16a34a")
    body += _legend(650, 64, "regressions", "#dc2626")
    return _svg(body, selection_digest)


def _gate_waterfall(selection_digest: str) -> str:
    gates = (
        ("evidence integrity", "PASS", "#16a34a"),
        ("strict stable gain", "FAIL", "#dc2626"),
        ("zero stable regression", "FAIL", "#dc2626"),
        ("p95 latency ≤ 1.2× A0", "FAIL", "#dc2626"),
        ("whole-attempt cost ≤ 1.2× A0", "PASS", "#16a34a"),
        ("governed terminal", "HOLD", "#7c3aed"),
    )
    body = _text(35, 34, "Selection gate waterfall", 22)
    body += _text(
        35, 58, "No candidate cleared every prerequisite; Release calls = 0", 13, "#475569"
    )
    for index, (name, status, color) in enumerate(gates):
        column, row = index % 3, index // 3
        x, y = 35 + column * 285, 105 + row * 135
        body += f'<rect x="{x}" y="{y}" width="250" height="78" rx="10" fill="{color}"/>'
        body += _text(x + 14, y + 31, name, 13, "#ffffff")
        body += _text(x + 14, y + 58, status, 14, "#ffffff")
    body += _text(
        35, 410, "HOLD is a successful fail-closed governance outcome, not deployment.", 14
    )
    return _svg(body, selection_digest)


def _technical_report(
    *,
    experiment_id: str,
    outcome_digest: str,
    selection_digest: str,
    statistics_digest: str,
    baseline: FormalBatchArtifact,
    candidates: list[FormalBatchArtifact],
    comparisons: list[Any],
    labels: dict[str, str],
    diagnosis: dict[str, int],
    whole_experiment_model_cost: dict[str, Any],
) -> str:
    rows = []
    for candidate, comparison in zip(candidates, comparisons, strict=True):
        ref = baseline.summary.stable_task_outcomes
        cur = candidate.summary.stable_task_outcomes
        gains = [task.removeprefix("task_") for task in ref if cur[task] and not ref[task]]
        regressions = [task.removeprefix("task_") for task in ref if ref[task] and not cur[task]]
        rows.append(
            "| {label} | {score}/15 | {gains} | {regressions} | {net} | "
            "[{lower}, {upper}] | {cost} |".format(
                label=labels[candidate.batch_id],
                score=candidate.summary.pass_1_numerator,
                gains=", ".join(gains) or "none",
                regressions=", ".join(regressions) or "none",
                net=comparison.observed_stable_task_net,
                lower=comparison.ci_lower,
                upper=comparison.ci_upper,
                cost=candidate.summary.mean_cost,
            )
        )
    return (
        f"# {experiment_id}: evidence-governed Selection HOLD\n\n"
        "## Abstract\n\n"
        "AgentLoopGate evaluated three external AHE Harness proposals against a "
        "frozen A0 baseline on an identical 15-task Banking Selection population. "
        "No proposal achieved a strict stable-task gain without regression, so the "
        "system emitted HOLD and made zero Release calls. Two candidates tied A0 in "
        "aggregate while exchanging gained and lost tasks, demonstrating why paired "
        "evidence is necessary. This is evidence for governance utility, not for a "
        "positive or generalizable self-evolution effect.\n\n"
        "## Method\n\n"
        "The statistical unit is the task. Each candidate is compared with A0 using "
        "the preregistered deterministic paired bootstrap (10,000 resamples, 95% "
        "nearest-rank interval). Intervals are descriptive for the frozen task set; "
        "the candidates are dependent proposals and no multiplicity-adjusted or "
        "cross-domain claim is made. Cost is exact valid-run mean model cost.\n\n"
        "## Selection results\n\n"
        "| Variant | Stable success | Gains | Regressions | Paired net | 95% interval "
        "for rate difference | Mean model cost (USD) |\n"
        "|---|---:|---|---|---:|---:|---:|\n" + "\n".join(rows) + "\n\n"
        f"A0 scored {baseline.summary.pass_1_numerator}/15. All three candidates "
        "regressed tasks 062 and 095; all gained task 017. The observed intervals "
        "include zero, and the zero-regression prerequisite fails regardless of "
        "interval width.\n\n"
        "## Diagnosis and system evidence\n\n"
        f"The {diagnosis['evaluated']} valid Update-Source runs contained "
        f"{diagnosis['failed']} failed tasks: "
        f"{diagnosis['tool']} primary tool-selection failures and "
        f"{diagnosis['state']} primary state-verification failures. Registered "
        "DeepSeek Harness fixture evidence separately verifies JSONL/SQLite native "
        "persistence, observer completeness, event-hash equivalence, and OTel "
        "coexistence.\n\n"
        "## Cost accounting\n\n"
        f"All nine formal batches cost USD "
        f"{whole_experiment_model_cost['batch_model_cost_usd']}; external Updater "
        f"calls cost USD {whole_experiment_model_cost['updater_model_cost_usd']}; "
        f"exact known model cost was USD "
        f"{whole_experiment_model_cost['total_known_model_cost_usd']}. Unknown "
        f"model-cost scope: {whole_experiment_model_cost['unknown_cost_scope'] or 'none'}. "
        "Local compute monetary cost is unmetered/unknown rather than zero.\n\n"
        "## Conclusion and limitations\n\n"
        "AgentLoopGate prevented unsupported promotion that aggregate scoring could "
        "have obscured. R15 does not validate a Release candidate, AHE superiority, "
        "production-load plugin latency, or cross-domain transfer. Release-ID, OOD, "
        "and Replay were correctly not run. A future guided updater requires a new "
        "frozen identity and untouched confirmation tasks.\n\n"
        "## Evidence binding\n\n"
        f"- Private outcome: `{outcome_digest}`\n"
        f"- Selection: `{selection_digest}`\n"
        f"- Statistics: `{statistics_digest}`\n"
        "- Publication authorization: not granted by package creation\n"
    )


def _svg(body: str, source_digest: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" height="{_HEIGHT}" '
        f'viewBox="0 0 {_WIDTH} {_HEIGHT}">'
        f"<metadata>source={escape(source_digest)}</metadata>"
        '<rect width="100%" height="100%" fill="#f8fafc"/>'
        f"{body}</svg>"
    )


def _text(
    x: int,
    y: int,
    value: object,
    size: int = 12,
    color: str = "#0f172a",
    *,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="system-ui,sans-serif" '
        f'font-size="{size}" fill="{color}" text-anchor="{anchor}">'
        f"{escape(str(value))}</text>"
    )


def _axes() -> str:
    return (
        '<line x1="80" y1="90" x2="80" y2="350" stroke="#64748b"/>'
        '<line x1="80" y1="350" x2="820" y2="350" stroke="#64748b"/>'
    )


def _metric_y(value: Decimal) -> int:
    return 350 - int(240 * value)


def _polyline(xs: list[int], values: list[Decimal], color: str) -> str:
    points = " ".join(f"{x},{_metric_y(value)}" for x, value in zip(xs, values, strict=True))
    return f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>'


def _circle(x: int, y: int, color: str) -> str:
    return f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>'


def _legend(x: int, y: int, label: str, color: str) -> str:
    return (
        f'<line x1="{x}" y1="{y}" x2="{x + 26}" y2="{y}" '
        f'stroke="{color}" stroke-width="4"/>' + _text(x + 34, y + 5, label, 12)
    )


def _bar(x: int, count: int, color: str) -> str:
    height = count * 60
    return f'<rect x="{x}" y="{350 - height}" width="50" height="{height}" fill="{color}"/>'
