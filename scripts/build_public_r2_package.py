#!/usr/bin/env python3
"""Build a fail-closed, sanitized public package from a verified formal outcome.

The filename is retained as a compatibility entry point. The implementation is
configuration-driven and supports the next corrected experiment identity, not
only historical Banking R2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from agentloopgate.adapters.dsh_tau3 import load_pilot_pricing
from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.experiment.ledger import (
    ExperimentAttemptEvent,
    ExperimentAttemptLedger,
    FormalCostAccounting,
    _verify_event,
)
from agentloopgate.experiment.orchestrator import (
    FormalExperimentOrchestrator,
    FormalSelectionHoldOutcome,
)
from agentloopgate.experiment.service import load_execution_protocol, load_formal_config
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    ModelCallUsageEvent,
    verify_model_call_event,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_public_tree import (  # noqa: E402
    PII_RULES,
    SECRET_RULES,
    unapproved_email_matches,
)
from build_selection_hold_supplement import (  # noqa: E402
    build_selection_hold_supplement,
)

# Legacy defaults retain the historical R2 command line, while every runtime
# path is derived from the verified freeze and formal config.
EXPERIMENT_ID = "EXP_BANKING_R2"
PRIVATE_ROOT = Path("runs/experiments") / EXPERIMENT_ID
DEFAULT_CONFIG = Path("configs/formal_experiment_r2_a4.yaml")
DEFAULT_FREEZE = PRIVATE_ROOT / "freeze_manifest_a4.json"
DEFAULT_OUTPUT = Path("artifacts/research/banking_r2/release")
REPORT_NAMES = (
    "decision.json",
    "decision.md",
    "01_candidate_curve.svg",
    "02_failure_funnel.svg",
    "03_pool_comparison.svg",
    "04_gate_waterfall.svg",
)


def _ablation_paths(root: Path, research_root: Path, freeze: dict[str, Any]) -> dict[str, Path]:
    paths = {
        "selector": research_root / "ablations/selector_v2.json",
        "diagnosis_direction": research_root / "ablations/diagnosis_direction_v2.json",
        "integrity_gate": research_root / "ablations/integrity_gate.json",
        "plugin_coexistence_overhead": research_root / "ablations/plugin_coexistence_overhead.json",
    }
    registered = freeze.get("pre_core_ablations")
    if registered is None:
        return paths
    if not isinstance(registered, dict):
        raise PublicPackageBlocked("freeze pre-core ablation register is invalid")
    for public_name, register_name in {
        "integrity_gate": "evidence_integrity_gate",
        "plugin_coexistence_overhead": "plugin_trace_coexistence_and_overhead",
    }.items():
        record = registered.get(register_name)
        if record is None:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise PublicPackageBlocked(f"freeze pre-core ablation path is invalid: {register_name}")
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise PublicPackageBlocked(
                f"freeze pre-core ablation path escapes project: {register_name}"
            )
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise PublicPackageBlocked(
                f"freeze pre-core ablation path escapes project: {register_name}"
            )
        paths[public_name] = resolved
    return paths


class PublicPackageBlocked(RuntimeError):
    """Required terminal private evidence is missing or incomplete."""


class PublicPackageConflict(RuntimeError):
    """An existing public package conflicts with the verified derived bytes."""


class SensitiveContentError(RuntimeError):
    """A derived public payload contains a forbidden Secret or direct-PII pattern."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicPackageBlocked(f"required JSON evidence is unavailable: {path.name}") from exc
    if not isinstance(value, dict):
        raise PublicPackageBlocked(f"required JSON evidence is not an object: {path.name}")
    return value


def _verify_digest(value: dict[str, Any], field: str, *, expected: str | None = None) -> str:
    digest = value.get(field)
    if not isinstance(digest, str):
        raise PublicPackageBlocked(f"evidence has no {field}")
    payload = dict(value)
    payload.pop(field)
    if canonical_digest(payload) != digest:
        raise PublicPackageBlocked(f"evidence {field} does not verify")
    if expected is not None and digest != expected:
        raise PublicPackageBlocked(f"evidence {field} conflicts with sealed outcome")
    return digest


def _load_freeze(path: Path) -> dict[str, Any]:
    freeze = _load_json(path)
    _verify_digest(freeze, "freeze_manifest_digest")
    if not isinstance(freeze.get("experiment_id"), str) or not freeze["experiment_id"]:
        raise PublicPackageBlocked("freeze manifest has no experiment identity")
    return freeze


def _terminal_outcome(
    root: Path, config: Path, *, experiment_id: str, private_root: Path
) -> tuple[str, Any]:
    outcome_path = root / private_root / "outcome.json"
    hold_path = root / private_root / "selection_hold_outcome.json"
    if outcome_path.is_file() and hold_path.is_file():
        raise PublicPackageBlocked("multiple incompatible terminal outcomes exist")
    if not outcome_path.is_file() and not hold_path.is_file():
        raise PublicPackageBlocked(
            "verified terminal formal outcome is unavailable; credentialed core has not completed"
        )
    formal_config = load_formal_config(config)
    if formal_config.experiment_id != experiment_id:
        raise PublicPackageBlocked("formal config conflicts with freeze experiment identity")
    # Deep verification uses the orchestrator's no-execute adapter. Historical
    # batches may include a separate user-simulator usage ledger even though
    # that adapter has no runtime path provider. Bind the immutable standard
    # path here so cost recomputation includes both channels without changing
    # the frozen execution-source tree.
    import agentloopgate.experiment.orchestrator as orchestrator_module

    no_execute = orchestrator_module._NoExecute  # noqa: SLF001
    protocol = (
        load_execution_protocol(root / formal_config.execution_protocol_config)
        if formal_config.execution_protocol_config is not None
        else None
    )
    enhanced_cost_lineage = bool(
        protocol is not None
        and protocol.schema_version in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9", "2.0"}
    )
    no_execute.cost_gate_scope = "valid_runs" if enhanced_cost_lineage else "whole_attempt"
    no_execute.direct_cost_lineage = bool(
        enhanced_cost_lineage
        and protocol is not None
        and protocol.global_task_attempt_limit is not None
    )
    if not hasattr(no_execute, "user_model_usage_path"):

        def _user_model_usage_path(_self: object, spec: Any) -> Path:
            return root / private_root / "user_model_usage" / f"{spec.batch_id}.jsonl"

        no_execute.user_model_usage_path = _user_model_usage_path
    if not hasattr(no_execute, "task_attempt_path"):

        def _task_attempt_path(_self: object, spec: Any) -> Path:
            return root / private_root / "task_attempts" / f"{spec.batch_id}.jsonl"

        no_execute.task_attempt_path = _task_attempt_path
    pricing = load_pilot_pricing(root / formal_config.pricing_config)

    def _frozen_token_prices(_self: object) -> tuple[Decimal, Decimal, Decimal]:
        return (
            pricing.input_cache_miss,
            pricing.input_cache_hit,
            pricing.output,
        )

    no_execute.frozen_token_prices = _frozen_token_prices
    orchestrator = FormalExperimentOrchestrator(root, config_path=config)
    # The public method would start paid work when outcome.json is absent. The
    # existence guard above makes this private verifier a strictly no-model path.
    if outcome_path.is_file():
        return "formal_outcome", orchestrator._load_verified_outcome(outcome_path)  # noqa: SLF001
    return "selection_hold", orchestrator._load_verified_selection_hold(hold_path)  # noqa: SLF001


def _outcome_seal_time(private_root: Path, *, terminal_kind: str = "formal_outcome") -> datetime:
    operation = (
        "seal_selection_hold_outcome"
        if terminal_kind == "selection_hold"
        else "seal_formal_outcome"
    )
    terminals: list[ExperimentAttemptEvent] = []
    ledger_root = private_root / "attempt_ledger"
    for path in sorted(ledger_root.glob("ATT_*/*.json")):
        event = ExperimentAttemptEvent.model_validate_json(path.read_text(encoding="utf-8"))
        _verify_event(event)
        if event.operation == operation and event.state is AttemptState.COMPLETED:
            terminals.append(event)
    if len(terminals) != 1:
        raise PublicPackageBlocked(f"exactly one completed {terminal_kind} seal is required")
    return terminals[0].recorded_at


def _attempt_accounting(private_root: Path, *, cutoff: datetime) -> dict[str, Any]:
    groups: dict[str, list[ExperimentAttemptEvent]] = defaultdict(list)
    for path in sorted((private_root / "attempt_ledger").glob("ATT_*/*.json")):
        event = ExperimentAttemptEvent.model_validate_json(path.read_text(encoding="utf-8"))
        _verify_event(event)
        if event.recorded_at <= cutoff:
            groups[event.attempt_id].append(event)
    terminal_counts: Counter[str] = Counter()
    cost_counts: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    total_duration_ms = 0
    resumed_count = 0
    for attempt_id, events in sorted(groups.items()):
        events.sort(key=lambda item: item.recorded_at)
        if len(events) != 2 or events[0].state is not AttemptState.STARTED:
            raise PublicPackageBlocked(
                f"Attempt lifecycle is unresolved before outcome: {attempt_id}"
            )
        terminal = events[1]
        if terminal.state not in {AttemptState.COMPLETED, AttemptState.FAILED}:
            raise PublicPackageBlocked(f"Attempt has no terminal state: {attempt_id}")
        if terminal.cost_status is CostStatus.PENDING:
            raise PublicPackageBlocked(f"Attempt terminal cost is pending: {attempt_id}")
        terminal_counts[terminal.state.value] += 1
        cost_counts[terminal.cost_status.value] += 1
        total_duration_ms += terminal.duration_ms or 0
        resumed_count += int(terminal.resumed)
        if terminal.state is AttemptState.FAILED:
            failures.append(
                {
                    "attempt_id": attempt_id,
                    "operation": terminal.operation,
                    "stage": terminal.stage,
                    "batch_id": terminal.batch_id,
                    "snapshot_id": terminal.snapshot_id,
                    "candidate_id": terminal.candidate_id,
                    "duration_ms": terminal.duration_ms,
                    "exit_code": terminal.exit_code,
                    "cost_status": terminal.cost_status.value,
                    "known_cost_usd": (
                        format(terminal.known_cost_usd, "f")
                        if terminal.known_cost_usd is not None
                        else None
                    ),
                    "error_type": terminal.error_type,
                    "result_digests": sorted(terminal.result_artifacts.values()),
                }
            )
    return {
        "schema_version": "1.0",
        "evidence_cutoff": cutoff,
        "attempt_count": len(groups),
        "event_count": sum(len(events) for events in groups.values()),
        "terminal_state_counts": dict(sorted(terminal_counts.items())),
        "terminal_cost_status_counts": dict(sorted(cost_counts.items())),
        "failed_attempt_count": len(failures),
        "resumed_attempt_count": resumed_count,
        "summed_operation_duration_ms": total_duration_ms,
        "unresolved_attempt_count": 0,
        "failed_attempts": failures,
    }


def _model_usage_accounting(private_root: Path, *, cutoff: datetime) -> dict[str, Any]:
    groups: dict[str, list[ModelCallUsageEvent]] = defaultdict(list)
    for path in sorted((private_root / "model_usage").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = ModelCallUsageEvent.model_validate_json(line)
            verify_model_call_event(event)
            if event.recorded_at <= cutoff:
                groups[event.call_id].append(event)
    state_counts: Counter[str] = Counter()
    cost_counts: Counter[str] = Counter()
    input_tokens = cache_tokens = output_tokens = retries = duration_ms = 0
    exact_cost = Decimal(0)
    unresolved = 0
    for call_id, events in sorted(groups.items()):
        events.sort(key=lambda item: item.recorded_at)
        if not events or events[0].state is not AttemptState.STARTED:
            raise PublicPackageBlocked(f"model-call lifecycle has no STARTED event: {call_id}")
        if len(events) == 1:
            unresolved += 1
            continue
        if len(events) != 2 or events[1].state not in {
            AttemptState.COMPLETED,
            AttemptState.FAILED,
        }:
            raise PublicPackageBlocked(f"model-call lifecycle is inconsistent: {call_id}")
        terminal = events[1]
        state_counts[terminal.state.value] += 1
        cost_counts[terminal.cost_status.value] += 1
        input_tokens += terminal.input_tokens or 0
        cache_tokens += terminal.cache_read_tokens or 0
        output_tokens += terminal.output_tokens or 0
        retries += terminal.provider_retry_count or 0
        duration_ms += terminal.duration_ms or 0
        if terminal.cost_status is CostStatus.EXACT and terminal.cost_usd is not None:
            exact_cost += terminal.cost_usd
    return {
        "schema_version": "1.0",
        "call_count": len(groups),
        "terminal_state_counts": dict(sorted(state_counts.items())),
        "terminal_cost_status_counts": dict(sorted(cost_counts.items())),
        "unresolved_call_count": unresolved,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_tokens,
        "output_tokens": output_tokens,
        "provider_retry_count": retries,
        "summed_call_duration_ms": duration_ms,
        "exact_terminal_cost_usd": format(exact_cost, "f"),
    }


def _cost_accounting(private_root: Path) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    known_lower_bound = Decimal(0)
    all_exact = True
    for path in sorted((private_root / "costs").glob("B_*.json")):
        cost = FormalCostAccounting.model_validate_json(path.read_text(encoding="utf-8"))
        payload = cost.model_dump(mode="python", exclude={"cost_digest"})
        if canonical_digest(payload) != cost.cost_digest:
            raise PublicPackageBlocked(f"cost artifact digest mismatch: {cost.batch_id}")
        status_counts[cost.accounting_status.value] += 1
        all_exact &= cost.accounting_status is CostStatus.EXACT
        if cost.total_cost_lower_bound_usd is not None:
            known_lower_bound += cost.total_cost_lower_bound_usd
        batches.append(
            {
                "batch_id": cost.batch_id,
                "accounting_status": cost.accounting_status.value,
                "valid_run_count": cost.valid_run_count,
                "infra_invalid_count": cost.infra_invalid_count,
                "agent_model_call_count": cost.agent_model_call_count,
                "unresolved_agent_call_count": cost.unresolved_agent_call_count,
                "unretained_agent_call_count": cost.unretained_agent_call_count,
                "agent_provider_retry_count": cost.agent_provider_retry_count,
                "agent_input_tokens": cost.agent_input_tokens,
                "agent_cache_read_tokens": cost.agent_cache_read_tokens,
                "agent_output_tokens": cost.agent_output_tokens,
                "user_model_call_count_retained": cost.user_model_call_count_retained,
                "user_input_tokens_retained": cost.user_input_tokens_retained,
                "user_cache_read_tokens_retained": cost.user_cache_read_tokens_retained,
                "user_output_tokens_retained": cost.user_output_tokens_retained,
                "valid_agent_cost_usd": format(cost.valid_agent_cost_usd, "f"),
                "valid_user_cost_usd": _decimal(cost.valid_user_cost_usd),
                "infra_agent_cost_usd": _decimal(cost.infra_agent_cost_usd),
                "infra_user_cost_usd": _decimal(cost.infra_user_cost_usd),
                "observed_agent_attempt_cost_usd": _decimal(cost.observed_agent_attempt_cost_usd),
                "retained_user_cost_usd": _decimal(cost.retained_user_cost_usd),
                "total_cost_lower_bound_usd": _decimal(cost.total_cost_lower_bound_usd),
                "cost_digest": cost.cost_digest,
            }
        )
    if not batches:
        raise PublicPackageBlocked("formal batch cost artifacts are unavailable")
    return {
        "schema_version": "1.0",
        "currency": "USD",
        "batch_count": len(batches),
        "accounting_status_counts": dict(sorted(status_counts.items())),
        "all_batches_exact": all_exact,
        "known_total_lower_bound_usd": format(known_lower_bound, "f"),
        "exact_total_usd": format(known_lower_bound, "f") if all_exact else None,
        "local_compute_monetary_cost_status": "unmetered_unknown",
        "github_actions_compute_monetary_cost_status": "unavailable_unknown",
        "batches": batches,
    }


def _incident_summaries(private_root: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for path in sorted((private_root / "incidents").glob("*.json")):
        item = _load_json(path)
        summaries.append(
            {
                "incident_id": item.get("incident_id"),
                "recorded_at": item.get("recorded_at"),
                "operation": item.get("operation"),
                "affected_baseline_snapshot_id": item.get("affected_baseline_snapshot_id"),
                "affected_source_revision": item.get("affected_source_revision"),
                "conclusion": item.get("conclusion"),
                "failed_stage": item.get("failed_stage"),
                "error_type": item.get("error_type"),
                "cost_status": item.get("cost_status"),
                "github_actions_compute_cost_status": item.get(
                    "github_actions_compute_cost_status"
                ),
                "paid_core_started": item.get(
                    "paid_core_started", item.get("paid_r2_core_started")
                ),
                "source_file_sha256": file_digest(path),
            }
        )
    return summaries


def _canonical_artifact(path: Path, digest_field: str, expected: str | None = None) -> bytes:
    value = _load_json(path)
    _verify_digest(value, digest_field, expected=expected)
    return canonical_json_bytes(value) + b"\n"


def _collect_payloads(
    root: Path,
    *,
    experiment_id: str,
    private_root: Path,
    research_root: Path,
    outcome: Any,
    freeze: dict[str, Any],
    cutoff: datetime,
) -> tuple[dict[str, bytes], dict[str, str], dict[str, Any]]:
    private = root / private_root
    payloads: dict[str, bytes] = {}
    derivations: dict[str, str] = {}

    outcome_json = outcome.model_dump(mode="json")
    payloads["outcome.json"] = canonical_json_bytes(outcome_json) + b"\n"
    derivations["outcome.json"] = "canonical copy of deeply verified private outcome"

    role_path = private / "role_assignment.json"
    payloads["role_assignment.json"] = _canonical_artifact(
        role_path, "role_assignment_digest", outcome.role_assignment_digest
    )
    derivations["role_assignment.json"] = "verified registered role assignment"

    stats_path = private / "statistics.json"
    payloads["statistics.json"] = _canonical_artifact(
        stats_path, "statistics_digest", outcome.statistics_digest
    )
    derivations["statistics.json"] = "verified six-comparison publication statistics"

    for selector in ("native", "agentloopgate"):
        source = private / "decisions" / f"{selector}.json"
        target = f"decisions/{selector}.json"
        payloads[target] = _canonical_artifact(source, "decision_digest")
        derivations[target] = f"verified {selector} selector decision"

    expected_ablations = {
        "selector": outcome.selector_ablation_digest,
        "diagnosis_direction": outcome.diagnosis_ablation_digest,
        "integrity_gate": None,
        "plugin_coexistence_overhead": None,
    }
    for name, source in _ablation_paths(root, research_root, freeze).items():
        target = f"ablations/{name}.json"
        payloads[target] = _canonical_artifact(source, "artifact_digest", expected_ablations[name])
        derivations[target] = f"verified {name} registered ablation"

    lineage = _load_json(private / "lineage.json")
    lineage_digest = _verify_digest(lineage, "lineage_digest", expected=outcome.lineage_digest)
    lineage_summary = {
        "schema_version": "1.0",
        "experiment_id": lineage["experiment_id"],
        "pilot_evidence_join_count": len(lineage["pilot_evidence_join_ids"]),
        "batch_count": len(lineage["batch_ids"]),
        "candidate_count": len(lineage["candidate_ids"]),
        "snapshot_count": len(lineage["snapshot_ids"]),
        "private_lineage_digest": lineage_digest,
    }
    payloads["lineage_summary.json"] = canonical_json_bytes(lineage_summary) + b"\n"
    derivations["lineage_summary.json"] = (
        "aggregate counts and digest derived from verified private lineage"
    )

    reports = root / "reports" / experiment_id
    for name in REPORT_NAMES:
        source = reports / name
        expected = outcome.report_file_digests.get(source.relative_to(root).as_posix())
        if expected is None or not source.is_file() or file_digest(source) != expected:
            raise PublicPackageBlocked(f"sealed report file is unavailable or drifted: {name}")
        target = f"reports/{name}"
        payloads[target] = source.read_bytes()
        derivations[target] = "exact report bytes authenticated by private outcome"

    attempt_accounting = _attempt_accounting(private, cutoff=cutoff)
    model_usage = _model_usage_accounting(private, cutoff=cutoff)
    if model_usage["unresolved_call_count"] and outcome.final_decision.value != "HOLD":
        raise PublicPackageBlocked(
            "unresolved model calls require an explicit final HOLD before publication"
        )
    failure_accounting = {
        **attempt_accounting,
        "model_usage": model_usage,
        "operational_incidents": _incident_summaries(private),
    }
    payloads["failure_accounting.json"] = canonical_json_bytes(failure_accounting) + b"\n"
    derivations["failure_accounting.json"] = (
        "sanitized lifecycle aggregates and retained failure metadata through outcome seal"
    )

    cost_summary = _cost_accounting(private)
    payloads["cost_summary.json"] = canonical_json_bytes(cost_summary) + b"\n"
    derivations["cost_summary.json"] = (
        "verified per-batch cost evidence with explicit unknown infrastructure scopes"
    )

    reproduction = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "evaluation_baseline": freeze["evaluation_baseline"],
        "source_revision": freeze["source_revision"],
        "objective": freeze["objective"],
        "split": freeze["split"],
        "pricing": freeze["pricing"],
        "asset_manifest": freeze["asset_manifest"],
        "execution_protocol": freeze["execution_protocol"],
        "study": freeze["study"],
        "benchmark_runtime": freeze["benchmark_runtime"],
        "p0_immutability": freeze["p0_immutability"],
        "freeze_manifest_digest": freeze["freeze_manifest_digest"],
        "source_clean_room": freeze["remote_clean_room"],
        "exact_commands_document": "docs/research/reproducibility.md",
    }
    payloads["reproduction.json"] = canonical_json_bytes(reproduction) + b"\n"
    derivations["reproduction.json"] = "selected frozen identities and source CI evidence"

    readme = (
        "# AgentLoopGate Banking sanitized result package\n\n"
        "This directory is a derived public view of verified private evidence. "
        "It excludes raw model and host traces, prompts, tool payloads, credentials, "
        "direct identifiers, and non-redistributable task content.\n\n"
        f"- Experiment: `{experiment_id}`\n"
        f"- Final decision: `{outcome.final_decision.value}`\n"
        f"- Private outcome digest: `{outcome.outcome_digest}`\n"
        f"- Evidence cutoff: `{cutoff.isoformat().replace('+00:00', 'Z')}`\n"
        "- Manifest: `manifest.json`\n"
        "- Publication authorization: not granted by package creation\n\n"
        "Unknown cost remains unknown. `SHIP_RECOMMENDED` is not deployment.\n"
    )
    payloads["README.md"] = readme.encode("utf-8")
    derivations["README.md"] = "generated package scope and outcome binding"

    metadata = {
        "schema_version": "1.0",
        "package_kind": "sanitized_derived_view",
        "experiment_id": experiment_id,
        "created_at": cutoff,
        "private_outcome_digest": outcome.outcome_digest,
        "freeze_manifest_digest": freeze["freeze_manifest_digest"],
        "source_revision": freeze["source_revision"],
        "objective_digest": freeze["objective"]["digest"],
        "split_digest": freeze["split"]["digest"],
        "protocol_digest": freeze["execution_protocol"]["digest"],
        "study_digest": freeze["study"]["digest"],
        "baseline_snapshot_id": outcome.baseline_snapshot_id,
        "logical_core_trial_count": outcome.logical_core_trial_count,
        "unique_executed_core_trial_count": outcome.unique_executed_core_trial_count,
        "reused_role_trial_count": outcome.reused_role_trial_count,
        "native_decision": outcome.native_decision.value,
        "final_decision": outcome.final_decision.value,
        "lineage_digest": outcome.lineage_digest,
        "statistics_digest": outcome.statistics_digest,
        "report_digest": outcome.report_digest,
        "scientific_protocol_deviations": [],
        "operational_incident_count": len(failure_accounting["operational_incidents"]),
        "package_content_verification_status": "verified",
        "publication_authorized": False,
        "package_commit_ci_attestation": "external_required_after_commit",
    }
    return payloads, derivations, metadata


def _collect_selection_hold_payloads(
    root: Path,
    *,
    experiment_id: str,
    private_root: Path,
    research_root: Path,
    outcome: FormalSelectionHoldOutcome,
    freeze: dict[str, Any],
    cutoff: datetime,
) -> tuple[dict[str, bytes], dict[str, str], dict[str, Any]]:
    """Create the smaller public view for a valid pre-Release HOLD terminal."""
    private = root / private_root
    payloads: dict[str, bytes] = {}
    derivations: dict[str, str] = {}
    payloads["selection_hold_outcome.json"] = (
        canonical_json_bytes(outcome.model_dump(mode="json")) + b"\n"
    )
    derivations["selection_hold_outcome.json"] = "canonical verified Selection-HOLD outcome"

    selection = private / "selection.json"
    payloads["selection.json"] = _canonical_artifact(
        selection, "selection_digest", outcome.selection_digest
    )
    derivations["selection.json"] = "verified A0-bound Selection evidence"

    lineage = _load_json(private / "lineage.json")
    lineage_digest = _verify_digest(lineage, "lineage_digest", expected=outcome.lineage_digest)
    payloads["lineage_summary.json"] = (
        canonical_json_bytes(
            {
                "schema_version": "1.0",
                "experiment_id": lineage["experiment_id"],
                "batch_count": len(lineage["batch_ids"]),
                "candidate_count": len(lineage["candidate_ids"]),
                "snapshot_count": len(lineage["snapshot_ids"]),
                "private_lineage_digest": lineage_digest,
            }
        )
        + b"\n"
    )
    derivations["lineage_summary.json"] = "aggregate counts from verified private lineage"

    for name in ("integrity_gate", "plugin_coexistence_overhead"):
        source = _ablation_paths(root, research_root, freeze)[name]
        target = f"ablations/{name}.json"
        payloads[target] = _canonical_artifact(source, "artifact_digest")
        derivations[target] = f"verified {name} registered ablation"

    for relative, expected in outcome.report_file_digests.items():
        source = root / relative
        if not source.is_file() or file_digest(source) != expected:
            raise PublicPackageBlocked("sealed Selection-HOLD report is unavailable or drifted")
        target = f"reports/{source.name}"
        payloads[target] = source.read_bytes()
        derivations[target] = "exact Selection-HOLD report bytes authenticated by outcome"

    attempt_accounting = _attempt_accounting(private, cutoff=cutoff)
    model_usage = _model_usage_accounting(private, cutoff=cutoff)
    failure_accounting = {
        **attempt_accounting,
        "model_usage": model_usage,
        "operational_incidents": _incident_summaries(private),
    }
    payloads["failure_accounting.json"] = canonical_json_bytes(failure_accounting) + b"\n"
    derivations["failure_accounting.json"] = "sanitized lifecycle accounting through outcome seal"
    cost_summary = {
        **_cost_accounting(private),
        "whole_experiment_model_cost": {
            "status": outcome.cost_status,
            "batch_model_cost_usd": format(outcome.batch_model_cost_usd, "f"),
            "updater_model_cost_usd": format(outcome.updater_model_cost_usd, "f"),
            "total_known_model_cost_usd": format(outcome.total_known_model_cost_usd, "f"),
            "unresolved_updater_model_call_count": (outcome.unresolved_updater_model_call_count),
            "unknown_cost_scope": outcome.unknown_cost_scope,
        },
    }
    payloads["cost_summary.json"] = canonical_json_bytes(cost_summary) + b"\n"
    derivations["cost_summary.json"] = (
        "verified per-batch cost evidence with unknown scopes disclosed"
    )

    reproduction = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "evaluation_baseline": freeze["evaluation_baseline"],
        "source_revision": freeze["source_revision"],
        "objective": freeze["objective"],
        "split": freeze["split"],
        "pricing": freeze["pricing"],
        "asset_manifest": freeze["asset_manifest"],
        "execution_protocol": freeze["execution_protocol"],
        "study": freeze["study"],
        "benchmark_runtime": freeze["benchmark_runtime"],
        "p0_immutability": freeze["p0_immutability"],
        "freeze_manifest_digest": freeze["freeze_manifest_digest"],
    }
    payloads["reproduction.json"] = canonical_json_bytes(reproduction) + b"\n"
    derivations["reproduction.json"] = "selected frozen identities and source CI evidence"
    supplement, statistics_digest, supplement_digest = build_selection_hold_supplement(
        root,
        experiment_id=experiment_id,
        private_root=private_root,
        study_path=Path(freeze["study"]["path"]),
        selection_digest=outcome.selection_digest,
        outcome_digest=outcome.outcome_digest,
        whole_experiment_model_cost=cost_summary["whole_experiment_model_cost"],
    )
    payloads.update(supplement)
    derivations.update(
        {
            "statistics.json": (
                "preregistered paired Selection bootstrap over verified batch summaries"
            ),
            "reports/technical_report.md": (
                "deterministic terminal-HOLD technical report bound to public statistics"
            ),
            "reports/01_candidate_curve.svg": (
                "deterministic Selection reliability and normalized-cost chart"
            ),
            "reports/02_failure_funnel.svg": (
                "deterministic Update-Source primary-diagnosis chart"
            ),
            "reports/03_pool_comparison.svg": (
                "deterministic paired Selection gain/regression chart"
            ),
            "reports/04_gate_waterfall.svg": ("deterministic Selection-HOLD gate-waterfall chart"),
        }
    )
    payloads["README.md"] = (
        "# AgentLoopGate Banking Selection-HOLD sanitized result package\n\n"
        "This derived public view records a verified governance abstention. It does not "
        "include raw Trace, prompts, payloads, credentials, or task content.\n\n"
        f"- Experiment: `{experiment_id}`\n"
        f"- Final decision: `{outcome.final_decision.value}`\n"
        f"- Private outcome digest: `{outcome.outcome_digest}`\n"
        f"- Evidence cutoff: `{cutoff.isoformat().replace('+00:00', 'Z')}`\n"
        f"- Selection statistics digest: `{statistics_digest}`\n"
        "- Four terminal-HOLD figures: `reports/01_*.svg` through `04_*.svg`\n"
        "- Technical report: `reports/technical_report.md`\n"
        "- Publication authorization: not granted by package creation\n\n"
        "A HOLD is not a deployment and means no Release tail was executed.\n"
    ).encode()
    derivations["README.md"] = "generated package scope and Selection-HOLD binding"
    return (
        payloads,
        derivations,
        {
            "schema_version": "1.0",
            "package_kind": "sanitized_derived_view",
            "terminal_kind": "selection_hold",
            "experiment_id": experiment_id,
            "created_at": cutoff,
            "private_outcome_digest": outcome.outcome_digest,
            "freeze_manifest_digest": freeze["freeze_manifest_digest"],
            "source_revision": freeze["source_revision"],
            "baseline_snapshot_id": outcome.baseline_snapshot_id,
            "final_decision": outcome.final_decision.value,
            "lineage_digest": outcome.lineage_digest,
            "selection_digest": outcome.selection_digest,
            "report_digest": outcome.report_digest,
            "selection_hold_package_version": "1.1",
            "selection_hold_statistics_digest": statistics_digest,
            "selection_hold_supplement_digest": supplement_digest,
            "scientific_protocol_deviations": [],
            "operational_incident_count": len(failure_accounting["operational_incidents"]),
            "package_content_verification_status": "verified",
            "publication_authorized": False,
            "package_commit_ci_attestation": "external_required_after_commit",
        },
    )


def _scan_payloads(payloads: dict[str, bytes]) -> dict[str, Any]:
    findings: Counter[str] = Counter()
    for data in payloads.values():
        if b"\0" in data:
            findings["binary_payload"] += 1
            continue
        for name, pattern in SECRET_RULES.items():
            findings[name] += len(pattern.findall(data))
        for name, pattern in PII_RULES.items():
            matches = pattern.findall(data)
            if name == "email_address":
                matches = unapproved_email_matches(matches)
            findings[name] += len(matches)
    nonzero = {key: value for key, value in sorted(findings.items()) if value}
    if nonzero:
        raise SensitiveContentError(
            "derived package failed Secret/direct-PII scan: "
            + ", ".join(f"{key}={value}" for key, value in nonzero.items())
        )
    return {
        "status": "passed",
        "files_scanned": len(payloads),
        "secret_rule_count": len(SECRET_RULES),
        "pii_rule_count": len(PII_RULES),
        "finding_counts": {},
        "paths_and_values_withheld": True,
    }


def _media_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _payload_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _validate_relative(path: str) -> None:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or not path or ".." in parsed.parts:
        raise PublicPackageConflict(f"unsafe package path: {path}")


def _seal_payloads(
    output: Path,
    *,
    payloads: dict[str, bytes],
    derivations: dict[str, str],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    for path in payloads:
        _validate_relative(path)
    scan = _scan_payloads(payloads)
    files = [
        {
            "path": path,
            "sha256": _payload_digest(payloads[path]),
            "media_type": _media_type(path),
            "privacy_classification": "sanitized_aggregate",
            "derivation": derivations[path],
        }
        for path in sorted(payloads)
    ]
    manifest_payload = {**metadata, "files": files, "secret_pii_scan": scan}
    manifest = {
        **manifest_payload,
        "manifest_digest": canonical_digest(manifest_payload),
    }
    complete = {**payloads, "manifest.json": canonical_json_bytes(manifest) + b"\n"}

    if output.is_symlink():
        raise PublicPackageConflict("public package output cannot be a symlink")
    if output.exists():
        if not output.is_dir():
            raise PublicPackageConflict("public package output exists and is not a directory")
        existing = {
            path.relative_to(output).as_posix(): path.read_bytes()
            for path in sorted(output.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        if existing != complete:
            raise PublicPackageConflict(
                "existing public package conflicts with verified derived bytes"
            )
        return manifest, True

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="agentloopgate-public-result-", dir=output.parent) as raw:
        staged = Path(raw)
        for relative, data in complete.items():
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        staged_files = {
            path.relative_to(staged).as_posix(): path.read_bytes()
            for path in sorted(staged.rglob("*"))
            if path.is_file()
        }
        if staged_files != complete:
            raise PublicPackageConflict("staged public package verification failed")
        shutil.copytree(staged, output)
    return manifest, False


def build_public_release(
    root: Path,
    *,
    config: Path = DEFAULT_CONFIG,
    freeze_path: Path = DEFAULT_FREEZE,
    output: Path = DEFAULT_OUTPUT,
    command: list[str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    config = config if config.is_absolute() else (root / config)
    freeze_path = freeze_path if freeze_path.is_absolute() else (root / freeze_path)
    output = output if output.is_absolute() else (root / output)
    output = output.resolve()
    if not output.is_relative_to(root) or output in {root, root / "artifacts"}:
        raise PublicPackageConflict("public package output must be a narrow project subdirectory")

    freeze = _load_freeze(freeze_path)
    experiment_id = freeze["experiment_id"]
    private_root = Path("runs/experiments") / experiment_id
    ledger = ExperimentAttemptLedger(root, experiment_id)
    handle = ledger.begin(
        operation="build_sanitized_public_result_package",
        protocol_digest=freeze["execution_protocol"]["digest"],
        study_digest=freeze["study"]["digest"],
        source_revision=freeze["source_revision"],
        stage="publication_package",
        snapshot_id=freeze["evaluation_baseline"]["snapshot_id"],
        spec_digest=freeze["freeze_manifest_digest"],
        command=command or ["python", "scripts/build_public_result_package.py"],
    )
    try:
        terminal_kind, outcome = _terminal_outcome(
            root, config, experiment_id=experiment_id, private_root=private_root
        )
        formal_config = load_formal_config(config)
        configured_research_root_value = formal_config.research_artifact_root
        if configured_research_root_value is None:
            raise PublicPackageBlocked("formal config has no research artifact root")
        configured_research_root = Path(configured_research_root_value)
        research_root = (
            configured_research_root
            if configured_research_root.is_absolute()
            else root / configured_research_root
        ).resolve()
        if not research_root.is_relative_to(root):
            raise PublicPackageBlocked("research artifact root escapes project")
        cutoff = _outcome_seal_time(root / private_root, terminal_kind=terminal_kind)
        if terminal_kind == "selection_hold":
            payloads, derivations, metadata = _collect_selection_hold_payloads(
                root,
                experiment_id=experiment_id,
                private_root=private_root,
                research_root=research_root,
                outcome=outcome,
                freeze=freeze,
                cutoff=cutoff,
            )
        else:
            payloads, derivations, metadata = _collect_payloads(
                root,
                experiment_id=experiment_id,
                private_root=private_root,
                research_root=research_root,
                outcome=outcome,
                freeze=freeze,
                cutoff=cutoff,
            )
        manifest, reused = _seal_payloads(
            output,
            payloads=payloads,
            derivations=derivations,
            metadata=metadata,
        )
        result_paths = {
            path.relative_to(root).as_posix(): file_digest(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        terminal = ledger.complete_no_model_operation(
            handle,
            exit_code=0,
            result_artifacts=result_paths,
            counters={
                "public_file_count": len(result_paths),
                "model_calls": 0,
                "reused_existing_package": int(reused),
            },
        )
        return {
            "status": "completed",
            "attempt_id": terminal.attempt_id,
            "output": output.relative_to(root).as_posix(),
            "file_count": len(result_paths),
            "manifest_digest": manifest["manifest_digest"],
            "private_outcome_digest": outcome.outcome_digest,
            "reused": reused,
            "publication_authorized": False,
        }
    except BaseException as exc:
        terminal = ledger.fail(
            handle,
            exc,
            exit_code=4 if isinstance(exc, PublicPackageBlocked) else 5,
            recovery_action=(
                "Preserve this failed package Attempt. Complete and verify the frozen "
                "credentialed core or correct only conflicting derived/public bytes; "
                "never fabricate results, discard failures, or relax sanitization."
            ),
            cost_status=CostStatus.NOT_APPLICABLE,
            known_cost_usd=Decimal(0),
        )
        exc.attempt_id = terminal.attempt_id
        raise


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = build_public_release(
            args.project,
            config=args.config,
            freeze_path=args.freeze,
            output=args.output,
            command=sys.argv,
        )
    except (PublicPackageBlocked, PublicPackageConflict, SensitiveContentError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "attempt_id": getattr(exc, "attempt_id", None),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "model_calls": 0,
                    "known_model_cost_usd": "0",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 4 if isinstance(exc, PublicPackageBlocked) else 5
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
