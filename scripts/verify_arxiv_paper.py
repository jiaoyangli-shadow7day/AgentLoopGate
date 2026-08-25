"""Verify that the arXiv manuscript stays bound to P0--R15 evidence."""

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
    citation = (project / "CITATION.cff").read_text(encoding="utf-8")

    p0_config = (project / "configs" / "formal_experiment.yaml").read_text(
        encoding="utf-8"
    )
    r2_adr = (
        project
        / "docs"
        / "adr"
        / "0002-version-formal-execution-protocol-for-banking-r2.md"
    ).read_text(encoding="utf-8")
    spec = (project / "SPEC.md").read_text(encoding="utf-8")
    r11_record = (
        project / "docs" / "research" / "banking-r11-preregistration.md"
    ).read_text(encoding="utf-8")
    history = project / "artifacts" / "research"
    r5 = _load_json(history / "banking_r5" / "execution_diagnosis.json")
    r6 = _load_json(history / "banking_r6" / "execution_diagnosis.json")
    r7 = _load_json(history / "banking_r7" / "execution_diagnosis.json")
    r8 = _load_json(history / "banking_r8" / "cost_incident_diagnosis.json")
    r9 = _load_json(history / "banking_r9" / "experiment_hold.json")
    r10 = _load_json(history / "banking_r10" / "selection_design_correction.json")
    r12 = _load_json(history / "banking_r12" / "formal_execution_seal.json")
    r13 = _load_json(history / "banking_r13" / "formal_execution_seal.json")
    r14 = _load_json(history / "banking_r14" / "formal_execution_seal.json")

    selection = _load_json(package / "selection.json")
    statistics = _load_json(package / "statistics.json")
    outcome = _load_json(package / "selection_hold_outcome.json")
    costs = _load_json(package / "cost_summary.json")
    failures = _load_json(package / "failure_accounting.json")
    manifest = _load_json(package / "manifest.json")
    reproduction = _load_json(package / "reproduction.json")
    plugin = _load_json(package / "ablations" / "plugin_coexistence_overhead.json")
    integrity = _load_json(package / "ablations" / "integrity_gate.json")

    _require_text(tex, r"\author{JiaoyangLi\\", "author name")
    _require_text(tex, "mailto:jiaoyanglifly@gmail.com", "author email link")
    _require_text(tex, "{jiaoyanglifly@gmail.com}", "visible author email")
    _require("AgentLoopGate Contributors" not in tex, "placeholder author remains")
    _require_text(citation, 'name: "JiaoyangLi"', "software citation author")
    _require_text(
        citation,
        'email: "jiaoyanglifly@gmail.com"',
        "software citation email",
    )
    _require(
        "AgentLoopGate Contributors" not in citation,
        "software citation placeholder author remains",
    )

    _require_text(p0_config, 'experiment_id: "EXP_BANKING_P0"', "P0 config identity")
    _require_text(r2_adr, "Supersedes for release claims: `EXP_BANKING_P0`", "P0 supersession")
    _require_text(tex, r"\code{EXP\_BANKING\_P0}", "P0 history identity")
    _require_text(
        tex_flat,
        r"no registered \code{EXP\_BANKING\_R1} identity exists",
        "R1 naming gap",
    )
    _require_text(
        tex_flat,
        "P0--R14 support a systems claim, not a positive evolution claim",
        "history claim boundary",
    )

    _require_text(spec, "25 个任务位置中 22 个有效", "R3 source count")
    _require_text(spec, "25 个任务位置中 24 个有效", "R4 source count")
    _require_text(spec, "0.69178802080000000240", "R4 exact cost")
    _require_text(tex, "R3 & 22/25 valid", "R3 history row")
    _require_text(tex, "R4 & 24/25 valid", "R4 history row")
    _require_text(tex, "USD~0.6917880208", "R4 history cost")

    _require(r5["formal_summary"]["valid_runs"] == 23, "R5 valid count drifted")
    _require(r6["formal_summary"]["valid_runs"] == 24, "R6 valid count drifted")
    _require(
        r6["cost_accounting"]["observed_total_model_cost_usd"].startswith(
            "0.7698343648"
        ),
        "R6 cost drifted",
    )
    _require_text(tex, "R5: 23/25 valid; R6: 24/25 valid", "R5--R6 history counts")
    _require_text(tex, "USD~0.7698343648", "R6 history cost")

    _require(r7["formal_summary"]["valid_runs"] == 25, "R7 Source count drifted")
    _require(
        r8["incident_class"] == "false_exact_zero_user_model_cost",
        "R8 cost incident drifted",
    )
    _require(r8["observation"]["user_terminal_calls"] == 13, "R8 User calls drifted")
    _require_text(tex, "false exact-zero User cost", "R8 cost failure")
    _require_text(spec, "R8 在任何付费 Batch 开始前", "R8 zero-paid boundary")
    _require_text(tex, "R8 made zero paid calls", "R8 zero-paid history")

    _require(r9["status"] == "HOLD", "R9 status drifted")
    _require(r9["completed_stage"]["valid_runs"] == 25, "R9 Source count drifted")
    _require(
        r9["completed_stage"]["whole_attempt_total_cost_usd"].startswith(
            "0.7015112488"
        ),
        "R9 cost drifted",
    )
    _require_text(tex, "USD~0.7015112488", "R9 history cost")

    _require(r10["completed_formal_task_positions"] == 95, "R10 position count drifted")
    _require(
        r10["cost_accounting"]["formal_model_cost_through_c2"] == "3.0651904832",
        "R10 cost drifted",
    )
    _require(r10["disposition"] == "paid_hold", "R10 disposition drifted")
    _require_text(tex, "R10 & 95 formal positions", "R10 history positions")
    _require_text(tex, "USD~3.0651904832", "R10 history cost")

    _require_text(r11_record, "24 valid runs and one Infra Invalid", "R11 terminal count")
    _require_text(tex, "R11: 24/25 Source valid", "R11 history count")

    _require(r12["terminal_state"] == "immutable_hold", "R12 state drifted")
    _require(r12["execution_scope"]["executed_formal_positions"] == 35, "R12 positions drifted")
    _require(r12["execution_scope"]["valid_formal_positions"] == 34, "R12 valid count drifted")
    _require(
        r12["aggregate_cost"]["total_observed_provider_cost_lower_bound"]
        == "1.1970712488",
        "R12 cost drifted",
    )
    _require_text(tex, "R12: 34/35 executed positions valid", "R12 history count")
    _require_text(tex, "USD~1.1970712488", "R12 history cost")

    r13_waste = r13["fail_fast_finding"]
    _require(
        r13_waste["positions_executed_after_terminal_infra_failure"] == 12,
        "R13 tail positions drifted",
    )
    _require(
        r13_waste["terminal_model_calls_after_terminal_infra_failure"] == 588,
        "R13 tail calls drifted",
    )
    _require(
        r13_waste["exact_known_cost_usd_after_terminal_infra_failure"]
        == "0.4686327800",
        "R13 tail cost drifted",
    )
    _require_text(tex, "12 queued positions", "R13 history tail positions")
    _require_text(tex, "588 calls", "R13 history tail calls")
    _require_text(tex, "USD~0.4686327800", "R13 history tail cost")

    _require(
        r14["execution_scope"]["executed_formal_positions"] == 46,
        "R14 position count drifted",
    )
    _require(
        r14["aggregate_cost"]["total_exact_known_model_cost_usd"].startswith(
            "1.4876297096"
        ),
        "R14 total cost drifted",
    )
    _require(
        r14["terminal_incident"]["authorized_positions_not_started_after_trigger"]
        == 79,
        "R14 prevented positions drifted",
    )
    _require(
        r14["terminal_incident"]["model_calls_after_trigger"] == 0,
        "R14 post-trigger calls exist",
    )
    _require_text(tex, "R14 & 46/125 positions executed", "R14 history positions")
    _require_text(tex, "USD~1.4876297096", "R14 history cost")
    _require_text(tex, "prevented 79 authorized positions", "R14 fail-fast result")

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
        "AgentLoopGate paper facts verified against P0--R14 formation evidence "
        "and sealed R15 Selection, cost, failure, ablation, reproduction, and "
        "manifest artifacts."
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
