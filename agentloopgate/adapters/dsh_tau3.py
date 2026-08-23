"""DeepSeek Harness model-session adapter for the pinned τ³ banking evaluator."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import model_validator

from agentloopgate.adapters.base import (
    AdapterHealth,
    BenchmarkIngestResult,
    BenchmarkRunContext,
    BenchmarkRunRequest,
    BenchmarkUnavailableError,
    OutcomeImportError,
)
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.adapters.tau3 import (
    SOCKSIO_REQUIREMENT,
    TAU3_COMMIT,
    TAU3_DOMAIN,
    Tau3Adapter,
)
from agentloopgate.bridge import BridgeService
from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.runtime import (
    DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT,
    DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT,
    DSH_TAU3_FAILURE_USAGE_POLICY_CURRENT,
    DSH_TAU3_PROTOCOL_CURRENT,
    DSH_TAU3_REPLY_POLICY_CURRENT,
    DSH_TAU3_SUPPORTED_PROTOCOLS,
    USER_EMPTY_FINAL_REPAIR_LIMIT_CURRENT,
    USER_EMPTY_FINAL_REPAIR_POLICY_CURRENT,
    DshTau3TurnClient,
    load_evaluator_overlay,
    verify_evaluator_overlay_sources,
)
from agentloopgate.schemas import (
    EvidenceReceipt,
    EvidenceStatus,
    PilotEvidenceJoin,
    RunRecord,
    RunSource,
    RuntimeHost,
    RunValidity,
    SourceTraceRef,
)
from agentloopgate.schemas.models import NonEmpty, StrictModel, UtcDateTime

DSH_VERSION = "0.1.0-rc.8"
DSH_COMMIT = "141eb6fef83422698aef7a981029e843e8161534"
PLUGIN_PACKAGE = "@agentloopgate/dsh-plugin"
PLUGIN_VERSION = "0.1.0"
AGENT_NAME = "agentloopgate_dsh"


@dataclass(frozen=True)
class DshTau3PilotConfig:
    dsh_executable: Path
    dsh_home: Path
    patch_path: Path
    session_root: Path
    profile: str
    provider: str
    model: str
    experiment_namespace: str
    pricing: PilotPricingConfig
    harness_root: Path | None = None
    turn_timeout_seconds: int = 360
    dsh_stream_idle_timeout_ms: int = 300_000
    provider_max_retries: int = 1
    provider_retry_delay_ms: int = 500
    agent_temperature: Decimal = Decimal(0)
    agent_max_output_tokens: int = 4096
    dsh_tau3_protocol_version: str = DSH_TAU3_PROTOCOL_CURRENT
    reply_normalization_policy: str = DSH_TAU3_REPLY_POLICY_CURRENT
    runner_failure_usage_policy: str = DSH_TAU3_FAILURE_USAGE_POLICY_CURRENT
    empty_final_repair_policy: str = DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT
    empty_final_repair_limit: int = DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT
    user_empty_final_repair_policy: str | None = None
    user_empty_final_repair_limit: int = 0
    network_route_policy: Literal["inherit", "direct_no_proxy"] = "inherit"
    global_task_attempt_limit: int | None = None
    task_attempt_ledger_schema_version: Literal["1.0", "1.1"] = "1.0"
    model_usage_ledger_schema_version: Literal["1.1", "1.2"] = "1.1"
    evaluator_overlay_path: Path | None = None


class PilotPricingConfig(StrictModel):
    schema_version: Literal["1.0"]
    provider: NonEmpty
    model: NonEmpty
    currency: Literal["USD"]
    unit: Literal["per_million_tokens"]
    input_cache_miss: Decimal
    input_cache_hit: Decimal
    output: Decimal
    source_url: NonEmpty
    checked_at: UtcDateTime

    @model_validator(mode="after")
    def prices_are_non_negative(self) -> PilotPricingConfig:
        for value in (self.input_cache_miss, self.input_cache_hit, self.output):
            if not value.is_finite() or value < 0:
                raise ValueError("pilot prices must be finite and non-negative")
        return self


def load_pilot_pricing(path: Path) -> PilotPricingConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OutcomeImportError(f"cannot read Pilot pricing evidence: {path}") from exc
    return PilotPricingConfig.model_validate(raw)


class DshTau3PilotResult(BenchmarkIngestResult):
    dsh_receipts: list[EvidenceReceipt]
    dsh_records: list[RunRecord]
    evidence_joins: list[PilotEvidenceJoin]

    @model_validator(mode="after")
    def dsh_artifacts_align(self) -> DshTau3PilotResult:
        dsh_run_ids = {record.run_id for record in self.dsh_records}
        tau_run_ids = {record.run_id for record in self.records}
        if len(dsh_run_ids) != len(self.dsh_records):
            raise ValueError("DSH run ids must be unique")
        if {receipt.run_id for receipt in self.dsh_receipts} != dsh_run_ids:
            raise ValueError("every DSH run must have exactly one evidence receipt")
        if {join.dsh_run_id for join in self.evidence_joins} != dsh_run_ids:
            raise ValueError("every DSH run must have exactly one evidence join")
        if {join.tau_run_id for join in self.evidence_joins} != tau_run_ids:
            raise ValueError("every τ³ run must have exactly one evidence join")
        return self


class DshTau3Adapter(Tau3Adapter):
    """Run τ³ with DSH as the model/session host, then join both evidence planes."""

    def __init__(
        self,
        project_root: Path,
        *,
        checkout: Path,
        pilot: DshTau3PilotConfig,
    ) -> None:
        super().__init__(project_root, checkout=checkout)
        valid_user_empty_final = (
            pilot.user_empty_final_repair_policy is None
            and pilot.user_empty_final_repair_limit == 0
        ) or (
            pilot.user_empty_final_repair_policy
            == USER_EMPTY_FINAL_REPAIR_POLICY_CURRENT
            and pilot.user_empty_final_repair_limit
            == USER_EMPTY_FINAL_REPAIR_LIMIT_CURRENT
        )
        if not valid_user_empty_final:
            raise ValueError(
                "User Simulator empty-final repair requires disabled/0 or "
                f"{USER_EMPTY_FINAL_REPAIR_POLICY_CURRENT}/1"
            )
        self.pilot = pilot

    def doctor(self) -> AdapterHealth:
        upstream = super().doctor()
        if not upstream.ready:
            return upstream
        missing: list[str] = []
        for path, label in (
            (self.pilot.dsh_executable, "dsh executable"),
            (self.pilot.patch_path, "banking DSH patch"),
            (self.project_root / "examples/tau3-banking/run.py", "τ³ runner"),
            (self.project_root / ".venv/bin/agentloopgate", "AgentLoopGate bridge"),
        ):
            if not path.resolve().is_file():
                missing.append(label)
        if self.pilot.evaluator_overlay_path is not None:
            try:
                overlay = load_evaluator_overlay(self.pilot.evaluator_overlay_path)
                if overlay.benchmark_commit != TAU3_COMMIT:
                    raise ValueError("overlay benchmark commit mismatch")
                verify_evaluator_overlay_sources(overlay, checkout=self.checkout)
            except ValueError as exc:
                missing.append(f"verified evaluator overlay ({exc})")
        version = self._dsh_version()
        if version != DSH_VERSION:
            missing.append(f"DeepSeek Harness {DSH_VERSION}")
        if not self._profile_has_plugin():
            missing.append(f"{PLUGIN_PACKAGE} in profile {self.pilot.profile}")
        if (
            self.pilot.pricing.provider != self.pilot.provider
            or self.pilot.pricing.model != self.pilot.model
        ):
            missing.append("pricing evidence matching the selected DSH provider/model")
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            missing.append("DEEPSEEK_API_KEY process environment")
        if missing:
            return AdapterHealth(
                status="unavailable",
                benchmark=f"tau2-bench/{TAU3_DOMAIN}+deepseek-harness",
                expected_commit=f"tau3:{upstream.expected_commit};dsh:{DSH_COMMIT}",
                actual_commit=upstream.actual_commit,
                version=f"tau3:{upstream.version};dsh:{version or 'missing'}",
                task_count=upstream.task_count,
                remediation="Provide: " + ", ".join(missing) + ".",
            )
        return AdapterHealth(
            status="ready",
            benchmark=f"tau2-bench/{TAU3_DOMAIN}+deepseek-harness",
            expected_commit=f"tau3:{upstream.expected_commit};dsh:{DSH_COMMIT}",
            actual_commit=upstream.actual_commit,
            version=f"tau3:{upstream.version};dsh:{version}",
            task_count=upstream.task_count,
            remediation="No action required.",
        )

    def build_command(self, request: BenchmarkRunRequest) -> list[str]:
        if request.max_concurrency != 1:
            raise BenchmarkUnavailableError(
                "the P0 DSH × τ³ reference adapter requires max_concurrency=1"
            )
        command = [
            "uv",
            "run",
            "--with",
            SOCKSIO_REQUIREMENT,
            "python",
            str(self.project_root / "examples/tau3-banking/run.py"),
            "run",
            "--domain",
            TAU3_DOMAIN,
            "--retrieval-config",
            request.retrieval_config,
            "--agent",
            AGENT_NAME,
            "--agent-llm",
            request.agent_model,
            "--user-llm",
            request.user_model,
            "--agent-llm-args",
            json.dumps(
                {
                    "num_retries": request.user_model_max_retries,
                    "temperature": float(request.agent_temperature),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            "--user-llm-args",
            json.dumps(
                {
                    "num_retries": request.user_model_max_retries,
                    "temperature": float(request.user_temperature),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            "--num-trials",
            str(request.trials),
            "--max-steps",
            str(request.max_steps),
            "--max-errors",
            str(request.max_errors),
            "--timeout",
            str(request.simulation_timeout_seconds),
            "--max-concurrency",
            "1",
            "--seed",
            str(request.seed),
            "--max-retries",
            str(request.max_retries),
            "--retry-delay",
            str(request.retry_delay_seconds),
            "--save-to",
            request.run_name,
        ]
        if request.resume:
            command.append("--auto-resume")
        return [*command, "--task-ids", *request.task_ids]

    def run(self, request: BenchmarkRunRequest) -> Path:
        health = self.doctor()
        if not health.ready:
            raise BenchmarkUnavailableError(health.remediation)
        self.pilot.session_root.mkdir(parents=True, exist_ok=True)
        self.pilot.dsh_home.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.pop("VIRTUAL_ENV", None)
        environment.pop("UV_RUN_RECURSION_DEPTH", None)
        if self.pilot.network_route_policy == "direct_no_proxy":
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                environment.pop(name, None)
        python_paths = [str(self.project_root), str(self.checkout / "src")]
        if environment.get("PYTHONPATH"):
            python_paths.append(environment["PYTHONPATH"])
        environment.update(
            {
                "PYTHONPATH": os.pathsep.join(python_paths),
                "DSH_HOME": str(self.pilot.dsh_home.resolve()),
                "AGENTLOOPGATE_PROJECT_ROOT": str(self.project_root),
                "AGENTLOOPGATE_DSH_EXECUTABLE": str(
                    self.pilot.dsh_executable.resolve()
                ),
                "AGENTLOOPGATE_DSH_PATCH": str(self.pilot.patch_path.resolve()),
                "AGENTLOOPGATE_DSH_PROFILE": self.pilot.profile,
                "AGENTLOOPGATE_DSH_SESSION_ROOT": str(
                    self.pilot.session_root.resolve()
                ),
                "AGENTLOOPGATE_DSH_PROVIDER": self.pilot.provider,
                "AGENTLOOPGATE_DSH_MODEL": self.pilot.model,
                "AGENTLOOPGATE_EXPERIMENT_NAMESPACE": (
                    self.pilot.experiment_namespace
                ),
                "AGENTLOOPGATE_HARNESS_ROOT": str(
                    (self.pilot.harness_root or self.project_root).resolve()
                ),
                "TZ": "UTC",
                "AGENTLOOPGATE_INPUT_PRICE_PER_MILLION": str(
                    self.pilot.pricing.input_cache_miss
                ),
                "AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION": str(
                    self.pilot.pricing.input_cache_hit
                ),
                "AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION": str(
                    self.pilot.pricing.output
                ),
                "AGENTLOOPGATE_DSH_TURN_TIMEOUT_SECONDS": str(
                    self.pilot.turn_timeout_seconds
                ),
                "AGENTLOOPGATE_DSH_STREAM_IDLE_TIMEOUT_MS": str(
                    self.pilot.dsh_stream_idle_timeout_ms
                ),
                "AGENTLOOPGATE_PROVIDER_MAX_RETRIES": str(
                    self.pilot.provider_max_retries
                ),
                "AGENTLOOPGATE_PROVIDER_RETRY_DELAY_MS": str(
                    self.pilot.provider_retry_delay_ms
                ),
                "AGENTLOOPGATE_AGENT_TEMPERATURE": str(
                    self.pilot.agent_temperature
                ),
                "AGENTLOOPGATE_AGENT_MAX_OUTPUT_TOKENS": str(
                    self.pilot.agent_max_output_tokens
                ),
                "AGENTLOOPGATE_REPLY_NORMALIZATION_POLICY": (
                    self.pilot.reply_normalization_policy
                ),
                "AGENTLOOPGATE_EMPTY_FINAL_REPAIR_POLICY": (
                    self.pilot.empty_final_repair_policy
                ),
                "AGENTLOOPGATE_EMPTY_FINAL_REPAIR_LIMIT": str(
                    self.pilot.empty_final_repair_limit
                ),
                "AGENTLOOPGATE_TAU3_CHECKOUT": str(self.checkout.resolve()),
            }
        )
        if self.pilot.user_empty_final_repair_policy is not None:
            environment["AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_POLICY"] = (
                self.pilot.user_empty_final_repair_policy
            )
            environment["AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_LIMIT"] = str(
                self.pilot.user_empty_final_repair_limit
            )
        if self.pilot.evaluator_overlay_path is not None:
            environment["AGENTLOOPGATE_TAU3_EVALUATOR_OVERLAY"] = str(
                self.pilot.evaluator_overlay_path.resolve()
            )
        if request.model_usage_ledger is not None:
            usage_ledger = request.model_usage_ledger.resolve()
            if not usage_ledger.is_relative_to(self.project_root):
                raise BenchmarkUnavailableError(
                    "model usage ledger must remain under the project root"
                )
            environment["AGENTLOOPGATE_MODEL_USAGE_LEDGER"] = str(usage_ledger)
            environment["AGENTLOOPGATE_MODEL_USAGE_LEDGER_SCHEMA_VERSION"] = (
                self.pilot.model_usage_ledger_schema_version
            )
        if request.user_model_usage_ledger is not None:
            user_usage_ledger = request.user_model_usage_ledger.resolve()
            if not user_usage_ledger.is_relative_to(self.project_root):
                raise BenchmarkUnavailableError(
                    "user model usage ledger must remain under the project root"
                )
            environment["AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER"] = str(
                user_usage_ledger
            )
        if request.task_attempt_ledger is not None:
            task_attempt_ledger = request.task_attempt_ledger.resolve()
            if not task_attempt_ledger.is_relative_to(self.project_root):
                raise BenchmarkUnavailableError(
                    "task attempt ledger must remain under the project root"
                )
            if self.pilot.global_task_attempt_limit is None:
                raise BenchmarkUnavailableError(
                    "task attempt ledger requires a global task attempt limit"
                )
            environment["AGENTLOOPGATE_TASK_ATTEMPT_LEDGER"] = str(
                task_attempt_ledger
            )
            environment["AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION"] = (
                self.pilot.task_attempt_ledger_schema_version
            )
            environment["AGENTLOOPGATE_GLOBAL_TASK_ATTEMPT_LIMIT"] = str(
                self.pilot.global_task_attempt_limit
            )
        try:
            subprocess.run(
                self.build_command(request),
                cwd=self.checkout,
                env=environment,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BenchmarkUnavailableError(
                "DSH-backed τ³ execution failed; inspect retained DSH and τ³ logs"
            ) from exc
        result = self.checkout / "data" / "simulations" / request.run_name / "results.json"
        if not result.is_file():
            raise BenchmarkUnavailableError(
                "τ³ completed without producing data/simulations/<run>/results.json"
            )
        return result

    def ingest_and_link(
        self,
        result_path: Path,
        context: BenchmarkRunContext,
    ) -> DshTau3PilotResult:
        tau_result = super().ingest(result_path, context)
        return DshTau3EvidenceLinker(
            self.project_root,
            pilot=self.pilot,
        ).link(result_path, tau_result)

    def composition_digest(self) -> str:
        return canonical_digest(
            {
                "dsh_version": DSH_VERSION,
                "dsh_commit": DSH_COMMIT,
                "profile": self.pilot.profile,
                "plugin_package": PLUGIN_PACKAGE,
                "plugin_version": PLUGIN_VERSION,
                "patch_digest": file_digest(self.pilot.patch_path),
                "provider": self.pilot.provider,
                "model": self.pilot.model,
                "pricing_evidence": canonical_digest(self.pilot.pricing),
                "turn_timeout_seconds": self.pilot.turn_timeout_seconds,
                "dsh_stream_idle_timeout_ms": self.pilot.dsh_stream_idle_timeout_ms,
                "harness_digest": self._harness_digest(),
                "provider_max_retries": self.pilot.provider_max_retries,
                "provider_retry_delay_ms": self.pilot.provider_retry_delay_ms,
                "agent_temperature": self.pilot.agent_temperature,
                "agent_max_output_tokens": self.pilot.agent_max_output_tokens,
                "dsh_tau3_protocol_version": self.pilot.dsh_tau3_protocol_version,
                "reply_normalization_policy": self.pilot.reply_normalization_policy,
                "runner_failure_usage_policy": self.pilot.runner_failure_usage_policy,
                "empty_final_repair_policy": self.pilot.empty_final_repair_policy,
                "empty_final_repair_limit": self.pilot.empty_final_repair_limit,
                "user_empty_final_repair_policy": (
                    self.pilot.user_empty_final_repair_policy
                ),
                "user_empty_final_repair_limit": (
                    self.pilot.user_empty_final_repair_limit
                ),
                "network_route_policy": self.pilot.network_route_policy,
                "global_task_attempt_limit": self.pilot.global_task_attempt_limit,
                "task_attempt_ledger_schema_version": (
                    self.pilot.task_attempt_ledger_schema_version
                ),
                "model_usage_ledger_schema_version": (
                    self.pilot.model_usage_ledger_schema_version
                ),
                "evaluator_overlay_digest": (
                    _evaluator_overlay_digest(self.pilot.evaluator_overlay_path)
                ),
            }
        )

    def _harness_digest(self) -> str:
        root = (self.pilot.harness_root or self.project_root).resolve()
        files = {
            path.relative_to(root).as_posix(): file_digest(path)
            for path in sorted((root / "harness").rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        if not files:
            raise OutcomeImportError("frozen harness root contains no files")
        return canonical_digest(files)

    def _dsh_version(self) -> str | None:
        try:
            return subprocess.run(
                [str(self.pilot.dsh_executable.resolve()), "--version"],
                cwd=self.project_root,
                env={**os.environ, "DSH_HOME": str(self.pilot.dsh_home.resolve())},
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    def _profile_has_plugin(self) -> bool:
        manifest = self.pilot.dsh_home / "profiles" / self.pilot.profile / "package.json"
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        dependencies = raw.get("dependencies") if isinstance(raw, dict) else None
        dsh = raw.get("dsh") if isinstance(raw, dict) else None
        profile = dsh.get("profile") if isinstance(dsh, dict) else None
        bundles = profile.get("bundles") if isinstance(profile, dict) else None
        return (
            isinstance(dependencies, dict)
            and PLUGIN_PACKAGE in dependencies
            and isinstance(bundles, list)
            and PLUGIN_PACKAGE in bundles
        )


class DshTau3EvidenceLinker:
    """Create immutable DSH records without treating DSH as the τ³ evaluator."""

    def __init__(self, project_root: Path, *, pilot: DshTau3PilotConfig) -> None:
        self.project_root = project_root.resolve()
        self.pilot = pilot
        self.store = BenchmarkEvidenceStore(self.project_root)

    def link(
        self,
        result_path: Path,
        tau_result: BenchmarkIngestResult,
    ) -> DshTau3PilotResult:
        raw = self._load_result(result_path)
        simulations = raw.get("simulations")
        if not isinstance(simulations, list):
            raise OutcomeImportError("τ³ simulations must be a JSON list")
        by_pair: dict[tuple[str, int], dict[str, Any]] = {}
        for simulation in simulations:
            if not isinstance(simulation, dict):
                raise OutcomeImportError("τ³ simulation must be a JSON object")
            task_id = simulation.get("task_id")
            trial = simulation.get("trial")
            if (
                not isinstance(task_id, str)
                or isinstance(trial, bool)
                or not isinstance(trial, int)
            ):
                raise OutcomeImportError("τ³ simulation task_id/trial is invalid")
            by_pair[(task_id, trial + 1)] = simulation

        tau_receipts = {receipt.run_id: receipt for receipt in tau_result.receipts}
        dsh_records: list[RunRecord] = []
        dsh_receipts: list[EvidenceReceipt] = []
        joins: list[PilotEvidenceJoin] = []
        for tau_record in tau_result.records:
            simulation = by_pair.get((tau_record.task_id, tau_record.trial_index))
            if simulation is None:
                raise OutcomeImportError("τ³ outcome cannot be paired to its simulation")
            seed = simulation.get("seed")
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise OutcomeImportError("τ³ simulation seed is required for DSH evidence join")
            fallback_session_id = DshTau3TurnClient.session_id(
                self.pilot.experiment_namespace,
                tau_record.task_id,
                seed,
            )
            session_hash = self._session_hash(
                simulation,
                fallback=canonical_digest({"session_id": fallback_session_id}),
            )
            dsh_ref = self._latest_verified_ref(session_hash)
            dsh_record = self._dsh_record(
                tau_record,
                simulation=simulation,
                ref=dsh_ref,
            )
            dsh_receipt = self._dsh_receipt(dsh_record, dsh_ref)
            tau_receipt = tau_receipts[tau_record.run_id]
            join = self._join(
                tau_record=tau_record,
                tau_receipt=tau_receipt,
                tau_ref=tau_result.source_trace_ref,
                dsh_record=dsh_record,
                dsh_receipt=dsh_receipt,
                dsh_ref=dsh_ref,
            )
            self.store.write_json_once(
                self.store.path_for("normalized", dsh_record.run_id),
                dsh_record.model_dump(mode="json"),
            )
            self.store.write_json_once(
                self.store.path_for("receipts", dsh_receipt.receipt_id),
                dsh_receipt.model_dump(mode="json"),
            )
            self.store.write_json_once(
                self.store.path_for("evidence_joins", join.join_id),
                join.model_dump(mode="json"),
            )
            dsh_records.append(dsh_record)
            dsh_receipts.append(dsh_receipt)
            joins.append(join)
        return DshTau3PilotResult(
            **tau_result.model_dump(mode="python"),
            dsh_receipts=dsh_receipts,
            dsh_records=dsh_records,
            evidence_joins=joins,
        )

    @staticmethod
    def _session_hash(simulation: dict[str, Any], *, fallback: str) -> str:
        messages = simulation.get("messages")
        if not isinstance(messages, list):
            raise OutcomeImportError("τ³ messages are required for DSH session correlation")
        observed: set[str] = set()
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            raw_data = message.get("raw_data")
            if not isinstance(raw_data, dict):
                continue
            value = raw_data.get("dsh_session_id_hash")
            if value is not None:
                if not isinstance(value, str) or not value.startswith("sha256:"):
                    raise OutcomeImportError("DSH session hash metadata is invalid")
                observed.add(value)
        if len(observed) > 1:
            raise OutcomeImportError("one τ³ trial references multiple DSH sessions")
        return next(iter(observed), fallback)

    def _latest_verified_ref(self, session_hash: str) -> SourceTraceRef:
        matches: list[SourceTraceRef] = []
        for path in (self.project_root / "runs/trace_refs").glob("DSH_*.json"):
            try:
                ref = SourceTraceRef.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if ref.session_id_hash == session_hash:
                matches.append(ref)
        if not matches:
            raise OutcomeImportError("no DeepSeek Harness trace matches the τ³ task trial")
        ref = max(matches, key=lambda item: (item.event_seq_end, item.event_count))
        verified = BridgeService(self.project_root).verify_trace(ref.source_trace_id)
        if verified.get("evidence_status") != EvidenceStatus.VERIFIED.value:
            raise OutcomeImportError("DeepSeek Harness trace is incomplete or unverifiable")
        return ref

    def _dsh_record(
        self,
        tau_record: RunRecord,
        *,
        simulation: dict[str, Any],
        ref: SourceTraceRef,
    ) -> RunRecord:
        suffix = canonical_digest(
            {"tau_run_id": tau_record.run_id, "source_trace_id": ref.source_trace_id}
        ).removeprefix("sha256:")[:20].upper()
        run_id = f"DSH_{suffix}"
        receipt_id = f"ER_DSH_{suffix}"
        messages = simulation.get("messages")
        latency_ms = (
            0
            if tau_record.run_validity is RunValidity.INFRA_INVALID and messages == []
            else self._agent_latency_ms(messages)
        )
        return RunRecord.model_validate(
            {
                **tau_record.model_dump(mode="python"),
                "run_id": run_id,
                "attempt_id": f"{run_id}:T{tau_record.trial_index}",
                "source": RunSource.DSH,
                "runtime_host": RuntimeHost.DEEPSEEK_HARNESS,
                "runtime_version": f"deepseek-harness@{DSH_VERSION}",
                "runtime_profile": self.pilot.profile,
                "composition_digest": self._composition_digest(),
                "model_id": f"{self.pilot.provider}/{self.pilot.model}",
                "latency_ms": latency_ms,
                "source_trace_ref": ref.source_trace_id,
                "evidence_receipt_ref": receipt_id,
            }
        )

    def _dsh_receipt(self, record: RunRecord, ref: SourceTraceRef) -> EvidenceReceipt:
        return EvidenceReceipt(
            schema_version="1.0",
            receipt_id=record.evidence_receipt_ref,
            source_trace_id=ref.source_trace_id,
            run_id=record.run_id,
            event_seq_start=ref.event_seq_start,
            event_seq_end=ref.event_seq_end,
            event_count=ref.event_count,
            redaction_policy_digest=file_digest(
                self.project_root / "configs/trace_redaction.yaml"
            ),
            normalized_record_digest=canonical_digest(record),
            collected_at=record.created_at,
            error_count=0,
        )

    def _join(
        self,
        *,
        tau_record: RunRecord,
        tau_receipt: EvidenceReceipt,
        tau_ref: SourceTraceRef,
        dsh_record: RunRecord,
        dsh_receipt: EvidenceReceipt,
        dsh_ref: SourceTraceRef,
    ) -> PilotEvidenceJoin:
        evidence_digest = canonical_digest(
            {
                "tau_record": canonical_digest(tau_record),
                "tau_receipt": canonical_digest(tau_receipt),
                "tau_ref": canonical_digest(tau_ref),
                "dsh_record": canonical_digest(dsh_record),
                "dsh_receipt": canonical_digest(dsh_receipt),
                "dsh_ref": canonical_digest(dsh_ref),
            }
        )
        suffix = evidence_digest.removeprefix("sha256:")[:20].upper()
        return PilotEvidenceJoin(
            schema_version="1.0",
            join_id=f"PEJ_{suffix}",
            task_id=tau_record.task_id,
            trial_index=tau_record.trial_index,
            dsh_run_id=dsh_record.run_id,
            tau_run_id=tau_record.run_id,
            dsh_source_trace_ref=dsh_ref.source_trace_id,
            dsh_evidence_receipt_ref=dsh_receipt.receipt_id,
            tau_source_trace_ref=tau_ref.source_trace_id,
            tau_evidence_receipt_ref=tau_receipt.receipt_id,
            session_id_hash=dsh_ref.session_id_hash,
            outcome_success=tau_record.success,
            evidence_digest=evidence_digest,
            created_at=max(tau_record.created_at, dsh_record.created_at),
        )

    def _composition_digest(self) -> str:
        return canonical_digest(
            {
                "dsh_version": DSH_VERSION,
                "dsh_commit": DSH_COMMIT,
                "profile": self.pilot.profile,
                "plugin_package": PLUGIN_PACKAGE,
                "plugin_version": PLUGIN_VERSION,
                "patch_digest": file_digest(self.pilot.patch_path),
                "provider": self.pilot.provider,
                "model": self.pilot.model,
                "pricing_evidence": canonical_digest(self.pilot.pricing),
                "turn_timeout_seconds": self.pilot.turn_timeout_seconds,
                "dsh_stream_idle_timeout_ms": self.pilot.dsh_stream_idle_timeout_ms,
                "harness_digest": self._harness_digest(),
                "provider_max_retries": self.pilot.provider_max_retries,
                "provider_retry_delay_ms": self.pilot.provider_retry_delay_ms,
                "agent_temperature": self.pilot.agent_temperature,
                "agent_max_output_tokens": self.pilot.agent_max_output_tokens,
                "dsh_tau3_protocol_version": self.pilot.dsh_tau3_protocol_version,
                "reply_normalization_policy": self.pilot.reply_normalization_policy,
                "runner_failure_usage_policy": self.pilot.runner_failure_usage_policy,
                "empty_final_repair_policy": self.pilot.empty_final_repair_policy,
                "empty_final_repair_limit": self.pilot.empty_final_repair_limit,
                "user_empty_final_repair_policy": (
                    self.pilot.user_empty_final_repair_policy
                ),
                "user_empty_final_repair_limit": (
                    self.pilot.user_empty_final_repair_limit
                ),
                "network_route_policy": self.pilot.network_route_policy,
                "global_task_attempt_limit": self.pilot.global_task_attempt_limit,
                "evaluator_overlay_digest": (
                    _evaluator_overlay_digest(self.pilot.evaluator_overlay_path)
                ),
            }
        )

    def _harness_digest(self) -> str:
        root = (self.pilot.harness_root or self.project_root).resolve()
        files = {
            path.relative_to(root).as_posix(): file_digest(path)
            for path in sorted((root / "harness").rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        if not files:
            raise OutcomeImportError("frozen harness root contains no files")
        return canonical_digest(files)

    @staticmethod
    def _agent_latency_ms(messages: Any) -> int:
        if not isinstance(messages, list):
            raise OutcomeImportError("τ³ messages are required for DSH latency evidence")
        seconds = Decimal(0)
        seen = False
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            raw_data = message.get("raw_data")
            protocol = (
                raw_data.get("agentloopgate_protocol")
                if isinstance(raw_data, dict)
                else None
            )
            if protocol is None:
                # τ³ seeds one inert assistant greeting before the custom agent
                # generates its first turn. It is not a DSH model invocation.
                if (
                    message.get("turn_idx") == 0
                    and raw_data is None
                    and message.get("generation_time_seconds") is None
                    and message.get("usage") is None
                    and message.get("tool_calls") is None
                ):
                    continue
                raise OutcomeImportError(
                    "provenance_missing: assistant message lacks DSH adapter provenance"
                )
            if protocol not in DSH_TAU3_SUPPORTED_PROTOCOLS:
                raise OutcomeImportError(
                    "protocol_version_unsupported: assistant message uses an "
                    f"unsupported DSH adapter protocol: {protocol!r}"
                )
            value = message.get("generation_time_seconds")
            if value is None or isinstance(value, bool):
                raise OutcomeImportError(
                    "DSH-backed assistant messages require generation_time_seconds"
                )
            try:
                parsed = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise OutcomeImportError(
                    "assistant generation_time_seconds must be a finite number"
                ) from exc
            if not parsed.is_finite() or parsed < 0:
                raise OutcomeImportError(
                    "assistant generation_time_seconds must be non-negative"
                )
            seconds += parsed
            seen = True
        if not seen:
            raise OutcomeImportError("DSH-backed simulation contains no assistant message")
        return round(float(seconds) * 1000)

    @staticmethod
    def _load_result(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OutcomeImportError(f"cannot read τ³ result: {path}") from exc
        if not isinstance(raw, dict):
            raise OutcomeImportError("τ³ result must be a JSON object")
        return raw


def _evaluator_overlay_digest(path: Path | None) -> str | None:
    return load_evaluator_overlay(path).overlay_digest if path is not None else None
