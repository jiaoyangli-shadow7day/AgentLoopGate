"""Command-line entry point for AgentLoopGate."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from yaml import YAMLError

from agentloopgate import __version__
from agentloopgate.adapters import (
    TAU3_COMMIT,
    BenchmarkRunContext,
    BenchmarkRunRequest,
    BenchmarkUnavailableError,
    DshTau3Adapter,
    DshTau3PilotConfig,
    OutcomeImportError,
    load_pilot_pricing,
)
from agentloopgate.bridge import BridgeService, export_bridge_schema, serve_stream
from agentloopgate.candidates import CandidateRegistry, CandidateStateError
from agentloopgate.contracts import (
    canonical_digest,
    computed_contract_digest,
    freeze_contract,
    load_contract,
    verify_contract_digest,
)
from agentloopgate.demo import build_public_demo
from agentloopgate.evaluation.reset import ResetIntegrityError, ResetManager
from agentloopgate.experiment import (
    FormalBatchError,
    FormalExperimentOrchestrator,
    FormalExperimentService,
    FormalStage,
    FormalWorkflowBlocked,
    inspect_formal_preflight,
    load_execution_protocol,
    load_study_plan,
    run_integrity_gate_ablation,
    run_plugin_coexistence_ablation,
)
from agentloopgate.mutation import (
    CandidateChecker,
    freeze_trust_kernel,
    load_asset_manifest,
    load_mutation_policy,
)
from agentloopgate.runtime import bootstrap_deepseek_harness, inspect_deepseek_harness
from agentloopgate.schemas import CandidateStatus, DecisionRecord, Pool, RunRecord
from agentloopgate.snapshots import (
    PromotionApproval,
    SnapshotAuthorizationError,
    SnapshotIntegrityError,
    SnapshotManager,
)
from agentloopgate.splits import SplitIntegrityError, SplitService

app = typer.Typer(
    name="agentloopgate",
    help="Evidence-driven continuous improvement and release governance for agent harnesses.",
    no_args_is_help=True,
    invoke_without_command=True,
)
contract_app = typer.Typer(help="Validate and inspect the frozen Objective Contract.")
split_app = typer.Typer(help="Freeze and verify physically isolated evaluation pools.")
eval_app = typer.Typer(help="Audit evaluation integrity and deterministic reset behavior.")
bridge_app = typer.Typer(help="Serve and export the bounded DeepSeek Harness bridge protocol.")
pilot_app = typer.Typer(help="Run the DeepSeek Harness × τ³ banking validation slice.")
experiment_app = typer.Typer(help="Preflight and run the credentialed P0 experiment.")
snapshot_app = typer.Typer(help="Human-authorized snapshot promotion and rollback.")
app.add_typer(contract_app, name="contract")
app.add_typer(split_app, name="split")
app.add_typer(eval_app, name="eval")
app.add_typer(bridge_app, name="bridge")
app.add_typer(pilot_app, name="pilot")
app.add_typer(experiment_app, name="experiment")
app.add_typer(snapshot_app, name="snapshot")


def _emit(payload: dict[str, Any], *, as_json: bool, human: str) -> None:
    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        typer.echo(human)


def _fail(*, code: str, message: str, remediation: str, as_json: bool, exit_code: int) -> None:
    payload = {"code": code, "message": message, "remediation": remediation}
    _emit(payload, as_json=as_json, human=f"{code}: {message}\nRemediation: {remediation}")
    raise typer.Exit(code=exit_code)


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the installed AgentLoopGate version and exit.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
    runtime: Annotated[
        str | None,
        typer.Option("--runtime", help="Optional runtime integration to inspect."),
    ] = None,
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
) -> None:
    """Check the no-key Python core environment."""
    if runtime is not None:
        if runtime != "deepseek-harness":
            _fail(
                code="runtime_unknown",
                message=f"Unsupported runtime: {runtime}",
                remediation="Use --runtime deepseek-harness.",
                as_json=json_output,
                exit_code=2,
            )
        report = inspect_deepseek_harness(project)
        payload = report.model_dump(mode="json")
        missing = sorted(
            {
                item
                for level in (
                    report.observe_ready,
                    report.check_ready,
                    report.govern_ready,
                )
                for item in level.missing
            }
        )
        _emit(
            payload,
            as_json=json_output,
            human=(
                f"DeepSeek Harness readiness: {report.status}\n"
                + (f"Missing: {', '.join(missing)}" if missing else "All P0 inputs are ready.")
            ),
        )
        if not report.observe_ready.ready:
            raise typer.Exit(code=4)
        return
    python_supported = sys.version_info[:2] == (3, 12)
    status = "ready" if python_supported else "unsupported"
    payload = {
        "schema_version": "1.0",
        "project": "AgentLoopGate",
        "version": __version__,
        "status": status,
        "python_supported": python_supported,
        "no_key_mode": True,
    }
    _emit(
        payload,
        as_json=json_output,
        human=f"AgentLoopGate core: {status} (Python 3.12, no API key required)",
    )
    if not python_supported:
        raise typer.Exit(code=4)


@app.command("init")
def init_project(
    runtime: Annotated[
        str,
        typer.Option("--runtime", help="Runtime integration to initialize."),
    ],
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace only the unfrozen runtime and redaction templates.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Create minimal runtime templates without editing a DeepSeek Profile."""
    if runtime != "deepseek-harness":
        _fail(
            code="runtime_unknown",
            message=f"Unsupported runtime: {runtime}",
            remediation="Use --runtime deepseek-harness.",
            as_json=json_output,
            exit_code=2,
        )
    result = bootstrap_deepseek_harness(project, force=force)
    payload = result.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"DeepSeek Harness templates ready: {len(result.created)} created, "
            f"{len(result.existing)} already present."
        ),
    )


@contract_app.command("validate")
def contract_validate(
    path: Annotated[Path, typer.Argument(help="Objective Contract YAML path.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Validate schema and verify the digest when a contract is frozen."""
    try:
        contract = load_contract(path)
        if contract.contract_digest is not None or contract.frozen_at is not None:
            verify_contract_digest(contract)
    except (OSError, ValueError, ValidationError, YAMLError) as exc:
        _fail(
            code="contract_invalid",
            message=str(exc),
            remediation="Fix the contract schema or restore the frozen contract bytes.",
            as_json=json_output,
            exit_code=2,
        )

    payload = {
        "schema_version": "1.0",
        "valid": True,
        "project": contract.project,
        "frozen": contract.frozen_at is not None,
        "computed_digest": computed_contract_digest(contract),
    }
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Objective Contract: valid ({'frozen' if payload['frozen'] else 'not frozen'}, "
            f"{payload['computed_digest']})"
        ),
    )


@contract_app.command("freeze")
def contract_freeze(
    path: Annotated[Path, typer.Argument(help="Objective Contract YAML path.")],
    confirmation: Annotated[
        str,
        typer.Option(
            "--confirm",
            help='Required exact confirmation: "FREEZE OBJECTIVE".',
        ),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Freeze the reviewed Objective Contract once; never relax it in place."""
    if confirmation != "FREEZE OBJECTIVE":
        _fail(
            code="objective_confirmation_required",
            message='Freezing requires --confirm "FREEZE OBJECTIVE".',
            remediation="Review every threshold, then provide the exact confirmation.",
            as_json=json_output,
            exit_code=3,
        )
    try:
        existing = load_contract(path)
        frozen = freeze_contract(existing, frozen_at=datetime.now(UTC))
        if existing.frozen_at is None:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                yaml.safe_dump(
                    frozen.model_dump(mode="json"),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        verify_contract_digest(load_contract(path))
    except (OSError, ValueError, ValidationError, YAMLError) as exc:
        _fail(
            code="contract_freeze_failed",
            message=str(exc),
            remediation="Restore the reviewed unfrozen contract and retry once.",
            as_json=json_output,
            exit_code=2,
        )
    payload = {
        "schema_version": "1.0",
        "status": "frozen",
        "contract_digest": frozen.contract_digest,
        "frozen_at": frozen.frozen_at.isoformat().replace("+00:00", "Z"),
    }
    _emit(
        payload,
        as_json=json_output,
        human=f"Objective Contract frozen: {frozen.contract_digest}",
    )


@split_app.command("freeze")
def split_freeze(
    config: Annotated[
        Path,
        typer.Option("--config", help="Split configuration YAML path."),
    ] = Path("configs/splits.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Freeze six disjoint pools after all task and OOD invariants pass."""
    try:
        frozen = SplitService(config).freeze(frozen_at=datetime.now(UTC))
    except SplitIntegrityError as exc:
        _fail(
            code="split_invalid",
            message=str(exc),
            remediation="Pin the benchmark and fix pool manifests before freezing.",
            as_json=json_output,
            exit_code=2,
        )
    payload = {
        "schema_version": "1.0",
        "status": frozen.status,
        "split_digest": frozen.split_digest,
        "task_count": sum(item.expected_count for item in frozen.pools.values()),
    }
    _emit(
        payload,
        as_json=json_output,
        human=f"Split frozen: {frozen.split_digest} ({payload['task_count']} tasks)",
    )


@split_app.command("verify")
def split_verify(
    config: Annotated[
        Path,
        typer.Option("--config", help="Split configuration YAML path."),
    ] = Path("configs/splits.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Verify frozen pool manifests and the global split digest."""
    try:
        frozen = SplitService(config).verify()
    except SplitIntegrityError as exc:
        _fail(
            code="split_invalid",
            message=str(exc),
            remediation="Restore the frozen config and pool manifests.",
            as_json=json_output,
            exit_code=2,
        )
    payload = {
        "schema_version": "1.0",
        "status": "verified",
        "split_digest": frozen.split_digest,
    }
    _emit(
        payload,
        as_json=json_output,
        human=f"Split verified: {frozen.split_digest}",
    )


@eval_app.command("reset-check")
def reset_check(
    fixture: Annotated[
        Path,
        typer.Option("--fixture", help="Frozen initial-state fixture directory."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Reset the same fixture twice and prove the initial state digest is stable."""
    try:
        with TemporaryDirectory(prefix="agentloopgate-reset-") as temporary:
            manager = ResetManager(Path(temporary))
            first = manager.reset(fixture, run_id="RESET_CHECK", attempt_id="A_001")
            second = manager.reset(fixture, run_id="RESET_CHECK", attempt_id="A_002")
    except ResetIntegrityError as exc:
        _fail(
            code="reset_invalid",
            message=str(exc),
            remediation="Restore a deterministic, symlink-free reset fixture.",
            as_json=json_output,
            exit_code=5,
        )
    consistent = first.initial_state_digest == second.initial_state_digest
    if not consistent:
        _fail(
            code="reset_digest_mismatch",
            message="Two resets produced different initial state digests.",
            remediation="Remove nondeterministic files from the reset fixture.",
            as_json=json_output,
            exit_code=5,
        )
    payload = {
        "schema_version": "1.0",
        "consistent": True,
        "initial_state_digest": first.initial_state_digest,
    }
    _emit(
        payload,
        as_json=json_output,
        human=f"Reset fixture is deterministic: {first.initial_state_digest}",
    )


@bridge_app.command("serve")
def bridge_serve(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
) -> None:
    """Serve one bounded bridge request/response per stdio JSONL line."""
    serve_stream(BridgeService(project), sys.stdin.buffer, sys.stdout.buffer)


@bridge_app.command("export-schema")
def bridge_export_schema(
    output: Annotated[
        Path,
        typer.Option("--output", help="Directory for JSON Schema and TypeScript types."),
    ] = Path("generated/bridge"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Generate the versioned bridge schema and TypeScript declarations."""
    artifacts = export_bridge_schema(output)
    payload = {
        "schema_version": "1.0",
        "json_schema": artifacts.schema_json.as_posix(),
        "typescript": artifacts.typescript.as_posix(),
    }
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Bridge contract exported: {artifacts.schema_json.as_posix()}, "
            f"{artifacts.typescript.as_posix()}"
        ),
    )


@pilot_app.command("run")
def pilot_run(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    pricing_config: Annotated[
        Path,
        typer.Option(
            "--pricing-config",
            help="Audited model-pricing evidence YAML.",
        ),
    ] = Path("configs/pilot_pricing.yaml"),
    checkout: Annotated[
        Path,
        typer.Option("--tau3-checkout", help="Pinned tau2-bench checkout."),
    ] = Path(".cache/tau2-bench"),
    dsh_executable: Annotated[
        Path,
        typer.Option("--dsh", help="Pinned DeepSeek Harness executable."),
    ] = Path("integrations/deepseek-harness/node_modules/.bin/dsh"),
    dsh_home: Annotated[
        Path,
        typer.Option("--dsh-home", help="Isolated DSH profile home for this project."),
    ] = Path("runs/dsh/home"),
    profile: Annotated[
        str,
        typer.Option("--profile", help="DSH profile containing the AgentLoopGate Bundle."),
    ] = "headless",
    provider: Annotated[
        str,
        typer.Option("--provider", help="DSH LLM provider route."),
    ] = "deepseek-official",
    model: Annotated[
        str,
        typer.Option("--model", help="Exact DSH model id."),
    ] = "deepseek-v4-flash",
    user_model: Annotated[
        str,
        typer.Option("--user-model", help="τ³ user-simulator model id."),
    ] = "deepseek/deepseek-v4-flash",
    run_name: Annotated[
        str,
        typer.Option("--run-name", help="Stable τ³ result and DSH session namespace."),
    ] = "pilot-dsh-a0",
    task_ids: Annotated[
        list[str] | None,
        typer.Option("--task-id", help="Pilot task id; repeat 3 to 7 times."),
    ] = None,
    trials: Annotated[
        int,
        typer.Option("--trials", min=1, help="Trials per selected Pilot task."),
    ] = 1,
    snapshot_id: Annotated[
        str,
        typer.Option("--snapshot", help="Pilot snapshot identity."),
    ] = "S_PILOT_DSH_A0",
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume an interrupted run with the same frozen inputs."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Run 3–7 banking tasks with DSH sessions and τ³ outcome authority."""
    root = project.resolve()
    resolved_checkout = _resolve_under_root(root, checkout)
    selected = task_ids or _pilot_task_ids(root)[:3]
    if not 3 <= len(selected) <= 7 or len(selected) != len(set(selected)):
        _fail(
            code="pilot_tasks_invalid",
            message="Banking Pilot requires 3–7 unique task ids.",
            remediation="Repeat --task-id 3 to 7 times, or omit it for the first three.",
            as_json=json_output,
            exit_code=2,
        )
    official_pilot = set(_pilot_task_ids(root))
    if not set(selected).issubset(official_pilot):
        _fail(
            code="pilot_tasks_invalid",
            message="A selected task is not in the frozen Pilot pool.",
            remediation="Choose task ids from data/splits/pilot.json.",
            as_json=json_output,
            exit_code=3,
        )
    try:
        pricing = load_pilot_pricing(_resolve_under_root(root, pricing_config))
    except (OSError, ValueError, ValidationError, OutcomeImportError) as exc:
        _fail(
            code="pilot_price_invalid",
            message=str(exc),
            remediation="Restore audited per-million-token pricing evidence.",
            as_json=json_output,
            exit_code=2,
        )
    if pricing.provider != provider or pricing.model != model:
        _fail(
            code="pilot_price_invalid",
            message="Pricing evidence does not match the selected provider/model.",
            remediation="Select the priced model or provide matching audited pricing YAML.",
            as_json=json_output,
            exit_code=2,
        )
    pilot = DshTau3PilotConfig(
        dsh_executable=_resolve_under_root(root, dsh_executable),
        dsh_home=_resolve_under_root(root, dsh_home),
        patch_path=root / "examples/tau3-banking/dsh-tau3.patch.yml",
        session_root=root / "runs/dsh/native-sessions",
        profile=profile,
        provider=provider,
        model=model,
        experiment_namespace=run_name,
        pricing=pricing,
    )
    adapter = DshTau3Adapter(root, checkout=resolved_checkout, pilot=pilot)
    try:
        contract = load_contract(root / "configs/objective_contract.yaml")
        frozen_split = SplitService(root / "configs/splits.yaml").verify()
        if frozen_split.split_digest is None:
            raise ValueError("split digest is missing after verification")
        initial_states = _tau3_initial_state_digests(resolved_checkout, selected)
        request = BenchmarkRunRequest(
            task_ids=selected,
            trials=trials,
            agent_model=f"{provider}/{model}",
            user_model=user_model,
            run_name=run_name,
            max_concurrency=1,
            resume=resume,
        )
        context = BenchmarkRunContext(
            pool=Pool.PILOT,
            snapshot_id=snapshot_id,
            candidate_id=None,
            objective_digest=computed_contract_digest(contract),
            split_digest=frozen_split.split_digest,
            benchmark_commit=TAU3_COMMIT,
            model_id=request.agent_model,
            expected_task_ids=selected,
            initial_state_digests=initial_states,
            expected_trials=trials,
        )
        result_path = adapter.run(request)
        result = adapter.ingest_and_link(result_path, context)
    except BenchmarkUnavailableError as exc:
        _fail(
            code="pilot_dependency_unavailable",
            message=str(exc),
            remediation=(
                "Install the pinned plugin into --dsh-home and export credentials in "
                "the current process."
            ),
            as_json=json_output,
            exit_code=4,
        )
    except (OSError, ValueError, ValidationError, SplitIntegrityError, OutcomeImportError) as exc:
        _fail(
            code="pilot_evidence_invalid",
            message=str(exc),
            remediation="Restore pinned inputs or inspect the retained τ³ and DSH artifacts.",
            as_json=json_output,
            exit_code=5,
        )
    payload = {
        "schema_version": "1.0",
        "status": "pilot_evidence_ready",
        "real_experiment": True,
        "run_name": run_name,
        "task_count": len(selected),
        "trial_count": trials,
        "tau_run_count": len(result.records),
        "dsh_run_count": len(result.dsh_records),
        "evidence_join_ids": [join.join_id for join in result.evidence_joins],
        "result_artifact": result_path.resolve().relative_to(root).as_posix(),
        "gate_decision": None,
    }
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Banking Pilot evidence ready: {payload['tau_run_count']} τ³ outcomes, "
            f"{payload['dsh_run_count']} DSH traces; no Gate decision was inferred."
        ),
    )


@experiment_app.command("preflight")
def experiment_preflight(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    config: Annotated[
        Path,
        typer.Option("--config", help="Formal experiment configuration YAML."),
    ] = Path("configs/formal_experiment.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Prove every irreversible formal-run prerequisite without running a model."""
    try:
        report = inspect_formal_preflight(project, config_path=config)
    except (OSError, ValueError, ValidationError, YAMLError) as exc:
        _fail(
            code="formal_preflight_invalid",
            message=str(exc),
            remediation="Restore the reviewed formal experiment configuration.",
            as_json=json_output,
            exit_code=2,
        )
    payload = report.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=(
            "Formal experiment preflight: ready"
            if report.ready
            else "Formal experiment preflight: blocked\nMissing: "
            + "\n- ".join(report.missing)
        ),
    )
    if not report.ready:
        raise typer.Exit(code=4)


@experiment_app.command("protocol-verify")
def experiment_protocol_verify(
    config: Annotated[
        Path,
        typer.Option("--config", help="Frozen execution protocol YAML."),
    ] = Path("configs/experiment_protocol_banking_r2.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Verify the content digest and frozen execution controls without a model call."""
    try:
        protocol = load_execution_protocol(config)
    except (OSError, ValueError, ValidationError, YAMLError) as exc:
        _fail(
            code="execution_protocol_invalid",
            message=str(exc),
            remediation="Restore the reviewed frozen protocol; never edit it in place.",
            as_json=json_output,
            exit_code=2,
        )
    payload = protocol.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Execution protocol verified: {protocol.protocol_id}; "
            f"digest={protocol.protocol_digest}."
        ),
    )


@experiment_app.command("study-verify")
def experiment_study_verify(
    config: Annotated[
        Path,
        typer.Option("--config", help="Frozen Banking R2 study-plan YAML."),
    ] = Path("configs/banking_r2_study.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Verify the pre-registered core matrix, ablations, and analysis choices."""
    try:
        plan = load_study_plan(config)
    except (OSError, ValueError, ValidationError, YAMLError) as exc:
        _fail(
            code="study_plan_invalid",
            message=str(exc),
            remediation="Restore the reviewed frozen study plan; never edit it in place.",
            as_json=json_output,
            exit_code=2,
        )
    payload = plan.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Banking R2 study verified: {plan.study_id}; "
            f"{plan.core_target_trial_count} target trials; digest={plan.study_digest}."
        ),
    )


@experiment_app.command("ablation-integrity")
def experiment_ablation_integrity(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    study: Annotated[
        Path,
        typer.Option("--study", help="Frozen Banking R2 study-plan YAML."),
    ] = Path("configs/banking_r2_study.yaml"),
    protocol: Annotated[
        Path,
        typer.Option("--protocol", help="Frozen Banking R2 execution protocol."),
    ] = Path("configs/experiment_protocol_banking_r2.yaml"),
    output: Annotated[
        Path,
        typer.Option("--output", help="Content-addressed ablation result JSON."),
    ] = Path("artifacts/research/banking_r2/ablations/integrity_gate.json"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Run the deterministic fail-closed integrity-gate ablation."""
    try:
        artifact = run_integrity_gate_ablation(
            project,
            study_path=study,
            output_path=output,
            protocol_path=protocol,
        )
    except (OSError, ValueError, ValidationError, YAMLError) as exc:
        _fail(
            code="integrity_ablation_invalid",
            message=str(exc),
            remediation="Restore the frozen study and objective inputs.",
            as_json=json_output,
            exit_code=2,
        )
    payload = artifact.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=(
            "Integrity Gate ablation: production=HOLD, counterfactual=SHIP_RECOMMENDED; "
            f"digest={artifact.artifact_digest}."
        ),
    )


@experiment_app.command("ablation-plugin")
def experiment_ablation_plugin(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    study: Annotated[
        Path,
        typer.Option("--study", help="Frozen Banking R2 study-plan YAML."),
    ] = Path("configs/banking_r2_study.yaml"),
    protocol: Annotated[
        Path,
        typer.Option("--protocol", help="Frozen Banking R2 execution protocol."),
    ] = Path("configs/experiment_protocol_banking_r2.yaml"),
    output: Annotated[
        Path,
        typer.Option("--output", help="Content-addressed ablation result JSON."),
    ] = Path(
        "artifacts/research/banking_r2/ablations/"
        "plugin_coexistence_overhead.json"
    ),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Run the no-model DSH trace/persistence/OTel coexistence ablation."""
    try:
        artifact = run_plugin_coexistence_ablation(
            project,
            study_path=study,
            protocol_path=protocol,
            output_path=output,
        )
    except (OSError, ValueError, RuntimeError, ValidationError, YAMLError) as exc:
        _fail(
            code="plugin_ablation_invalid",
            message=str(exc),
            remediation="Inspect the immutable attempt ledger and preserve failed evidence.",
            as_json=json_output,
            exit_code=2,
        )
    _emit(
        artifact,
        as_json=json_output,
        human=(
            "Plugin coexistence/overhead ablation completed with zero model calls; "
            f"digest={artifact['artifact_digest']}."
        ),
    )


@experiment_app.command("stage")
def experiment_stage(
    stage: Annotated[
        FormalStage,
        typer.Option("--stage", help="Frozen formal experiment stage to run or resume."),
    ],
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    config: Annotated[
        Path,
        typer.Option("--config", help="Formal experiment configuration YAML."),
    ] = Path("configs/formal_experiment.yaml"),
    snapshot: Annotated[
        str | None,
        typer.Option(
            "--snapshot",
            help="Frozen snapshot to evaluate; defaults to the configured A0.",
        ),
    ] = None,
    existing_only: Annotated[
        bool,
        typer.Option(
            "--existing-only",
            help=(
                "Seal already-retained raw evidence without preflight credentials or "
                "a model call. Fails if the exact batch raw file is absent."
            ),
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Run one paid formal batch once, or verify and resume its existing evidence."""
    if not existing_only:
        report = inspect_formal_preflight(project, config_path=config)
        if not report.ready:
            _fail(
                code="formal_preflight_blocked",
                message="; ".join(report.missing),
                remediation="Resolve every preflight item before a paid formal stage.",
                as_json=json_output,
                exit_code=4,
            )
    service = FormalExperimentService(project, config_path=config)
    try:
        if existing_only:
            result = service.run_stage(
                stage,
                snapshot_id=snapshot or service.config.baseline_snapshot_id,
                existing_only=True,
            )
        else:
            baseline_id = (
                FormalExperimentOrchestrator(
                    project,
                    config_path=config,
                ).ensure_evaluation_baseline(
                    command=[
                        "agentloopgate",
                        "experiment",
                        "stage",
                        "--stage",
                        stage.value,
                        "--config",
                        str(config),
                        *(["--snapshot", snapshot] if snapshot is not None else []),
                    ]
                )
                if service.config.schema_version == "1.1"
                else service.ensure_baseline()
            )
            result = service.run_stage(stage, snapshot_id=snapshot or baseline_id)
    except BenchmarkUnavailableError as exc:
        _fail(
            code="formal_dependency_unavailable",
            message=str(exc),
            remediation="Restore the pinned DSH × τ³ runtime and current-process credential.",
            as_json=json_output,
            exit_code=4,
        )
    except (OSError, ValueError, ValidationError, FormalBatchError) as exc:
        _fail(
            code="formal_stage_invalid",
            message=str(exc),
            remediation="Inspect the immutable batch evidence; do not overwrite it.",
            as_json=json_output,
            exit_code=5,
        )
    artifact = result.artifact
    payload = {
        **artifact.model_dump(mode="json"),
        "resumed": result.resumed,
    }
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Formal {stage.value} batch {'resumed' if result.resumed else 'sealed'}: "
            f"{artifact.batch_id}; disposition={artifact.disposition}; "
            f"{artifact.summary.stable_success_task_count}/"
            f"{artifact.summary.expected_task_count} stable tasks"
            + (
                f"; reasons={','.join(artifact.hold_reasons)}."
                if artifact.hold_reasons
                else "."
            )
        ),
    )


@experiment_app.command("baseline-freeze")
def experiment_baseline_freeze(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    config: Annotated[
        Path,
        typer.Option("--config", help="Formal R2 experiment configuration YAML."),
    ] = Path("configs/formal_experiment_r2.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Freeze or verify the non-active R2 evaluation baseline without a model call."""

    try:
        orchestrator = FormalExperimentOrchestrator(project, config_path=config)
        snapshot_id = orchestrator.ensure_evaluation_baseline(
            command=[
                "agentloopgate",
                "experiment",
                "baseline-freeze",
                "--config",
                str(config),
            ]
        )
        manager = SnapshotManager(project)
        snapshot = manager.verify(snapshot_id)
        active = manager.verify_active_live()
    except (
        OSError,
        ValueError,
        ValidationError,
        FormalWorkflowBlocked,
        SnapshotIntegrityError,
    ) as exc:
        _fail(
            code="evaluation_baseline_invalid",
            message=str(exc),
            remediation=(
                "Restore the frozen source, protocol, study, and active harness bytes; "
                "inspect the immutable attempt ledger before retrying."
            ),
            as_json=json_output,
            exit_code=5,
        )
    payload = {
        "schema_version": "1.0",
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": canonical_digest(snapshot),
        "code_revision": snapshot.code_revision,
        "active_snapshot_id": active.snapshot_id,
        "deployment_activation_changed": False,
        "model_calls": 0,
        "cost_status": "not_applicable",
    }
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Evaluation baseline frozen: {snapshot.snapshot_id}; "
            f"source={snapshot.code_revision}; deployment activation unchanged."
        ),
    )


@experiment_app.command("run")
def experiment_run(
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    config: Annotated[
        Path,
        typer.Option("--config", help="Formal experiment configuration YAML."),
    ] = Path("configs/formal_experiment.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Run or resume the complete A0-to-Decision P0 workflow without promotion."""
    report = inspect_formal_preflight(project, config_path=config)
    if not report.ready:
        _fail(
            code="formal_preflight_blocked",
            message="; ".join(report.missing),
            remediation="Resolve every preflight item, then rerun this same command.",
            as_json=json_output,
            exit_code=4,
        )
    try:
        outcome = FormalExperimentOrchestrator(
            project,
            config_path=config,
        ).run()
    except BenchmarkUnavailableError as exc:
        _fail(
            code="formal_dependency_unavailable",
            message=str(exc),
            remediation="Restore the pinned DSH, τ³, AHE, and credential boundary.",
            as_json=json_output,
            exit_code=4,
        )
    except FormalWorkflowBlocked as exc:
        _fail(
            code="formal_workflow_blocked",
            message=str(exc),
            remediation=(
                "Inspect retained immutable artifacts; fix only the stated environment or "
                "evidence issue, then rerun."
            ),
            as_json=json_output,
            exit_code=5,
        )
    except (OSError, ValueError, ValidationError) as exc:
        _fail(
            code="formal_evidence_invalid",
            message=str(exc),
            remediation="Restore the frozen inputs or the exact retained evidence bytes.",
            as_json=json_output,
            exit_code=5,
        )
    payload = outcome.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Formal experiment {outcome.experiment_id}: {outcome.final_decision.value}; "
            f"native={outcome.native_decision.value}; candidates={len(outcome.candidate_ids)}; "
            f"P0 requirements={'met' if outcome.p0_requirements_met else 'incomplete'}."
        ),
    )
    if not outcome.p0_requirements_met:
        raise typer.Exit(code=5)


@snapshot_app.command("promote")
def snapshot_promote(
    snapshot_id: Annotated[str, typer.Argument(help="Frozen child snapshot id.")],
    decision_path: Annotated[
        Path,
        typer.Option("--decision", help="SHIP_RECOMMENDED DecisionRecord JSON."),
    ],
    approval_path: Annotated[
        Path,
        typer.Option("--approval", help="Human promotion approval JSON."),
    ],
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Activate a Gate-approved child snapshot; never called by experiment run."""
    root = project.resolve()
    try:
        decision = DecisionRecord.model_validate_json(
            _resolve_under_root(root, decision_path).read_text(encoding="utf-8")
        )
        approval = PromotionApproval.model_validate_json(
            _resolve_under_root(root, approval_path).read_text(encoding="utf-8")
        )
        manager = SnapshotManager(root)
        target = manager.verify(snapshot_id)
        if target.candidate_id is None:
            raise SnapshotAuthorizationError("baseline snapshots cannot be promoted")
        registry = _candidate_registry(root)
        candidate = registry.load(target.candidate_id)
        if candidate.status not in {
            CandidateStatus.SHIP_RECOMMENDED,
            CandidateStatus.SHIPPED,
        }:
            raise SnapshotAuthorizationError(
                "candidate must be SHIP_RECOMMENDED before promotion"
            )
        activation = manager.promote(snapshot_id, decision, approval=approval)
        if candidate.status is CandidateStatus.SHIP_RECOMMENDED:
            registry.transition(
                candidate.candidate_id,
                CandidateStatus.SHIPPED,
                actor=approval.actor,
                evidence_refs=[_activation_ref(activation.ordinal)],
                occurred_at=approval.approved_at,
            )
    except (SnapshotAuthorizationError, CandidateStateError) as exc:
        _fail(
            code="snapshot_promotion_rejected",
            message=str(exc),
            remediation="Provide matching human approval and a SHIP_RECOMMENDED decision.",
            as_json=json_output,
            exit_code=3,
        )
    except (OSError, ValueError, ValidationError, SnapshotIntegrityError) as exc:
        _fail(
            code="snapshot_promotion_invalid",
            message=str(exc),
            remediation="Restore the frozen snapshot, decision, approval, and live parent.",
            as_json=json_output,
            exit_code=5,
        )
    payload = activation.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=f"Snapshot promoted by human approval: {activation.snapshot_id}",
    )


@snapshot_app.command("rollback")
def snapshot_rollback(
    snapshot_id: Annotated[str, typer.Argument(help="Parent snapshot id to restore.")],
    approval_path: Annotated[
        Path,
        typer.Option("--approval", help="Human rollback approval JSON."),
    ],
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
) -> None:
    """Restore the active child snapshot's parent under explicit human approval."""
    root = project.resolve()
    try:
        approval = PromotionApproval.model_validate_json(
            _resolve_under_root(root, approval_path).read_text(encoding="utf-8")
        )
        manager = SnapshotManager(root)
        activation = manager.rollback(snapshot_id, approval=approval)
        previous = manager.verify(activation.previous_snapshot_id or "")
        if previous.candidate_id is not None:
            registry = _candidate_registry(root)
            candidate = registry.load(previous.candidate_id)
            if candidate.status is CandidateStatus.SHIPPED:
                registry.transition(
                    candidate.candidate_id,
                    CandidateStatus.ROLLED_BACK,
                    actor=approval.actor,
                    evidence_refs=[_activation_ref(activation.ordinal)],
                    occurred_at=approval.approved_at,
                )
            elif candidate.status is not CandidateStatus.ROLLED_BACK:
                raise SnapshotAuthorizationError(
                    "rolled-back child candidate is not in the shipped lifecycle"
                )
    except (SnapshotAuthorizationError, CandidateStateError) as exc:
        _fail(
            code="snapshot_rollback_rejected",
            message=str(exc),
            remediation="Provide matching human approval for the active snapshot parent.",
            as_json=json_output,
            exit_code=3,
        )
    except (OSError, ValueError, ValidationError, SnapshotIntegrityError) as exc:
        _fail(
            code="snapshot_rollback_invalid",
            message=str(exc),
            remediation="Restore the frozen snapshots, approval, and live child bytes.",
            as_json=json_output,
            exit_code=5,
        )
    payload = activation.model_dump(mode="json")
    _emit(
        payload,
        as_json=json_output,
        human=f"Snapshot rolled back by human approval: {activation.snapshot_id}",
    )


def _resolve_under_root(root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def _candidate_registry(root: Path) -> CandidateRegistry:
    policy = load_mutation_policy(root / "configs/mutation_policy.yaml")
    return CandidateRegistry(
        root,
        CandidateChecker(
            root,
            load_asset_manifest(root / "configs/harness_assets.yaml"),
            policy,
            freeze_trust_kernel(root, policy),
        ),
    )


def _activation_ref(ordinal: int) -> str:
    return f"snapshots/activations/{ordinal:04d}.json"


def _pilot_task_ids(root: Path) -> list[str]:
    try:
        raw = json.loads((root / "data/splits/pilot.json").read_text(encoding="utf-8"))
        tasks = raw["tasks"]
        result = [item["task_id"] for item in tasks]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("cannot read the frozen Pilot task manifest") from exc
    if not all(isinstance(item, str) and item for item in result):
        raise ValueError("Pilot task manifest contains an invalid task id")
    return result


def _tau3_initial_state_digests(checkout: Path, task_ids: list[str]) -> dict[str, str]:
    path = checkout / "data/tau2/domains/banking_knowledge/tasks.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read the pinned τ³ banking task catalog") from exc
    if not isinstance(raw, list):
        raise ValueError("τ³ banking task catalog must be a JSON list")
    by_id = {
        task.get("id"): task
        for task in raw
        if isinstance(task, dict) and isinstance(task.get("id"), str)
    }
    if not set(task_ids).issubset(by_id):
        raise ValueError("a Pilot task is missing from the pinned τ³ catalog")
    return {
        task_id: canonical_digest(
            {"task_id": task_id, "initial_state": by_id[task_id].get("initial_state")}
        )
        for task_id in task_ids
    }


@app.command()
def demo(
    fixture: Annotated[
        Path,
        typer.Option("--fixture", help="Fixture directory or demo.json file."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a stable JSON object."),
    ] = False,
    build_output: Annotated[
        Path | None,
        typer.Option(
            "--build-output",
            help="Build the deterministic no-key artifact package before validating it.",
        ),
    ] = None,
    project: Annotated[
        Path,
        typer.Option("--project", help="AgentLoopGate project root."),
    ] = Path("."),
) -> None:
    """Validate and summarize a no-key public fixture."""
    if build_output is not None:
        try:
            fixture_file = build_public_demo(project, build_output)
        except (OSError, ValueError, ValidationError) as exc:
            _fail(
                code="fixture_build_failed",
                message=str(exc),
                remediation="Restore the public fixture inputs and retry in an empty output path.",
                as_json=json_output,
                exit_code=5,
            )
    else:
        fixture_file = fixture / "demo.json" if fixture.suffix.lower() != ".json" else fixture
    if not fixture_file.is_file():
        _fail(
            code="fixture_not_found",
            message=f"Fixture file does not exist: {fixture_file.as_posix()}",
            remediation="Pass a directory containing demo.json.",
            as_json=json_output,
            exit_code=2,
        )

    try:
        raw = json.loads(fixture_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(
            code="fixture_invalid",
            message=f"Fixture cannot be read as JSON: {exc}",
            remediation="Provide a UTF-8 demo.json object.",
            as_json=json_output,
            exit_code=2,
        )

    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != "1.0"
        or raw.get("real_experiment") is not False
    ):
        _fail(
            code="fixture_schema_invalid",
            message=(
                "Fixture must be an object with schema_version 1.0 and "
                "real_experiment=false."
            ),
            remediation="Update demo.json to the public fixture schema.",
            as_json=json_output,
            exit_code=2,
        )

    runs = raw.get("runs", [])
    candidates = raw.get("candidates", [])
    if not isinstance(runs, list) or not isinstance(candidates, list):
        _fail(
            code="fixture_schema_invalid",
            message="Fixture runs and candidates must be arrays.",
            remediation="Update demo.json to the public fixture schema.",
            as_json=json_output,
            exit_code=2,
        )
    try:
        normalized_runs = [RunRecord.model_validate(item) for item in runs]
        failed_gates = {
            str(item["failed_gate"])
            for item in candidates
            if isinstance(item, dict)
            and item.get("decision") == "HOLD"
            and item.get("failed_gate") is not None
        }
    except (KeyError, TypeError, ValidationError) as exc:
        _fail(
            code="fixture_schema_invalid",
            message=f"Fixture contains an invalid run or candidate: {exc}",
            remediation="Rebuild the fixture with agentloopgate demo --build-output.",
            as_json=json_output,
            exit_code=2,
        )
    if not normalized_runs or not {"ood_noninferiority", "cost"}.issubset(failed_gates):
        _fail(
            code="fixture_incomplete",
            message="Fixture must include a run plus OOD and cost HOLD candidates.",
            remediation="Rebuild the fixture with agentloopgate demo --build-output.",
            as_json=json_output,
            exit_code=5,
        )

    payload = {
        "schema_version": "1.0",
        "fixture_id": str(raw.get("fixture_id", "unknown")),
        "status": "fixture_ready",
        "real_experiment": False,
        "run_count": len(normalized_runs),
        "candidate_count": len(candidates),
    }
    _emit(
        payload,
        as_json=json_output,
        human=(
            f"Fixture {payload['fixture_id']}: ready "
            f"({payload['run_count']} runs, {payload['candidate_count']} candidates; no-key)"
        ),
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
