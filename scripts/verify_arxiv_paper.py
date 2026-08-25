"""Verify that the arXiv manuscript stays bound to the sealed R15 evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"paper verification failed: {message}")


def _require_text(text: str, value: str, label: str) -> None:
    _require(value in text, f"missing {label}: {value}")


def _task_suffix(task_id: str) -> str:
    return task_id.removeprefix("task_")


def _paired_changes(
    baseline: dict[str, bool], candidate: dict[str, bool]
) -> tuple[list[str], list[str]]:
    gains = [
        _task_suffix(task_id)
        for task_id, baseline_success in baseline.items()
        if not baseline_success and candidate[task_id]
    ]
    regressions = [
        _task_suffix(task_id)
        for task_id, baseline_success in baseline.items()
        if baseline_success and not candidate[task_id]
    ]
    return gains, regressions


def verify(project: Path) -> None:
    paper_dir = project / "paper" / "agentloopgate-arxiv"
    tex_path = paper_dir / "main.tex"
    bib_path = paper_dir / "references.bib"
    package = project / "artifacts" / "research" / "banking_r15" / "release_v2"

    tex = tex_path.read_text(encoding="utf-8")
    tex_flat = " ".join(tex.split())
    bib = bib_path.read_text(encoding="utf-8")
    selection = _load_json(package / "selection.json")
    statistics = _load_json(package / "statistics.json")
    outcome = _load_json(package / "selection_hold_outcome.json")
    costs = _load_json(package / "cost_summary.json")
    failures = _load_json(package / "failure_accounting.json")
    manifest = _load_json(package / "manifest.json")
    reproduction = _load_json(package / "reproduction.json")
    plugin = _load_json(package / "ablations" / "plugin_coexistence_overhead.json")
    integrity = _load_json(package / "ablations" / "integrity_gate.json")

    _require(outcome["final_decision"] == "HOLD", "R15 decision is not HOLD")
    _require(outcome["model_calls_after_selection"] == 0, "post-Selection calls exist")
    _require(outcome["release_batch_count"] == 0, "Release batches exist")
    _require(outcome["agentloopgate_candidate_id"] is None, "candidate was governed")
    _require(outcome["unknown_cost_scope"] == [], "unknown model-cost scope exists")
    _require(manifest["publication_authorized"] is False, "package says publication")
    _require(manifest["final_decision"] == "HOLD", "manifest decision is not HOLD")
    _require(costs["all_batches_exact"] is True, "batch cost is not exact")
    _require(costs["batch_count"] == 9, "unexpected batch count")

    bound_values = {
        "experiment identity": outcome["experiment_id"].replace("_", r"\_"),
        "protocol digest": outcome["protocol_digest"],
        "study digest": outcome["study_digest"],
        "source revision": outcome["source_revision"],
        "Selection digest": outcome["selection_digest"],
        "statistics digest": statistics["statistics_digest"],
        "Outcome digest": outcome["outcome_digest"],
        "manifest digest": manifest["manifest_digest"],
        "decision reason": outcome["decision_reason"],
    }
    for label, value in bound_values.items():
        _require_text(tex, value, label)

    whole_cost = costs["whole_experiment_model_cost"]
    _require(
        whole_cost["total_known_model_cost_usd"]
        == outcome["total_known_model_cost_usd"],
        "total cost artifacts disagree",
    )
    _require(
        whole_cost["updater_model_cost_usd"] == outcome["updater_model_cost_usd"],
        "updater cost artifacts disagree",
    )
    for value, label in (
        ("3.8830976464", "formal batch cost"),
        ("0.0255671416", "updater cost"),
        ("3.9086647880", "known total model cost"),
    ):
        _require_text(tex, value, label)

    usage = failures["model_usage"]
    expected_usage = {
        "4,378": usage["call_count"],
        "10,343,844": usage["input_tokens"],
        "4,648,289": usage["output_tokens"],
        "222,019,328": usage["cache_read_tokens"],
    }
    for formatted, value in expected_usage.items():
        _require(int(formatted.replace(",", "")) == value, "usage fixture drifted")
        _require_text(tex, formatted, "model-usage value")
    _require(usage["provider_retry_count"] == 0, "provider retries are nonzero")
    _require(usage["unresolved_call_count"] == 0, "unresolved calls are nonzero")

    baseline = selection["baseline"]
    _require(baseline["stable_success_task_count"] == 6, "baseline score drifted")
    _require_text(tex, "$A_0$ & 6/15", "baseline Selection row")
    candidate_rows = (
        ("C1", selection["inputs"][0], "017, 096", "062, 095"),
        ("C2", selection["inputs"][1], "017, 090", "056, 062, 095"),
        ("C3", selection["inputs"][2], "017, 090", "062, 095"),
    )
    baseline_outcomes = baseline["stable_task_outcomes"]
    for label, candidate, gain_text, regression_text in candidate_rows:
        gains, regressions = _paired_changes(
            baseline_outcomes, candidate["stable_task_outcomes"]
        )
        _require(", ".join(gains) == gain_text, f"{label} gain set drifted")
        _require(", ".join(regressions) == regression_text, f"{label} regressions drifted")
        score = candidate["stable_success_task_count"]
        _require_text(tex, f"{label} & {score}/15", f"{label} Selection row")
        _require_text(tex, gain_text, f"{label} gain set")
        _require_text(tex, regression_text, f"{label} regression set")

    _require(statistics["bootstrap_resamples"] == 10_000, "bootstrap count drifted")
    _require(statistics["statistical_unit"] == "task", "statistical unit drifted")
    _require(statistics["comparison_count"] == 3, "comparison count drifted")
    for comparison in statistics["comparisons"]:
        lower = float(comparison["ci_lower"])
        upper = float(comparison["ci_upper"])
        _require(lower <= 0 <= upper, "paper claim that all intervals include zero drifted")

    _require(plugin["formal_decision"] is False, "plugin fixture became formal")
    _require(plugin["additional_model_calls"] is False, "plugin fixture called a model")
    for backend, p50, p95 in (
        ("jsonl", "-0.308", "16.424"),
        ("sqlite", "0.244", "0.542"),
    ):
        result = plugin["results"][backend]
        _require(result["iterations"] == 30, f"{backend} iteration count drifted")
        _require(result["eventCount"] == 100, f"{backend} event count drifted")
        for key in (
            "observerComplete",
            "otelCoexistence",
            "persistenceSurvival",
            "sessionEventHashEquivalent",
        ):
            _require(result[key] is True, f"{backend} {key} is false")
        _require_text(tex, p50, f"{backend} p50 overhead")
        _require_text(tex, p95, f"{backend} p95 overhead")

    _require(integrity["synthetic_control"] is True, "integrity control not synthetic")
    _require(integrity["formal_decision"] is False, "integrity control became formal")
    _require(integrity["production_decision"] == "HOLD", "integrity gate drifted")
    _require(
        integrity["counterfactual_decision"] == "SHIP_RECOMMENDED",
        "integrity counterfactual drifted",
    )

    _require(
        reproduction["execution_protocol"]["digest"] == outcome["protocol_digest"],
        "reproduction protocol does not bind Outcome",
    )
    _require(
        reproduction["study"]["digest"] == outcome["study_digest"],
        "reproduction study does not bind Outcome",
    )
    _require(len(manifest["files"]) + 1 == 18, "R15 package is no longer 18 files")

    cite_keys = {
        key.strip()
        for group in re.findall(r"\\cite\{([^}]+)\}", tex)
        for key in group.split(",")
    }
    bib_keys = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bib))
    missing_citations = sorted(cite_keys - bib_keys)
    _require(not missing_citations, f"undefined citations: {missing_citations}")
    _require(len(cite_keys) >= 13, "related-work coverage unexpectedly shrank")

    _require_text(tex_flat, "No positive self-evolution effect is claimed", "claim limit")
    _require_text(tex_flat, "Release was not run", "Release claim limit")
    _require_text(tex_flat, "promotion is never automatic", "promotion claim limit")
    _require(not re.search(r"sk-[A-Za-z0-9]{12,}", tex + bib), "secret-like token")

    figures = (
        paper_dir / "figures" / "paired-comparison.pdf",
        paper_dir / "figures" / "gate-waterfall.pdf",
    )
    for figure in figures:
        _require(figure.is_file() and figure.stat().st_size > 0, f"missing {figure.name}")

    print(
        "AgentLoopGate paper facts verified against sealed R15 Selection, cost, "
        "failure, ablation, reproduction, and manifest artifacts."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="AgentLoopGate repository root",
    )
    args = parser.parse_args()
    verify(args.project.resolve())


if __name__ == "__main__":
    main()
