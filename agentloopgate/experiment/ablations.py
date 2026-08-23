"""Deterministic, no-model ablations pre-registered for Banking R2."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from agentloopgate.contracts import (
    canonical_digest,
    canonical_json_bytes,
    computed_contract_digest,
    file_digest,
    load_contract,
    verify_contract_digest,
)
from agentloopgate.gates import GateAssessment, GateEngine
from agentloopgate.schemas import DecisionValue, Digest, GateName
from agentloopgate.schemas.models import StrictModel

from .ledger import CostStatus, ExperimentAttemptLedger
from .protocol import load_execution_protocol
from .study import BankingR2StudyPlan, load_study_plan


class IntegrityGateAblation(StrictModel):
    schema_version: Literal["1.0"]
    ablation_id: Literal["integrity_gate"]
    study_digest: Digest
    objective_digest: Digest
    fixture_digest: Digest
    synthetic_control: Literal[True]
    formal_decision: Literal[False]
    production_decision: DecisionValue
    production_failed_gate: GateName
    counterfactual_decision: DecisionValue
    unsupported_admission_prevented: bool
    artifact_digest: Digest

    @model_validator(mode="after")
    def result_is_the_pre_registered_contrast(self) -> IntegrityGateAblation:
        if self.production_failed_gate is not GateName.EVALUATION_INTEGRITY:
            raise ValueError("integrity ablation must fail at evaluation_integrity")
        expected = (
            self.production_decision is DecisionValue.HOLD
            and self.counterfactual_decision is DecisionValue.SHIP_RECOMMENDED
        )
        if self.unsupported_admission_prevented != expected:
            raise ValueError("integrity ablation contrast is inconsistent")
        return self


def run_integrity_gate_ablation(
    project_root: Path,
    *,
    study_path: Path,
    output_path: Path,
    protocol_path: Path | None = None,
) -> IntegrityGateAblation:
    root = project_root.resolve()
    study = load_study_plan(_under(root, study_path))
    ledger = None
    handle = None
    if protocol_path is not None:
        protocol = load_execution_protocol(_under(root, protocol_path))
        if study.protocol_digest != protocol.protocol_digest:
            raise ValueError("integrity ablation study and execution protocol differ")
        from .service import _code_revision

        revision = _code_revision(root)
        if revision is None:
            raise ValueError("integrity ablation requires a source revision")
        ledger = ExperimentAttemptLedger(root, study.experiment_id)
        handle = ledger.begin(
            operation="integrity_gate_ablation",
            protocol_digest=protocol.protocol_digest,
            study_digest=study.study_digest,
            source_revision=revision,
            command=[
                "agentloopgate",
                "experiment",
                "ablation-integrity",
                "--study",
                str(study_path),
                "--protocol",
                str(protocol_path),
                "--output",
                str(output_path),
            ],
            recovery_action="verify the immutable inputs and rerun the same no-model contrast",
        )
    try:
        artifact, destination = _execute_integrity_gate_ablation(
            root,
            study=study,
            output_path=output_path,
        )
        if ledger is not None and handle is not None:
            ledger.complete_no_model_operation(
                handle,
                exit_code=0,
                result_artifacts={"integrity_gate_ablation": file_digest(destination)},
                counters={"model_calls": 0, "synthetic_controls": 1},
            )
        return artifact
    except BaseException as exc:
        if ledger is not None and handle is not None:
            destination = _under(root, output_path)
            ledger.fail(
                handle,
                exc,
                cost_status=CostStatus.NOT_APPLICABLE,
                known_cost_usd=0,
                result_artifacts=(
                    {"integrity_gate_ablation": file_digest(destination)}
                    if destination.is_file()
                    else {}
                ),
                recovery_action=(
                    "preserve the failed attempt, repair only implementation code, "
                    "and rerun the same frozen no-model contrast"
                ),
            )
        raise


def _execute_integrity_gate_ablation(
    root: Path,
    *,
    study: BankingR2StudyPlan,
    output_path: Path,
) -> tuple[IntegrityGateAblation, Path]:
    contract = load_contract(root / "configs/objective_contract.yaml")
    verify_contract_digest(contract)
    base = {
        "schema_version": "1.0",
        "candidate_id": "C_ABLATION_INTEGRITY",
        "baseline_snapshot_id": "R2_A0",
        "evaluation_integrity_complete": False,
        "leakage_hits": 0,
        "mutates_trust_kernel": False,
        "risk_tier": "M",
        "release_critical_violations": 0,
        "id_stable_task_net": 1,
        "ood_stable_task_net": 0,
        "replay_stable_task_net": 0,
        "catastrophic_regressions": 0,
        "reliability_complete": True,
        "reliability_trials": contract.reliability.trials,
        "stable_success_required": contract.reliability.stable_success_required,
        "baseline_mean_cost": "1",
        "candidate_mean_cost": "1",
        "baseline_p50_latency_ms": "1",
        "candidate_p50_latency_ms": "1",
        "evidence_refs": {
            gate.value: f"ablation:integrity_gate:{gate.value}" for gate in GateName
        },
    }
    incomplete = GateAssessment.model_validate(base)
    complete = incomplete.model_copy(update={"evaluation_integrity_complete": True})
    gate = GateEngine(contract)
    production = gate.decide(incomplete, created_at=study.frozen_at)
    counterfactual = gate.decide(complete, created_at=study.frozen_at)
    payload = {
        "schema_version": "1.0",
        "ablation_id": "integrity_gate",
        "study_digest": study.study_digest,
        "objective_digest": computed_contract_digest(contract),
        "fixture_digest": canonical_digest(incomplete),
        "synthetic_control": True,
        "formal_decision": False,
        "production_decision": production.record.decision,
        "production_failed_gate": production.failed_gate,
        "counterfactual_decision": counterfactual.record.decision,
        "unsupported_admission_prevented": (
            production.record.decision is DecisionValue.HOLD
            and counterfactual.record.decision is DecisionValue.SHIP_RECOMMENDED
        ),
    }
    artifact = IntegrityGateAblation.model_validate(
        {**payload, "artifact_digest": canonical_digest(payload)}
    )
    destination = _under(root, output_path)
    encoded = canonical_json_bytes(artifact.model_dump(mode="json")) + b"\n"
    if destination.exists():
        try:
            existing = canonical_json_bytes(
                json.loads(destination.read_text(encoding="utf-8"))
            ) + b"\n"
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("existing ablation artifact is unreadable") from exc
        if existing != encoded:
            raise ValueError("existing ablation artifact conflicts with frozen result")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encoded)
    return artifact, destination


def run_plugin_coexistence_ablation(
    project_root: Path,
    *,
    study_path: Path,
    protocol_path: Path,
    output_path: Path,
) -> dict:
    """Run the no-model DSH coexistence benchmark under the R2 attempt ledger."""

    root = project_root.resolve()
    study = load_study_plan(_under(root, study_path))
    protocol = load_execution_protocol(_under(root, protocol_path))
    if study.protocol_digest != protocol.protocol_digest:
        raise ValueError("plugin ablation study and execution protocol differ")
    output = _under(root, output_path)
    package = root / "integrations/deepseek-harness"
    command = ["corepack", "pnpm", "run", "ablation:plugin"]
    from .service import _code_revision

    revision = _code_revision(root)
    if revision is None:
        raise ValueError("plugin ablation requires a content-addressed source revision")
    ledger = ExperimentAttemptLedger(root, study.experiment_id)
    handle = ledger.begin(
        operation="plugin_coexistence_overhead",
        protocol_digest=protocol.protocol_digest,
        study_digest=study.study_digest,
        source_revision=revision,
        command=command,
        recovery_action=(
            "inspect the immutable failure event and preserve any output before rerunning"
        ),
    )
    try:
        completed = subprocess.run(
            command,
            cwd=package,
            env={
                **os.environ,
                "AGENTLOOPGATE_ABLATION_OUTPUT": str(output),
                "AGENTLOOPGATE_ABLATION_STUDY": str(
                    _under(root, study_path)
                ),
                "AGENTLOOPGATE_ABLATION_PROTOCOL_DIGEST": protocol.protocol_digest,
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "no process output").strip()
            raise PluginAblationProcessError(completed.returncode, message[-2000:])
        try:
            raw = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("plugin ablation did not produce readable JSON evidence") from exc
        claimed = raw.get("artifact_digest")
        if not isinstance(claimed, str):
            raise ValueError("plugin ablation artifact digest is missing")
        digest_payload = {
            key: value for key, value in raw.items() if key != "artifact_digest"
        }
        if canonical_digest(digest_payload) != claimed:
            raise ValueError("plugin ablation artifact digest mismatch")
        if raw.get("study_digest") != study.study_digest:
            raise ValueError("plugin ablation artifact is bound to a different study")
        if study.schema_version in {"1.1", "1.2"} and raw.get("protocol_digest") != (
            protocol.protocol_digest
        ):
            raise ValueError("plugin ablation artifact lacks the frozen protocol binding")
        ledger.complete_no_model_operation(
            handle,
            exit_code=completed.returncode,
            result_artifacts={"plugin_ablation": file_digest(output)},
            counters={
                "model_calls": 0,
                "jsonl_iterations": int(raw["results"]["jsonl"]["iterations"]),
                "sqlite_iterations": int(raw["results"]["sqlite"]["iterations"]),
            },
        )
        return raw
    except BaseException as exc:
        exit_code = exc.exit_code if isinstance(exc, PluginAblationProcessError) else None
        ledger.fail(
            handle,
            exc,
            exit_code=exit_code,
            cost_status=CostStatus.NOT_APPLICABLE,
            known_cost_usd=0,
            result_artifacts=(
                {"plugin_ablation": file_digest(output)} if output.is_file() else {}
            ),
            recovery_action=(
                "preserve the failed attempt, repair only implementation code, rerun the "
                "same frozen command, protocol, study, and output contract"
            ),
        )
        raise


class PluginAblationProcessError(RuntimeError):
    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(f"plugin ablation exited {exit_code}: {message}")
        self.exit_code = exit_code


def _under(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"ablation path escapes project root: {path}")
    return resolved
