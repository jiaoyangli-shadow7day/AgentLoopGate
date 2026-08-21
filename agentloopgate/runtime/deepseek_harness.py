"""Safe bootstrap and three-level readiness for DeepSeek Harness projects."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from agentloopgate.bridge import BridgeRequest, BridgeService
from agentloopgate.contracts import canonical_json_bytes, load_contract, verify_contract_digest
from agentloopgate.mutation import load_asset_manifest, load_mutation_policy
from agentloopgate.schemas.models import StrictModel
from agentloopgate.splits import SplitService


class DshTraceConfig(StrictModel):
    source: Literal["deepseek_session"]
    ingest_mode: Literal["reference", "mirror"]
    live: bool
    backfill_on_start: bool
    max_batch_events: int = Field(ge=1, le=100)
    max_buffer_events: int = Field(ge=1)
    redact_policy: str


class DeepSeekHarnessConfig(StrictModel):
    schema_version: Literal["1.0"]
    runtime: Literal["deepseek-harness"]
    dsh_version: Literal["0.1.0-rc.8"]
    dsh_commit: Literal["141eb6fef83422698aef7a981029e843e8161534"]
    node_range: Literal["^22.19.0 || >=24.0.0"]
    pnpm_version: Literal["11.7.0"]
    profile: str = Field(min_length=1)
    plugin_package: Literal["@agentloopgate/dsh-plugin"]
    plugin_version: Literal["0.1.0"]
    bridge_protocol_version: Literal["1.0"]
    trace: DshTraceConfig


class RedactionConfig(StrictModel):
    schema_version: Literal["1.0"]
    replacement: Literal["[REDACTED]"]
    sensitive_keys: list[str] = Field(min_length=1)
    max_text_bytes: int = Field(ge=1)


class EvaluatorConfig(StrictModel):
    schema_version: Literal["1.0"]
    kind: Literal["tau3_outcome"]
    authority: Literal["independent"]
    benchmark: Literal["tau3-bench"]
    benchmark_commit: Literal["fc0055dc4e0a316c3f83133267fbd6faaa770992"]
    suite: Literal["banking_knowledge"]
    success_rule: Literal["official_reward_equals_1"]
    infrastructure_rule: Literal["termination_reason_infrastructure_error"]
    llm_grader_allowed: Literal[False]


class ReadinessLevel(StrictModel):
    ready: bool
    available_capabilities: list[str]
    missing: list[str]
    remediation: list[str]


class ReadinessReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    runtime: Literal["deepseek-harness"] = "deepseek-harness"
    status: Literal["observe_ready", "check_ready", "govern_ready", "not_ready"]
    observe_ready: ReadinessLevel
    check_ready: ReadinessLevel
    govern_ready: ReadinessLevel


class BootstrapResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    runtime: Literal["deepseek-harness"] = "deepseek-harness"
    created: list[str]
    existing: list[str]


_RUNTIME_TEMPLATE = {
    "schema_version": "1.0",
    "runtime": "deepseek-harness",
    "dsh_version": "0.1.0-rc.8",
    "dsh_commit": "141eb6fef83422698aef7a981029e843e8161534",
    "node_range": "^22.19.0 || >=24.0.0",
    "pnpm_version": "11.7.0",
    "profile": "headless",
    "plugin_package": "@agentloopgate/dsh-plugin",
    "plugin_version": "0.1.0",
    "bridge_protocol_version": "1.0",
    "trace": {
        "source": "deepseek_session",
        "ingest_mode": "reference",
        "live": True,
        "backfill_on_start": True,
        "max_batch_events": 100,
        "max_buffer_events": 1000,
        "redact_policy": "configs/trace_redaction.yaml",
    },
}

_REDACTION_TEMPLATE = {
    "schema_version": "1.0",
    "replacement": "[REDACTED]",
    "sensitive_keys": [
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "secret",
        "access_token",
        "refresh_token",
        "session_id",
    ],
    "max_text_bytes": 8192,
}


def bootstrap_deepseek_harness(project_root: Path, *, force: bool = False) -> BootstrapResult:
    root = project_root.resolve()
    targets = {
        root / "configs/runtime_dsh.yaml": _RUNTIME_TEMPLATE,
        root / "configs/trace_redaction.yaml": _REDACTION_TEMPLATE,
    }
    created: list[str] = []
    existing: list[str] = []
    for path, payload in targets.items():
        relative = path.relative_to(root).as_posix()
        if path.exists() and not force:
            existing.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        created.append(relative)
    return BootstrapResult(created=created, existing=existing)


def load_runtime_config(path: Path) -> DeepSeekHarnessConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DeepSeekHarnessConfig.model_validate(raw)


def inspect_deepseek_harness(project_root: Path) -> ReadinessReport:
    root = project_root.resolve()
    observe_missing: list[str] = []
    observe_remediation: list[str] = []
    config: DeepSeekHarnessConfig | None = None
    try:
        config = load_runtime_config(root / "configs/runtime_dsh.yaml")
        redact_path = (root / config.trace.redact_policy).resolve()
        if not redact_path.is_relative_to(root):
            raise ValueError("trace redaction path escapes the project root")
        RedactionConfig.model_validate(yaml.safe_load(redact_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        observe_missing.append(f"runtime_config:{exc}")
        observe_remediation.append(
            "Run agentloopgate init --runtime deepseek-harness --project ."
        )

    bridge = BridgeService(root).handle(
        BridgeRequest(
            protocol_version="1.0",
            request_id="DOCTOR_HEALTH",
            method="health",
            payload={},
        )
    )
    if not bridge.ok:
        observe_missing.append("python_bridge")
        observe_remediation.append("Repair the local AgentLoopGate Core installation.")

    if config is not None:
        executable = shutil.which("dsh")
        if executable is None:
            observe_missing.append("dsh_executable")
            observe_remediation.append(f"Install DeepSeek Harness {config.dsh_version}.")
        profile_manifest = _profile_manifest(config.profile, project_root=root)
        if not _profile_has_plugin(profile_manifest, config.plugin_package):
            observe_missing.append("profile_bundle")
            observe_remediation.append(
                "Install the Bundle with: dsh plugin --profile "
                f"{config.profile} add <agentloopgate-plugin-package>."
            )

    check_missing: list[str] = []
    check_remediation: list[str] = []
    try:
        contract = load_contract(root / "configs/objective_contract.yaml")
        load_asset_manifest(root / "configs/harness_assets.yaml")
        load_mutation_policy(root / "configs/mutation_policy.yaml")
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        contract = None
        check_missing.append(f"governance_templates:{exc}")
        check_remediation.append(
            "Add valid Objective Contract, Harness Asset Manifest, and Mutation Policy files."
        )

    govern_missing: list[str] = []
    govern_remediation: list[str] = []
    if contract is None or contract.frozen_at is None or contract.contract_digest is None:
        govern_missing.append("frozen_objective_contract")
        govern_remediation.append("Freeze the Objective Contract after the Pilot.")
    else:
        try:
            verify_contract_digest(contract)
        except ValueError as exc:
            govern_missing.append(f"objective_digest:{exc}")
    try:
        SplitService(root / "configs/splits.yaml").verify()
    except (OSError, ValueError) as exc:
        govern_missing.append(f"frozen_splits:{exc}")
        govern_remediation.append("Freeze and verify the six isolated data pools.")
    try:
        EvaluatorConfig.model_validate(
            yaml.safe_load((root / "configs/evaluator.yaml").read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        govern_missing.append("deterministic_evaluator")
        govern_remediation.append(f"Restore configs/evaluator.yaml: {exc}")
    if not any((root / "candidates").glob("*/events/*.json")):
        govern_missing.append("registered_candidate")
        govern_remediation.append("Generate and register at least one external-updater candidate.")

    observe_ready = not observe_missing
    check_ready = not check_missing
    govern_ready = check_ready and not govern_missing
    status: Literal["observe_ready", "check_ready", "govern_ready", "not_ready"]
    if govern_ready:
        status = "govern_ready"
    elif check_ready:
        status = "check_ready"
    elif observe_ready:
        status = "observe_ready"
    else:
        status = "not_ready"
    return ReadinessReport(
        status=status,
        observe_ready=ReadinessLevel(
            ready=observe_ready,
            available_capabilities=(
                ["trace_correlation", "tool_and_cost_facts", "evidence_verify"]
                if observe_ready
                else []
            ),
            missing=observe_missing,
            remediation=observe_remediation,
        ),
        check_ready=ReadinessLevel(
            ready=check_ready,
            available_capabilities=(
                ["contract_validate", "candidate_check", "decision_explain"]
                if check_ready
                else []
            ),
            missing=check_missing,
            remediation=check_remediation,
        ),
        govern_ready=ReadinessLevel(
            ready=govern_ready,
            available_capabilities=(
                ["diagnose", "update", "evaluate", "gate", "rollback"]
                if govern_ready
                else []
            ),
            missing=govern_missing,
            remediation=govern_remediation,
        ),
    )


def _profile_manifest(
    profile: str,
    *,
    project_root: Path | None = None,
) -> dict[str, object] | None:
    configured = os.environ.get("DSH_HOME")
    if configured is not None:
        dsh_home = Path(configured).expanduser()
    elif project_root is not None and (project_root / "runs/dsh/home").is_dir():
        dsh_home = project_root / "runs/dsh/home"
    else:
        dsh_home = Path.home() / ".dsh"
    path = dsh_home / "profiles" / profile / "package.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _profile_has_plugin(manifest: dict[str, object] | None, package: str) -> bool:
    if manifest is None:
        return False
    dependencies = manifest.get("dependencies")
    dsh = manifest.get("dsh")
    profile = dsh.get("profile") if isinstance(dsh, dict) else None
    bundles = profile.get("bundles") if isinstance(profile, dict) else None
    return (
        isinstance(dependencies, dict)
        and package in dependencies
        and isinstance(bundles, list)
        and package in bundles
    )


def stable_readiness_json(report: ReadinessReport) -> bytes:
    return canonical_json_bytes(report)
