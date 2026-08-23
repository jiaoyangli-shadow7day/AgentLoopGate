"""Fail-closed preflight for the credentialed P0 experiment."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from agentloopgate.adapters import (
    DSH_COMMIT,
    DSH_VERSION,
    TAU3_COMMIT,
    DshTau3Adapter,
    DshTau3PilotConfig,
    PilotPricingConfig,
    load_pilot_pricing,
)
from agentloopgate.candidates import CandidateRegistry
from agentloopgate.contracts import (
    canonical_digest,
    canonical_json_bytes,
    computed_contract_digest,
    file_digest,
    load_contract,
    verify_contract_digest,
)
from agentloopgate.mutation import (
    CandidateChecker,
    freeze_trust_kernel,
    load_asset_manifest,
    load_mutation_policy,
)
from agentloopgate.runtime import (
    DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT,
    DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT,
    DSH_TAU3_FAILURE_USAGE_POLICY_CURRENT,
    DSH_TAU3_PROTOCOL_CURRENT,
    DSH_TAU3_REPLY_POLICY_CURRENT,
    load_evaluator_overlay,
    verify_evaluator_overlay_sources,
)
from agentloopgate.schemas import Digest, PilotEvidenceJoin, Pool, RunRecord, RuntimeHost
from agentloopgate.schemas.models import ArtifactId, NonEmpty, StrictModel, UtcDateTime
from agentloopgate.snapshots import SnapshotIntegrityError, SnapshotManager
from agentloopgate.splits import SplitService
from agentloopgate.splits.models import PoolManifest
from agentloopgate.updaters import AheAdapter, AheExternalRunner

from .batch import (
    DshFormalBatchExecutor,
    FormalBatchRunner,
    FormalBatchRunResult,
    FormalBatchSpec,
    FormalStage,
)
from .protocol import (
    FormalExecutionProtocol,
    load_cost_lineage_calibration,
    load_evaluator_correction_calibration,
    load_execution_protocol,
    load_reply_lineage_calibration,
)
from .study import BankingStudyPlan, load_study_plan


class PaidExecutionAuthorizationError(ValueError):
    """A new paid stage lacks exact, current Owner authorization evidence."""


class FormalExperimentConfig(StrictModel):
    schema_version: Literal["1.0", "1.1", "1.2"]
    experiment_id: ArtifactId
    provider: Literal["deepseek-official"]
    agent_model: Literal["deepseek-v4-flash"]
    user_model: Literal["deepseek/deepseek-v4-flash"]
    baseline_snapshot_id: ArtifactId
    candidate_count: int = Field(ge=3, le=6)
    update_source_trials: Literal[1]
    update_check_trials: Literal[1]
    selection_trials: Literal[1]
    release_trials: int = Field(ge=1)
    stable_success_required: int = Field(ge=1)
    min_asset_families: int = Field(ge=2)
    min_rejected_or_held_candidates: int = Field(ge=1)
    tau3_checkout: NonEmpty
    ahe_checkout: NonEmpty
    dsh_executable: NonEmpty
    dsh_home: NonEmpty
    dsh_profile: NonEmpty
    pricing_config: NonEmpty
    execution_protocol_config: NonEmpty | None = None
    study_plan_config: NonEmpty | None = None
    research_artifact_root: NonEmpty | None = None
    paid_execution_authorization_root: NonEmpty | None = None

    @model_validator(mode="after")
    def reliability_is_possible(self) -> FormalExperimentConfig:
        if self.stable_success_required > self.release_trials:
            raise ValueError("stable_success_required cannot exceed release_trials")
        if self.schema_version in {"1.1", "1.2"} and (
            self.execution_protocol_config is None or self.study_plan_config is None
        ):
            raise ValueError(
                "formal config 1.1 requires execution_protocol_config and study_plan_config"
            )
        if self.schema_version == "1.0" and (
            self.execution_protocol_config is not None or self.study_plan_config is not None
        ):
            raise ValueError("execution protocol and study plan require formal config 1.1")
        if self.schema_version == "1.0" and self.research_artifact_root is not None:
            raise ValueError("research_artifact_root requires formal config 1.1")
        if self.schema_version == "1.2" and self.paid_execution_authorization_root is None:
            raise ValueError(
                "formal config 1.2 requires paid_execution_authorization_root"
            )
        if self.schema_version == "1.2" and self.paid_execution_authorization_root != (
            f"runs/authorizations/{self.experiment_id}"
        ):
            raise ValueError(
                "paid_execution_authorization_root must be experiment-scoped"
            )
        if (
            self.schema_version != "1.2"
            and self.paid_execution_authorization_root is not None
        ):
            raise ValueError(
                "paid_execution_authorization_root requires formal config 1.2"
            )
        return self


class PaidExecutionAuthorization(StrictModel):
    """Content-addressed human scope for one paid experiment checkpoint."""

    schema_version: Literal["1.0"] = "1.0"
    authorization_id: ArtifactId
    experiment_id: ArtifactId
    scope: Literal["pre_release_checkpoint", "release_tail"]
    protocol_digest: Digest
    study_digest: Digest
    source_revision: NonEmpty
    authorized_stages: list[FormalStage] = Field(min_length=3, max_length=3)
    authorized_task_positions: int = Field(ge=1)
    external_updater_generation_authorized: bool
    selection_digest: Digest | None = None
    governed_candidate_id: ArtifactId | None = None
    authorized_by: NonEmpty
    authorized_at: UtcDateTime
    confirmation: Literal[
        "OWNER_AUTHORIZED_PRE_RELEASE_CHECKPOINT",
        "OWNER_AUTHORIZED_RELEASE_TAIL",
    ]
    authorization_digest: Digest

    @model_validator(mode="after")
    def scope_is_exact(self) -> PaidExecutionAuthorization:
        expected_stages = {
            "pre_release_checkpoint": [
                FormalStage.UPDATE_SOURCE,
                FormalStage.UPDATE_CHECK,
                FormalStage.SELECTION,
            ],
            "release_tail": [
                FormalStage.RELEASE_ID,
                FormalStage.RELEASE_OOD,
                FormalStage.REPLAY,
            ],
        }[self.scope]
        expected_confirmation = {
            "pre_release_checkpoint": "OWNER_AUTHORIZED_PRE_RELEASE_CHECKPOINT",
            "release_tail": "OWNER_AUTHORIZED_RELEASE_TAIL",
        }[self.scope]
        if self.authorized_stages != expected_stages:
            raise ValueError("paid authorization stages do not match its scope")
        if self.confirmation != expected_confirmation:
            raise ValueError("paid authorization confirmation does not match its scope")
        release_bound = (
            self.selection_digest is not None and self.governed_candidate_id is not None
        )
        if self.scope == "release_tail" and not release_bound:
            raise ValueError("Release authorization must bind the Selection result")
        if self.scope == "pre_release_checkpoint" and (
            self.selection_digest is not None or self.governed_candidate_id is not None
        ):
            raise ValueError("pre-Release authorization cannot predict Selection")
        if (
            self.external_updater_generation_authorized
            != (self.scope == "pre_release_checkpoint")
        ):
            raise ValueError(
                "only pre-Release authorization can authorize external Updater generation"
            )
        return self


class FormalPreflightReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: ArtifactId
    ready: bool
    checks: dict[NonEmpty, bool]
    missing: list[NonEmpty]
    code_revision: str | None
    pilot_task_count: int
    candidate_count: int
    dsh_version: str | None
    dsh_commit: Literal["141eb6fef83422698aef7a981029e843e8161534"] = DSH_COMMIT
    ahe_status: NonEmpty
    protocol_digest: Digest | None
    study_digest: Digest | None
    paid_execution_authorization_digest: Digest | None = None


def load_formal_config(path: Path) -> FormalExperimentConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read formal experiment config: {path}") from exc
    return FormalExperimentConfig.model_validate(raw)


def computed_paid_execution_authorization_digest(
    authorization: PaidExecutionAuthorization,
) -> str:
    return canonical_digest(
        authorization.model_dump(mode="python", exclude={"authorization_digest"})
    )


def load_paid_execution_authorization(path: Path) -> PaidExecutionAuthorization:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read paid execution authorization: {path}") from exc
    return PaidExecutionAuthorization.model_validate(raw)


def verify_paid_execution_authorization(
    path: Path,
    *,
    config: FormalExperimentConfig,
    protocol: FormalExecutionProtocol,
    study: BankingStudyPlan,
    source_revision: str,
    required_stage: FormalStage,
    selection_path: Path | None = None,
) -> PaidExecutionAuthorization:
    authorization = load_paid_execution_authorization(path)
    if (
        computed_paid_execution_authorization_digest(authorization)
        != authorization.authorization_digest
    ):
        raise ValueError("paid execution authorization digest mismatch")
    expected_scope = (
        "pre_release_checkpoint"
        if required_stage
        in {
            FormalStage.UPDATE_SOURCE,
            FormalStage.UPDATE_CHECK,
            FormalStage.SELECTION,
        }
        else "release_tail"
    )
    if (
        authorization.experiment_id != config.experiment_id
        or authorization.protocol_digest != protocol.protocol_digest
        or authorization.study_digest != study.study_digest
        or authorization.source_revision != source_revision
        or authorization.scope != expected_scope
        or required_stage not in authorization.authorized_stages
    ):
        raise ValueError("paid execution authorization identity or scope mismatch")
    expected_positions = sum(
        row.target_trials
        for row in study.matrix
        if row.stage in authorization.authorized_stages
    )
    if authorization.authorized_task_positions != expected_positions:
        raise ValueError("paid execution authorization task-position scope mismatch")
    if expected_scope == "release_tail":
        if selection_path is None:
            raise ValueError("Release authorization requires Selection evidence")
        selection_digest, governed_candidate_id = _verified_release_selection(
            selection_path
        )
        if (
            governed_candidate_id != authorization.governed_candidate_id
            or selection_digest != authorization.selection_digest
        ):
            raise ValueError("Release authorization conflicts with Selection evidence")
    return authorization


def create_paid_execution_authorization(
    project_root: Path,
    *,
    config_path: Path,
    scope: Literal["pre_release_checkpoint", "release_tail"],
    authorized_by: str,
    confirmation: str,
) -> tuple[PaidExecutionAuthorization, Path]:
    root = project_root.resolve()
    config = load_formal_config(_under(root, config_path))
    if config.schema_version != "1.2":
        raise ValueError("paid authorization requires formal config 1.2")
    expected_confirmation = {
        "pre_release_checkpoint": "OWNER_AUTHORIZED_PRE_RELEASE_CHECKPOINT",
        "release_tail": "OWNER_AUTHORIZED_RELEASE_TAIL",
    }[scope]
    if confirmation != expected_confirmation:
        raise ValueError(
            f"paid authorization requires exact confirmation: {expected_confirmation}"
        )
    contract = load_contract(root / "configs/objective_contract.yaml")
    verify_contract_digest(contract)
    split = SplitService(root / "configs/splits.yaml").verify()
    if split.split_digest is None:
        raise ValueError("verified split is missing its digest")
    pricing = load_pilot_pricing(_under(root, Path(config.pricing_config)))
    protocol = _verified_protocol(
        root,
        config,
        objective_digest=computed_contract_digest(contract),
        split_digest=split.split_digest,
        pricing=pricing,
    )
    if protocol is None or protocol.schema_version != "1.8":
        raise ValueError("paid authorization requires frozen protocol 1.8")
    study = _verified_study(root, config, protocol=protocol)
    if study.schema_version != "1.2":
        raise ValueError("paid authorization requires Study 1.2")
    source_revision = _code_revision(root)
    if source_revision is None:
        raise ValueError("paid authorization requires a source revision")
    stages = {
        "pre_release_checkpoint": [
            FormalStage.UPDATE_SOURCE,
            FormalStage.UPDATE_CHECK,
            FormalStage.SELECTION,
        ],
        "release_tail": [
            FormalStage.RELEASE_ID,
            FormalStage.RELEASE_OOD,
            FormalStage.REPLAY,
        ],
    }[scope]
    selection_digest = None
    governed_candidate_id = None
    selection_path = (
        root / "runs/experiments" / config.experiment_id / "selection.json"
    )
    if scope == "release_tail":
        hold_path = (
            root
            / "runs/experiments"
            / config.experiment_id
            / "selection_hold_outcome.json"
        )
        if hold_path.exists():
            raise ValueError("Selection HOLD permanently blocks Release authorization")
        selection_digest, governed_candidate_id = _verified_release_selection(
            selection_path
        )
    path = _paid_authorization_path(root, config, scope=scope)
    if path.exists():
        existing = verify_paid_execution_authorization(
            path,
            config=config,
            protocol=protocol,
            study=study,
            source_revision=source_revision,
            required_stage=stages[0],
            selection_path=selection_path if scope == "release_tail" else None,
        )
        if existing.authorized_by != authorized_by:
            raise ValueError("existing paid authorization belongs to another actor")
        return existing, path
    positions = sum(
        row.target_trials for row in study.matrix if row.stage in stages
    )
    identity = {
        "experiment_id": config.experiment_id,
        "scope": scope,
        "protocol_digest": protocol.protocol_digest,
        "study_digest": study.study_digest,
        "source_revision": source_revision,
    }
    suffix = canonical_digest(identity).removeprefix("sha256:")[:20].upper()
    authorization = PaidExecutionAuthorization(
        authorization_id=f"AUTH_{suffix}",
        experiment_id=config.experiment_id,
        scope=scope,
        protocol_digest=protocol.protocol_digest,
        study_digest=study.study_digest,
        source_revision=source_revision,
        authorized_stages=stages,
        authorized_task_positions=positions,
        external_updater_generation_authorized=(
            scope == "pre_release_checkpoint"
        ),
        selection_digest=selection_digest,
        governed_candidate_id=governed_candidate_id,
        authorized_by=authorized_by,
        authorized_at=datetime.now(UTC),
        confirmation=confirmation,
        authorization_digest="sha256:" + "0" * 64,
    )
    authorization = authorization.model_copy(
        update={
            "authorization_digest": computed_paid_execution_authorization_digest(
                authorization
            )
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(authorization) + b"\n")
    except FileExistsError as exc:
        raise ValueError(
            "paid authorization appeared concurrently; rerun to verify it"
        ) from exc
    return authorization, path


def inspect_formal_preflight(
    project_root: Path,
    *,
    config_path: Path,
) -> FormalPreflightReport:
    root = project_root.resolve()
    config = load_formal_config(_under(root, config_path))
    checks: dict[str, bool] = {}
    missing: list[str] = []

    contract = None
    try:
        contract = load_contract(root / "configs/objective_contract.yaml")
        verify_contract_digest(contract)
        checks["objective_frozen"] = True
    except (OSError, ValueError, ValidationError) as exc:
        checks["objective_frozen"] = False
        missing.append(f"objective_frozen:{exc}")

    split = None
    try:
        split = SplitService(root / "configs/splits.yaml").verify()
        checks["splits_frozen"] = True
    except (OSError, ValueError, ValidationError) as exc:
        checks["splits_frozen"] = False
        missing.append(f"splits_frozen:{exc}")

    if contract is not None and (
        contract.reliability.trials != config.release_trials
        or contract.reliability.stable_success_required != config.stable_success_required
    ):
        checks["reliability_matches_contract"] = False
        missing.append("reliability_matches_contract")
    else:
        checks["reliability_matches_contract"] = contract is not None

    code_revision = _code_revision(root)
    checks["code_revision"] = code_revision is not None
    if code_revision is None:
        missing.append("code_revision:cannot hash the reviewed source tree")

    pilot_task_count = _verified_pilot_task_count(root)
    checks["banking_pilot_evidence"] = 3 <= pilot_task_count <= 7
    if not checks["banking_pilot_evidence"]:
        missing.append("banking_pilot_evidence:run 3-7 frozen Pilot tasks first")

    pricing = load_pilot_pricing(_under(root, Path(config.pricing_config)))
    protocol = None
    if contract is not None and split is not None and split.split_digest is not None:
        try:
            protocol = _verified_protocol(
                root,
                config,
                objective_digest=computed_contract_digest(contract),
                split_digest=split.split_digest,
                pricing=pricing,
            )
            checks["execution_protocol_frozen"] = (
                protocol is not None and protocol.schema_version == "1.8"
            )
            if protocol is None:
                missing.append(
                    "execution_protocol_frozen:legacy config cannot start a new paid run"
                )
            elif protocol.schema_version != "1.8":
                missing.append(
                    "execution_protocol_frozen:new paid work requires protocol 1.8 "
                    "with Reply v5, direct task/session lineage, and frozen-price "
                    "cost-authority, Cost Gate input, and evaluator-correction pins"
                )
        except (OSError, ValueError, ValidationError) as exc:
            checks["execution_protocol_frozen"] = False
            missing.append(f"execution_protocol_frozen:{exc}")
    else:
        checks["execution_protocol_frozen"] = False
        missing.append("execution_protocol_frozen:objective or split is unavailable")
    study = None
    if protocol is not None:
        try:
            study = _verified_study(root, config, protocol=protocol)
            checks["study_plan_frozen"] = study.schema_version == "1.2"
            if study.schema_version != "1.2" or config.schema_version != "1.2":
                missing.append(
                    "study_plan_frozen:new paid work requires formal config and "
                    "Study schema 1.2 with A0-bound Selection and abstention"
                )
        except (OSError, ValueError, ValidationError) as exc:
            checks["study_plan_frozen"] = False
            missing.append(f"study_plan_frozen:{exc}")
    else:
        checks["study_plan_frozen"] = False
        missing.append("study_plan_frozen:execution protocol is unavailable")
    paid_authorization = None
    if (
        protocol is not None
        and study is not None
        and code_revision is not None
        and config.schema_version == "1.2"
        and study.schema_version == "1.2"
    ):
        try:
            paid_authorization = verify_paid_execution_authorization(
                _paid_authorization_path(
                    root,
                    config,
                    scope="pre_release_checkpoint",
                ),
                config=config,
                protocol=protocol,
                study=study,
                source_revision=code_revision,
                required_stage=FormalStage.UPDATE_SOURCE,
            )
            checks["paid_execution_authorized"] = True
        except (OSError, ValueError, ValidationError) as exc:
            checks["paid_execution_authorized"] = False
            missing.append(f"paid_execution_authorized:{exc}")
    else:
        checks["paid_execution_authorized"] = False
        missing.append(
            "paid_execution_authorized:requires current Protocol, Study, source, "
            "and an explicit Owner authorization artifact"
        )
    pilot = DshTau3PilotConfig(
        dsh_executable=_under(root, Path(config.dsh_executable)),
        dsh_home=_under(root, Path(config.dsh_home)),
        patch_path=root / "examples/tau3-banking/dsh-tau3.patch.yml",
        session_root=root / "runs/dsh/native-sessions",
        profile=config.dsh_profile,
        provider=config.provider,
        model=config.agent_model,
        experiment_namespace=f"{config.experiment_id}-preflight",
        pricing=pricing,
        turn_timeout_seconds=protocol.turn_timeout_seconds if protocol else 360,
        dsh_stream_idle_timeout_ms=(
            protocol.dsh_stream_idle_timeout_ms
            if protocol
            and protocol.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8"}
            and protocol.dsh_stream_idle_timeout_ms is not None
            else 300_000
        ),
        provider_max_retries=(
            protocol.dsh_provider_max_retries
            if protocol and protocol.dsh_provider_max_retries is not None
            else 1
        ),
        provider_retry_delay_ms=(
            protocol.dsh_provider_retry_delay_ms
            if protocol and protocol.dsh_provider_retry_delay_ms is not None
            else 500
        ),
        agent_temperature=(
            protocol.agent_temperature
            if protocol and protocol.agent_temperature is not None
            else 0
        ),
        agent_max_output_tokens=(
            protocol.agent_max_output_tokens
            if protocol and protocol.agent_max_output_tokens is not None
            else 4096
        ),
        dsh_tau3_protocol_version=(
            protocol.dsh_tau3_protocol_version
            if protocol and protocol.dsh_tau3_protocol_version is not None
            else DSH_TAU3_PROTOCOL_CURRENT
        ),
        reply_normalization_policy=(
            protocol.reply_normalization_policy
            if protocol and protocol.reply_normalization_policy is not None
            else DSH_TAU3_REPLY_POLICY_CURRENT
        ),
        runner_failure_usage_policy=(
            protocol.runner_failure_usage_policy
            if protocol and protocol.runner_failure_usage_policy is not None
            else DSH_TAU3_FAILURE_USAGE_POLICY_CURRENT
        ),
        empty_final_repair_policy=(
            protocol.empty_final_repair_policy
            if protocol
            and protocol.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8"}
            and protocol.empty_final_repair_policy is not None
            else DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT
        ),
        empty_final_repair_limit=(
            protocol.empty_final_repair_limit
            if protocol
            and protocol.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8"}
            and protocol.empty_final_repair_limit is not None
            else DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT
        ),
        network_route_policy=(
            protocol.network_route_policy
            if protocol
            and protocol.schema_version in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
            else "inherit"
        ),
        global_task_attempt_limit=(
            protocol.global_task_attempt_limit
            if protocol
            and protocol.schema_version in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
            else None
        ),
        task_attempt_ledger_schema_version=(
            protocol.task_attempt_ledger_schema_version
            if protocol
            and protocol.schema_version in {"1.5", "1.6", "1.7", "1.8"}
            and protocol.task_attempt_ledger_schema_version is not None
            else "1.0"
        ),
        model_usage_ledger_schema_version=(
            protocol.model_usage_ledger_schema_version
            if protocol
            and protocol.schema_version in {"1.5", "1.6", "1.7", "1.8"}
            and protocol.model_usage_ledger_schema_version is not None
            else "1.1"
        ),
        evaluator_overlay_path=(
            _under(root, Path(protocol.evaluator_overlay_artifact))
            if protocol
            and protocol.schema_version == "1.8"
            and protocol.evaluator_overlay_artifact is not None
            else None
        ),
    )
    dsh_adapter = DshTau3Adapter(
        root,
        checkout=_under(root, Path(config.tau3_checkout)),
        pilot=pilot,
    )
    dsh_health = dsh_adapter.doctor()
    checks["dsh_tau3_ready"] = dsh_health.ready
    if not dsh_health.ready:
        missing.append(f"dsh_tau3_ready:{dsh_health.remediation}")

    policy = load_mutation_policy(root / "configs/mutation_policy.yaml")
    manifest = load_asset_manifest(root / "configs/harness_assets.yaml")
    updater = AheAdapter(
        root,
        registry=CandidateRegistry(
            root,
            CandidateChecker(root, manifest, policy, freeze_trust_kernel(root, policy)),
        ),
        runner=AheExternalRunner(
            _under(root, Path(config.ahe_checkout)),
            project_root=root,
            timeout_seconds=(
                protocol.updater_timeout_seconds
                if protocol and protocol.updater_timeout_seconds is not None
                else 3600
            ),
            max_iterations=(
                protocol.updater_max_iterations
                if protocol and protocol.updater_max_iterations is not None
                else 80
            ),
            max_output_tokens=(
                protocol.updater_max_output_tokens
                if protocol and protocol.updater_max_output_tokens is not None
                else 8000
            ),
            temperature=(
                protocol.updater_temperature
                if protocol and protocol.updater_temperature is not None
                else Decimal("0.3")
            ),
            max_retries=(
                protocol.updater_max_retries
                if protocol and protocol.updater_max_retries is not None
                else 0
            ),
            retry_delay_seconds=(
                protocol.updater_retry_delay_seconds
                if protocol and protocol.updater_retry_delay_seconds is not None
                else Decimal(1)
            ),
            input_price_per_million=pricing.input_cache_miss,
            cache_read_price_per_million=pricing.input_cache_hit,
            output_price_per_million=pricing.output,
            network_route_policy=(
                protocol.network_route_policy
                if protocol and protocol.network_route_policy is not None
                else "inherit"
            ),
        ),
    )
    ahe_health = updater.doctor()
    checks["ahe_ready"] = ahe_health.ready
    if not ahe_health.ready:
        missing.append(f"ahe_ready:{ahe_health.remediation}")

    candidate_count = sum(
        any((directory / "events").glob("*.json"))
        for directory in (root / "candidates").glob("*")
        if directory.is_dir()
    )
    checks["credential_process_boundary"] = bool(
        os.environ.get("DEEPSEEK_API_KEY", "").strip()
    )
    if not checks["credential_process_boundary"]:
        missing.append("credential_process_boundary:export DEEPSEEK_API_KEY in this process")

    return FormalPreflightReport(
        experiment_id=config.experiment_id,
        ready=all(checks.values()),
        checks=checks,
        missing=sorted(set(missing)),
        code_revision=code_revision,
        pilot_task_count=pilot_task_count,
        candidate_count=candidate_count,
        dsh_version=dsh_health.version,
        ahe_status=ahe_health.status,
        protocol_digest=protocol.protocol_digest if protocol else None,
        study_digest=study.study_digest if study else None,
        paid_execution_authorization_digest=(
            paid_authorization.authorization_digest if paid_authorization else None
        ),
    )


class FormalExperimentService:
    """Prepare the immutable A0 snapshot and execute one formal evidence stage."""

    def __init__(self, project_root: Path, *, config_path: Path) -> None:
        self.root = project_root.resolve()
        self.config = load_formal_config(_under(self.root, config_path))
        self.splits = SplitService(self.root / "configs/splits.yaml")
        self.snapshots = SnapshotManager(self.root)

    def ensure_baseline(self, *, require_active: bool = True) -> str:
        contract = load_contract(self.root / "configs/objective_contract.yaml")
        verify_contract_digest(contract)
        split = self.splits.verify()
        if split.split_digest is None:
            raise ValueError("verified split is missing its digest")
        pricing = load_pilot_pricing(
            _under(self.root, Path(self.config.pricing_config))
        )
        if self.config.schema_version in {"1.1", "1.2"}:
            protocol = self._protocol(
                objective_digest=computed_contract_digest(contract),
                split_digest=split.split_digest,
                pricing=pricing,
            )
            if protocol is None:
                raise ValueError("formal config 1.1 has no execution protocol")
            _verified_study(self.root, self.config, protocol=protocol)
        code_revision = _code_revision(self.root)
        if code_revision is None:
            raise ValueError("cannot hash the reviewed source tree")
        manifest = load_asset_manifest(self.root / "configs/harness_assets.yaml")
        harness_paths = sorted(
            path.relative_to(self.root).as_posix()
            for path in (self.root / "harness").rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        try:
            existing = self.snapshots.verify(self.config.baseline_snapshot_id)
        except SnapshotIntegrityError:
            existing = None
        if existing is None:
            create = (
                self.snapshots.create_evaluation_baseline
                if self.config.schema_version in {"1.1", "1.2"}
                else self.snapshots.create_baseline
            )
            create_kwargs = (
                {"allow_reviewed_harness_revision": True}
                if self.config.schema_version == "1.2"
                else {}
            )
            baseline = create(
                snapshot_id=self.config.baseline_snapshot_id,
                harness_paths=harness_paths,
                model_id=f"{self.config.provider}/{self.config.agent_model}",
                objective_digest=computed_contract_digest(contract),
                split_digest=split.split_digest,
                asset_manifest_digest=canonical_digest(manifest),
                code_revision=code_revision,
                runtime_host=RuntimeHost.DEEPSEEK_HARNESS.value,
                runtime_version=f"deepseek-harness@{DSH_VERSION}",
                created_at=datetime.now(UTC),
                **create_kwargs,
            )
        else:
            baseline = existing
        expected = {
            "model_id": f"{self.config.provider}/{self.config.agent_model}",
            "objective_digest": computed_contract_digest(contract),
            "split_digest": split.split_digest,
            "asset_manifest_digest": canonical_digest(manifest),
            "code_revision": code_revision,
        }
        actual = {key: getattr(baseline, key) for key in expected}
        if actual != expected:
            raise ValueError("existing A0 snapshot does not match the frozen formal inputs")
        if require_active:
            active = self.snapshots.active_snapshot()
            if self.config.schema_version in {"1.0", "1.1"}:
                active = self.snapshots.verify_active_live()
            else:
                self.snapshots.verify_live(baseline.snapshot_id)
            if self.config.schema_version == "1.0" and active.snapshot_id != baseline.snapshot_id:
                raise ValueError("formal A0 is not the active parent snapshot")
            if (
                self.config.schema_version == "1.1"
                and active.harness_files != baseline.harness_files
            ):
                raise ValueError(
                    "evaluation A0 does not match the active live harness bytes"
                )
        return baseline.snapshot_id

    def run_stage(
        self,
        stage: FormalStage,
        *,
        snapshot_id: str,
        existing_only: bool = False,
    ) -> FormalBatchRunResult:
        contract = load_contract(self.root / "configs/objective_contract.yaml")
        verify_contract_digest(contract)
        split = self.splits.verify()
        if split.split_digest is None:
            raise ValueError("verified split is missing its digest")
        snapshot = self.snapshots.verify(snapshot_id)
        if (
            snapshot.objective_digest != computed_contract_digest(contract)
            or snapshot.split_digest != split.split_digest
            or snapshot.model_id
            != f"{self.config.provider}/{self.config.agent_model}"
        ):
            raise ValueError("snapshot does not match the frozen formal execution context")
        task_ids = self._task_ids(stage)
        trials = self._trials(stage)
        pricing = load_pilot_pricing(
            _under(self.root, Path(self.config.pricing_config))
        )
        protocol = self._protocol(
            objective_digest=computed_contract_digest(contract),
            split_digest=split.split_digest,
            pricing=pricing,
            allow_runtime_binding_mismatch=existing_only,
        )
        if not existing_only and (
            self.config.schema_version != "1.2"
            or protocol is None
            or protocol.schema_version != "1.8"
        ):
            raise PaidExecutionAuthorizationError(
                "new paid formal execution requires formal config 1.2 and frozen "
                "protocol 1.8 with Reply v5, direct lineage, frozen-price cost "
                "calibration, direct Agent+User Cost Gate input, and evaluator "
                "correction"
            )
        study = None
        if protocol is not None:
            study = _verified_study(self.root, self.config, protocol=protocol)
        if not existing_only:
            if study is None or study.schema_version != "1.2":
                raise PaidExecutionAuthorizationError(
                    "new paid formal execution requires Study 1.2 A0-bound Selection"
                )
            source_revision = _code_revision(self.root)
            if source_revision is None or snapshot.code_revision != source_revision:
                raise PaidExecutionAuthorizationError(
                    "paid execution source differs from the frozen Snapshot"
                )
            scope = (
                "pre_release_checkpoint"
                if stage
                in {
                    FormalStage.UPDATE_SOURCE,
                    FormalStage.UPDATE_CHECK,
                    FormalStage.SELECTION,
                }
                else "release_tail"
            )
            if scope == "release_tail" and (
                self.root
                / "runs/experiments"
                / self.config.experiment_id
                / "selection_hold_outcome.json"
            ).exists():
                raise PaidExecutionAuthorizationError(
                    "Selection HOLD permanently blocks paid Release stages"
                )
            try:
                verify_paid_execution_authorization(
                    _paid_authorization_path(self.root, self.config, scope=scope),
                    config=self.config,
                    protocol=protocol,
                    study=study,
                    source_revision=source_revision,
                    required_stage=stage,
                    selection_path=(
                        self.root
                        / "runs/experiments"
                        / self.config.experiment_id
                        / "selection.json"
                        if scope == "release_tail"
                        else None
                    ),
                )
            except (OSError, ValueError, ValidationError) as exc:
                raise PaidExecutionAuthorizationError(str(exc)) from exc
        spec_payload = dict(
            experiment_id=self.config.experiment_id,
            stage=stage,
            pool=(Pool.UPDATE_SOURCE if stage is FormalStage.REPLAY else Pool(stage.value)),
            snapshot_id=snapshot.snapshot_id,
            candidate_id=snapshot.candidate_id,
            task_ids=task_ids,
            trials=trials,
            agent_model=f"{self.config.provider}/{self.config.agent_model}",
            user_model=self.config.user_model,
            objective_digest=snapshot.objective_digest,
            split_digest=snapshot.split_digest,
            benchmark_commit=TAU3_COMMIT,
            initial_state_digests=self._initial_state_digests(task_ids),
        )
        if protocol is not None:
            spec_payload["protocol_digest"] = protocol.protocol_digest
        spec = FormalBatchSpec.model_validate(spec_payload)
        turn_timeout_seconds = protocol.turn_timeout_seconds if protocol else 360
        max_concurrency = protocol.max_concurrency if protocol else 1
        max_retries = protocol.max_retries if protocol else 1
        retry_delay_seconds = (
            str(protocol.retry_delay_seconds) if protocol else "1"
        )
        pilot = DshTau3PilotConfig(
            dsh_executable=_under(self.root, Path(self.config.dsh_executable)),
            dsh_home=_under(self.root, Path(self.config.dsh_home)),
            patch_path=self.root / "examples/tau3-banking/dsh-tau3.patch.yml",
            session_root=self.root / "runs/dsh/native-sessions",
            profile=self.config.dsh_profile,
            provider=self.config.provider,
            model=self.config.agent_model,
            experiment_namespace=spec.run_name,
            pricing=pricing,
            harness_root=self.root / "snapshots" / snapshot.snapshot_id / "files",
            turn_timeout_seconds=turn_timeout_seconds,
            dsh_stream_idle_timeout_ms=(
                protocol.dsh_stream_idle_timeout_ms
                if protocol
                and protocol.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8"}
                and protocol.dsh_stream_idle_timeout_ms is not None
                else min(300_000, turn_timeout_seconds * 1000 - 1_000)
            ),
            provider_max_retries=(
                protocol.dsh_provider_max_retries
                if protocol and protocol.dsh_provider_max_retries is not None
                else 1
            ),
            provider_retry_delay_ms=(
                protocol.dsh_provider_retry_delay_ms
                if protocol and protocol.dsh_provider_retry_delay_ms is not None
                else 500
            ),
            agent_temperature=(
                protocol.agent_temperature
                if protocol and protocol.agent_temperature is not None
                else 0
            ),
            agent_max_output_tokens=(
                protocol.agent_max_output_tokens
                if protocol and protocol.agent_max_output_tokens is not None
                else 4096
            ),
            dsh_tau3_protocol_version=(
                protocol.dsh_tau3_protocol_version
                if protocol and protocol.dsh_tau3_protocol_version is not None
                else DSH_TAU3_PROTOCOL_CURRENT
            ),
            reply_normalization_policy=(
                protocol.reply_normalization_policy
                if protocol and protocol.reply_normalization_policy is not None
                else DSH_TAU3_REPLY_POLICY_CURRENT
            ),
            runner_failure_usage_policy=(
                protocol.runner_failure_usage_policy
                if protocol and protocol.runner_failure_usage_policy is not None
                else DSH_TAU3_FAILURE_USAGE_POLICY_CURRENT
            ),
            empty_final_repair_policy=(
                protocol.empty_final_repair_policy
                if protocol
                and protocol.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8"}
                and protocol.empty_final_repair_policy is not None
                else DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT
            ),
            empty_final_repair_limit=(
                protocol.empty_final_repair_limit
                if protocol
                and protocol.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8"}
                and protocol.empty_final_repair_limit is not None
                else DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT
            ),
            network_route_policy=(
                protocol.network_route_policy
                if protocol
                and protocol.schema_version
                in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
                else "inherit"
            ),
            global_task_attempt_limit=(
                protocol.global_task_attempt_limit
                if protocol
                and protocol.schema_version
                in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
                else None
            ),
            task_attempt_ledger_schema_version=(
                protocol.task_attempt_ledger_schema_version
                if protocol
                and protocol.schema_version in {"1.5", "1.6", "1.7", "1.8"}
                and protocol.task_attempt_ledger_schema_version is not None
                else "1.0"
            ),
            model_usage_ledger_schema_version=(
                protocol.model_usage_ledger_schema_version
                if protocol
                and protocol.schema_version in {"1.5", "1.6", "1.7", "1.8"}
                and protocol.model_usage_ledger_schema_version is not None
                else "1.1"
            ),
            evaluator_overlay_path=(
                _under(self.root, Path(protocol.evaluator_overlay_artifact))
                if protocol
                and protocol.schema_version == "1.8"
                and protocol.evaluator_overlay_artifact is not None
                else None
            ),
        )
        adapter = DshTau3Adapter(
            self.root,
            checkout=_under(self.root, Path(self.config.tau3_checkout)),
            pilot=pilot,
        )
        return FormalBatchRunner(
            self.root,
            DshFormalBatchExecutor(
                self.root,
                adapter,
                existing_only=existing_only,
                max_concurrency=max_concurrency,
                max_retries=max_retries,
                retry_delay_seconds=retry_delay_seconds,
                seed=(protocol.benchmark_seed if protocol else 300) or 300,
                max_steps=(protocol.max_steps if protocol else 200) or 200,
                max_errors=(protocol.max_errors if protocol else 10) or 10,
                simulation_timeout_seconds=(
                    (protocol.simulation_timeout_seconds if protocol else 1800)
                    or 1800
                ),
                agent_temperature=str(
                    (protocol.agent_temperature if protocol else 0) or 0
                ),
                user_temperature=str(
                    (protocol.user_temperature if protocol else 0) or 0
                ),
                user_model_max_retries=(
                    (protocol.user_model_max_retries if protocol else 1)
                    if protocol is None or protocol.user_model_max_retries is not None
                    else 1
                ),
                capture_user_attempt_usage=bool(
                    protocol
                    and protocol.schema_version
                    in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
                ),
                global_task_attempt_limit=(
                    protocol.global_task_attempt_limit
                    if protocol
                    and protocol.schema_version
                    in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
                    else None
                ),
                cost_gate_scope=(
                    "valid_runs"
                    if protocol
                    and protocol.schema_version
                    in {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8"}
                    else "whole_attempt"
                ),
            ),
        ).run(spec)

    def verify_updater_generation_authorization(
        self,
        *,
        snapshot_id: str,
    ) -> PaidExecutionAuthorization:
        """Re-verify the pre-Release scope before any external Updater call."""

        contract = load_contract(self.root / "configs/objective_contract.yaml")
        verify_contract_digest(contract)
        split = self.splits.verify()
        if split.split_digest is None:
            raise PaidExecutionAuthorizationError(
                "Updater authorization requires a verified frozen split"
            )
        snapshot = self.snapshots.verify(snapshot_id)
        pricing = load_pilot_pricing(
            _under(self.root, Path(self.config.pricing_config))
        )
        protocol = self._protocol(
            objective_digest=computed_contract_digest(contract),
            split_digest=split.split_digest,
            pricing=pricing,
        )
        if (
            self.config.schema_version != "1.2"
            or protocol is None
            or protocol.schema_version != "1.8"
        ):
            raise PaidExecutionAuthorizationError(
                "external Updater generation requires formal config 1.2 and "
                "frozen protocol 1.8"
            )
        study = _verified_study(self.root, self.config, protocol=protocol)
        if study.schema_version != "1.2":
            raise PaidExecutionAuthorizationError(
                "external Updater generation requires Study 1.2"
            )
        source_revision = _code_revision(self.root)
        if source_revision is None or snapshot.code_revision != source_revision:
            raise PaidExecutionAuthorizationError(
                "Updater execution source differs from the frozen Snapshot"
            )
        try:
            authorization = verify_paid_execution_authorization(
                _paid_authorization_path(
                    self.root,
                    self.config,
                    scope="pre_release_checkpoint",
                ),
                config=self.config,
                protocol=protocol,
                study=study,
                source_revision=source_revision,
                required_stage=FormalStage.UPDATE_SOURCE,
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise PaidExecutionAuthorizationError(
                "external Updater generation lacks exact pre-Release Owner "
                f"authorization: {exc}"
            ) from exc
        if not authorization.external_updater_generation_authorized:
            raise PaidExecutionAuthorizationError(
                "pre-Release authorization excludes external Updater generation"
            )
        return authorization

    def _protocol(
        self,
        *,
        objective_digest: str,
        split_digest: str,
        pricing,
        allow_runtime_binding_mismatch: bool = False,
    ) -> FormalExecutionProtocol | None:
        return _verified_protocol(
            self.root,
            self.config,
            objective_digest=objective_digest,
            split_digest=split_digest,
            pricing=pricing,
            allow_runtime_binding_mismatch=allow_runtime_binding_mismatch,
        )

    def _task_ids(self, stage: FormalStage) -> list[str]:
        split = self.splits.verify()
        if stage is FormalStage.REPLAY:
            return list(split.replay_task_ids)
        pool = Pool(stage.value)
        manifest_path = _under(self.root, Path(split.pools[pool].manifest))
        try:
            manifest = PoolManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot load the frozen {pool.value} manifest") from exc
        return [task.task_id for task in manifest.tasks]

    def _trials(self, stage: FormalStage) -> int:
        return {
            FormalStage.UPDATE_SOURCE: self.config.update_source_trials,
            FormalStage.UPDATE_CHECK: self.config.update_check_trials,
            FormalStage.SELECTION: self.config.selection_trials,
            FormalStage.RELEASE_ID: self.config.release_trials,
            FormalStage.RELEASE_OOD: self.config.release_trials,
            FormalStage.REPLAY: self.config.release_trials,
        }[stage]

    def _initial_state_digests(self, task_ids: list[str]) -> dict[str, str]:
        path = _under(self.root, Path(self.config.tau3_checkout)) / (
            "data/tau2/domains/banking_knowledge/tasks.json"
        )
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("cannot read the pinned τ³ task catalog") from exc
        if not isinstance(raw, list):
            raise ValueError("pinned τ³ task catalog must be a list")
        tasks = {
            item.get("id"): item
            for item in raw
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if not set(task_ids).issubset(tasks):
            raise ValueError("a frozen task is missing from the pinned τ³ catalog")
        return {
            task_id: canonical_digest(
                {"task_id": task_id, "initial_state": tasks[task_id].get("initial_state")}
            )
            for task_id in task_ids
        }


def _verified_pilot_task_count(root: Path) -> int:
    task_ids: set[str] = set()
    for path in (root / "runs/evidence_joins").glob("PEJ_*.json"):
        try:
            join = PilotEvidenceJoin.model_validate_json(path.read_text(encoding="utf-8"))
            tau = RunRecord.model_validate_json(
                (root / "runs/normalized" / f"{join.tau_run_id}.json").read_text(
                    encoding="utf-8"
                )
            )
            dsh = RunRecord.model_validate_json(
                (root / "runs/normalized" / f"{join.dsh_run_id}.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, ValueError):
            continue
        if (
            tau.pool is Pool.PILOT
            and dsh.pool is Pool.PILOT
            and tau.task_id == join.task_id == dsh.task_id
            and tau.trial_index == join.trial_index == dsh.trial_index
            and tau.success == join.outcome_success == dsh.success
        ):
            task_ids.add(join.task_id)
    return len(task_ids)


def _verified_protocol(
    root: Path,
    config: FormalExperimentConfig,
    *,
    objective_digest: str,
    split_digest: str,
    pricing: PilotPricingConfig,
    allow_runtime_binding_mismatch: bool = False,
) -> FormalExecutionProtocol | None:
    if config.execution_protocol_config is None:
        return None
    protocol = load_execution_protocol(
        _under(root, Path(config.execution_protocol_config))
    )
    expected = {
        "experiment_id": config.experiment_id,
        "objective_digest": objective_digest,
        "split_digest": split_digest,
        "benchmark_commit": TAU3_COMMIT,
        "agent_model": f"{config.provider}/{config.agent_model}",
        "user_model": config.user_model,
        "pricing_digest": canonical_digest(pricing),
    }
    actual = {key: getattr(protocol, key) for key in expected}
    if actual != expected:
        mismatches = sorted(key for key in expected if actual[key] != expected[key])
        raise ValueError(
            "execution protocol conflicts with formal inputs: " + ", ".join(mismatches)
        )
    if protocol.schema_version in {
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "1.7",
        "1.8",
    }:
        calibration_path = _under(
            root,
            Path(protocol.execution_calibration_artifact or "missing"),
        )
        try:
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("cannot read execution calibration evidence") from exc
        if not isinstance(calibration, dict):
            raise ValueError("execution calibration evidence must be a JSON object")
        declared = calibration.pop("artifact_digest", None)
        computed = canonical_digest(calibration)
        if (
            declared != protocol.execution_calibration_digest
            or computed != protocol.execution_calibration_digest
        ):
            raise ValueError("execution calibration evidence digest mismatch")
    if protocol.schema_version in {"1.5", "1.6", "1.7", "1.8"}:
        lineage_path = _under(
            root,
            Path(protocol.reply_lineage_calibration_artifact or "missing"),
        )
        lineage = load_reply_lineage_calibration(lineage_path)
        if lineage.artifact_digest != protocol.reply_lineage_calibration_digest:
            raise ValueError("reply-lineage calibration evidence digest mismatch")
        expected_lineage_pins = {
            "reply_normalization_policy": protocol.reply_normalization_policy,
            "task_attempt_ledger_schema_version": (
                protocol.task_attempt_ledger_schema_version
            ),
            "model_usage_ledger_schema_version": (
                protocol.model_usage_ledger_schema_version
            ),
            "task_attempt_session_binding_policy": (
                protocol.task_attempt_session_binding_policy
            ),
            "model_call_task_identity_policy": protocol.model_call_task_identity_policy,
        }
        actual_lineage_pins = {
            key: getattr(lineage, key) for key in expected_lineage_pins
        }
        if actual_lineage_pins != expected_lineage_pins:
            raise ValueError("reply-lineage calibration conflicts with protocol pins")
        source_path = _under(root, Path(lineage.source_diagnosis_artifact))
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("cannot read reply-lineage source diagnosis") from exc
        if not isinstance(source, dict):
            raise ValueError("reply-lineage source diagnosis must be a JSON object")
        declared_source = source.pop("artifact_digest", None)
        if (
            declared_source != lineage.source_diagnosis_digest
            or canonical_digest(source) != lineage.source_diagnosis_digest
        ):
            raise ValueError("reply-lineage source diagnosis digest mismatch")
        for relative, expected_digest in lineage.runtime_bindings.items():
            runtime_path = _under(root, Path(relative))
            if (
                not allow_runtime_binding_mismatch
                and (
                    not runtime_path.is_file()
                    or file_digest(runtime_path) != expected_digest
                )
            ):
                raise ValueError(
                    f"reply-lineage runtime binding mismatch: {relative}"
                )
    if protocol.schema_version in {"1.6", "1.7", "1.8"}:
        cost_path = _under(
            root,
            Path(protocol.cost_lineage_calibration_artifact or "missing"),
        )
        cost = load_cost_lineage_calibration(cost_path)
        if cost.artifact_digest != protocol.cost_lineage_calibration_digest:
            raise ValueError("cost-lineage calibration evidence digest mismatch")
        expected_cost_pins = {
            "pricing_digest": protocol.pricing_digest,
            "cost_authority_policy": protocol.cost_authority_policy,
            "valid_cost_lineage_policy": protocol.valid_cost_lineage_policy,
            "raw_cost_evidence_policy": protocol.raw_cost_evidence_policy,
            "positive_token_zero_cost_policy": (
                protocol.positive_token_zero_cost_policy
            ),
        }
        if protocol.schema_version in {"1.7", "1.8"}:
            expected_cost_pins["cost_gate_input_policy"] = (
                protocol.cost_gate_input_policy
            )
        actual_cost_pins = {
            key: getattr(cost, key) for key in expected_cost_pins
        }
        if actual_cost_pins != expected_cost_pins:
            raise ValueError("cost-lineage calibration conflicts with protocol pins")
        incident_path = _under(root, Path(cost.source_incident_artifact))
        try:
            incident = json.loads(incident_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("cannot read cost-lineage source incident") from exc
        if not isinstance(incident, dict):
            raise ValueError("cost-lineage source incident must be a JSON object")
        declared_incident = incident.pop("artifact_digest", None)
        if (
            declared_incident != cost.source_incident_digest
            or canonical_digest(incident) != cost.source_incident_digest
        ):
            raise ValueError("cost-lineage source incident digest mismatch")
        for relative, expected_digest in cost.runtime_bindings.items():
            runtime_path = _under(root, Path(relative))
            if (
                not allow_runtime_binding_mismatch
                and (
                    not runtime_path.is_file()
                    or file_digest(runtime_path) != expected_digest
                )
            ):
                raise ValueError(
                    f"cost-lineage runtime binding mismatch: {relative}"
                )
    if protocol.schema_version == "1.8":
        overlay_path = _under(
            root,
            Path(protocol.evaluator_overlay_artifact or "missing"),
        )
        overlay = load_evaluator_overlay(overlay_path)
        if overlay.overlay_digest != protocol.evaluator_overlay_digest:
            raise ValueError("evaluator overlay evidence digest mismatch")
        if overlay.benchmark_commit != protocol.benchmark_commit:
            raise ValueError("evaluator overlay benchmark commit mismatch")
        verify_evaluator_overlay_sources(
            overlay,
            checkout=_under(root, Path(config.tau3_checkout)),
        )
        incident_path = _under(
            root,
            Path(protocol.eval_incident_artifact or "missing"),
        )
        try:
            eval_incident = json.loads(incident_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("cannot read evaluator incident evidence") from exc
        if not isinstance(eval_incident, dict):
            raise ValueError("evaluator incident evidence must be a JSON object")
        declared_eval_incident = eval_incident.pop("artifact_digest", None)
        if (
            declared_eval_incident != protocol.eval_incident_digest
            or canonical_digest(eval_incident) != protocol.eval_incident_digest
        ):
            raise ValueError("evaluator incident evidence digest mismatch")
        if (
            overlay.incident_artifact != protocol.eval_incident_artifact
            or overlay.incident_digest != protocol.eval_incident_digest
        ):
            raise ValueError("evaluator overlay conflicts with incident pins")
        evaluator_calibration_path = _under(
            root,
            Path(
                protocol.evaluator_correction_calibration_artifact or "missing"
            ),
        )
        evaluator_calibration = load_evaluator_correction_calibration(
            evaluator_calibration_path
        )
        if (
            evaluator_calibration.artifact_digest
            != protocol.evaluator_correction_calibration_digest
        ):
            raise ValueError("evaluator correction calibration digest mismatch")
        expected_evaluator_pins = {
            "source_incident_artifact": protocol.eval_incident_artifact,
            "source_incident_digest": protocol.eval_incident_digest,
            "evaluator_overlay_artifact": protocol.evaluator_overlay_artifact,
            "evaluator_overlay_digest": protocol.evaluator_overlay_digest,
            "evaluator_conflict_policy": protocol.evaluator_conflict_policy,
            "evaluator_correction_policy": protocol.evaluator_correction_policy,
        }
        actual_evaluator_pins = {
            key: getattr(evaluator_calibration, key)
            for key in expected_evaluator_pins
        }
        if actual_evaluator_pins != expected_evaluator_pins:
            raise ValueError("evaluator calibration conflicts with protocol pins")
        if set(evaluator_calibration.affected_task_ids) != set(
            overlay.affected_task_ids
        ):
            raise ValueError("evaluator calibration affected tasks mismatch")
        for relative, expected_digest in evaluator_calibration.runtime_bindings.items():
            runtime_path = _under(root, Path(relative))
            if (
                not allow_runtime_binding_mismatch
                and (
                    not runtime_path.is_file()
                    or file_digest(runtime_path) != expected_digest
                )
            ):
                raise ValueError(
                    f"evaluator correction runtime binding mismatch: {relative}"
                )
    return protocol


def _verified_study(
    root: Path,
    config: FormalExperimentConfig,
    *,
    protocol: FormalExecutionProtocol,
) -> BankingStudyPlan:
    if config.study_plan_config is None:
        raise ValueError("formal config has no frozen study plan")
    study = load_study_plan(_under(root, Path(config.study_plan_config)))
    if study.experiment_id != config.experiment_id:
        raise ValueError("study plan experiment_id conflicts with formal config")
    if study.protocol_digest != protocol.protocol_digest:
        raise ValueError("study plan is not bound to the frozen execution protocol")
    return study


def _code_revision(root: Path) -> str | None:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        paths = sorted(item.decode("utf-8") for item in listed.split(b"\0") if item)
        files = {
            relative: file_digest(root / relative)
            for relative in paths
            if _is_execution_source(relative)
            and (root / relative).is_file()
            and not (root / relative).is_symlink()
        }
    except (OSError, UnicodeDecodeError):
        return None
    return f"tree:{canonical_digest(files)}" if files else None


def _is_execution_source(relative: str) -> bool:
    """Keep generated evidence and publication prose out of runtime identity."""

    if relative in {
        ".python-version",
        "build_backend.py",
        "pyproject.toml",
        "uv.lock",
    }:
        return True
    if relative.startswith(("agentloopgate/", "configs/", "data/", "examples/")):
        return True
    if not relative.startswith("integrations/deepseek-harness/"):
        return False
    nested = relative.removeprefix("integrations/deepseek-harness/")
    return nested in {"package.json", "pnpm-lock.yaml", "tsconfig.json"} or nested.startswith(
        ("src/", "test/")
    )


def _paid_authorization_path(
    root: Path,
    config: FormalExperimentConfig,
    *,
    scope: Literal["pre_release_checkpoint", "release_tail"],
) -> Path:
    if config.paid_execution_authorization_root is None:
        raise ValueError("formal config has no paid execution authorization root")
    authorization_root = _under(
        root,
        Path(config.paid_execution_authorization_root),
    )
    expected_root = (root / "runs/authorizations" / config.experiment_id).resolve()
    if authorization_root != expected_root:
        raise ValueError(
            "paid execution authorization root must be "
            f"runs/authorizations/{config.experiment_id}"
        )
    filename = {
        "pre_release_checkpoint": "pre_release_checkpoint.json",
        "release_tail": "release_tail.json",
    }[scope]
    path = (authorization_root / filename).resolve()
    if not path.is_relative_to(authorization_root):
        raise ValueError("paid execution authorization path escapes its root")
    return path


def _verified_release_selection(path: Path) -> tuple[str, str]:
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
        selection_digest = selection.pop("selection_digest")
        decision = selection["selection"]
        governed_candidate_id = decision["agentloopgate_candidate_id"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("cannot verify Selection for Release authorization") from exc
    if (
        not isinstance(selection_digest, str)
        or canonical_digest(selection) != selection_digest
        or decision.get("agentloopgate_decision") != "SELECT"
        or not isinstance(governed_candidate_id, str)
        or not governed_candidate_id
    ):
        raise ValueError("Release authorization requires a verified SELECT result")
    return selection_digest, governed_candidate_id


def _under(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"formal experiment path escapes project root: {path}")
    return resolved
