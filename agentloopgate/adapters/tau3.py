"""Pinned τ³ banking adapter for the upstream ``tau2-bench`` package."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from agentloopgate.adapters.base import (
    ActionDiagnostic,
    AdapterHealth,
    BenchmarkIngestResult,
    BenchmarkRunContext,
    BenchmarkRunRequest,
    BenchmarkUnavailableError,
    OutcomeDiagnostics,
    OutcomeImportError,
)
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.schemas import (
    EvidenceStatus,
    PersistenceKind,
    Pool,
    RunRecord,
    RunSource,
    RuntimeHost,
    RunValidity,
    SourceTraceRef,
)
from agentloopgate.splits.models import PoolManifest, TaskDescriptor
from agentloopgate.splits.service import EXPECTED_POOL_COUNTS

TAU3_VERSION = "1.0.1"
TAU3_TAG = "v1.0.1"
TAU3_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
TAU3_DOMAIN = "banking_knowledge"
TAU3_TASK_COUNT = 97
TAU3_TASKS_SHA256 = "sha256:213c7f3e6dc0420b1184ee271e39e38c6ece3c43edfa362db49a560828ebd543"
SOCKSIO_REQUIREMENT = "socksio==1.0.0"
_SUCCESS_TOLERANCE = Decimal("0.000001")
_OOD_FAMILIES = frozenset({"human_transfer", "referral", "high_risk_account_action"})
_HIGH_RISK_ACTIONS = frozenset(
    {"apply_for_credit_card", "change_user_email", "submit_transaction"}
)


@dataclass(frozen=True)
class Tau3SplitPlan:
    manifests: dict[Pool, PoolManifest]
    replay_task_ids: list[str]


class Tau3TaskCatalog:
    """Audit the upstream catalog and split it before any model result exists."""

    def __init__(self, descriptors: list[TaskDescriptor]) -> None:
        self.descriptors = descriptors

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        verify_official_digest: bool = True,
    ) -> Tau3TaskCatalog:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OutcomeImportError(f"cannot read τ³ task catalog: {path}") from exc
        if not isinstance(raw, list) or len(raw) != TAU3_TASK_COUNT:
            raise OutcomeImportError(
                f"τ³ task catalog must contain exactly {TAU3_TASK_COUNT} tasks"
            )
        if verify_official_digest and file_digest(path) != TAU3_TASKS_SHA256:
            raise OutcomeImportError("τ³ task catalog digest does not match pinned v1.0.1")
        descriptors = [cls._descriptor(task) for task in raw]
        task_ids = [item.task_id for item in descriptors]
        if len(task_ids) != len(set(task_ids)):
            raise OutcomeImportError("τ³ task catalog contains duplicate task ids")
        return cls(descriptors)

    def build_split_plan(self) -> Tau3SplitPlan:
        ood = [
            item for item in self.descriptors if item.workflow_family in _OOD_FAMILIES
        ]
        if len(ood) != EXPECTED_POOL_COUNTS[Pool.RELEASE_OOD]:
            raise OutcomeImportError(
                "pinned τ³ catalog no longer yields the frozen 20-task OOD family reservation"
            )
        if {item.workflow_family for item in ood} != _OOD_FAMILIES:
            raise OutcomeImportError("τ³ catalog is missing a frozen OOD workflow family")
        remaining = [
            item for item in self.descriptors if item.workflow_family not in _OOD_FAMILIES
        ]
        expected_remaining = TAU3_TASK_COUNT - EXPECTED_POOL_COUNTS[Pool.RELEASE_OOD]
        if len(remaining) != expected_remaining:
            raise OutcomeImportError("τ³ OOD reservation overlaps the ID task population")
        ordered = self._stratified_order(remaining)
        manifests: dict[Pool, PoolManifest] = {}
        cursor = 0
        for pool in (
            Pool.PILOT,
            Pool.UPDATE_SOURCE,
            Pool.UPDATE_CHECK,
            Pool.SELECTION,
            Pool.RELEASE_ID,
        ):
            count = EXPECTED_POOL_COUNTS[pool]
            manifests[pool] = PoolManifest(
                schema_version="1.0",
                pool=pool,
                benchmark_commit=TAU3_COMMIT,
                tasks=ordered[cursor : cursor + count],
            )
            cursor += count
        manifests[Pool.RELEASE_OOD] = PoolManifest(
            schema_version="1.0",
            pool=Pool.RELEASE_OOD,
            benchmark_commit=TAU3_COMMIT,
            tasks=sorted(ood, key=lambda item: self._hash_key(item.task_id)),
        )
        update_source = manifests[Pool.UPDATE_SOURCE].tasks
        replay = sorted(
            update_source,
            key=lambda item: (
                not item.high_risk,
                -item.document_count,
                -item.tool_complexity,
                self._hash_key(item.task_id),
            ),
        )[:10]
        return Tau3SplitPlan(
            manifests=manifests,
            replay_task_ids=[item.task_id for item in replay],
        )

    @classmethod
    def _descriptor(cls, task: object) -> TaskDescriptor:
        if not isinstance(task, dict):
            raise OutcomeImportError("τ³ task entry must be a JSON object")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise OutcomeImportError("τ³ task id must be a non-empty string")
        criteria = task.get("evaluation_criteria") or {}
        if not isinstance(criteria, dict):
            raise OutcomeImportError(f"τ³ task {task_id} has invalid evaluation_criteria")
        actions = criteria.get("actions") or []
        if not isinstance(actions, list):
            raise OutcomeImportError(f"τ³ task {task_id} actions must be a list")
        action_names: set[str] = set()
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("name"), str):
                raise OutcomeImportError(f"τ³ task {task_id} contains an invalid action")
            action_names.add(action["name"])
        documents = task.get("required_documents") or []
        if not isinstance(documents, list):
            raise OutcomeImportError(f"τ³ task {task_id} required_documents must be a list")
        family = cls._workflow_family(action_names)
        return TaskDescriptor(
            task_id=task_id,
            workflow_family=family,
            high_risk=bool(action_names & _HIGH_RISK_ACTIONS),
            document_count=max(1, len(documents)),
            tool_complexity=max(1, len(action_names)),
        )

    @staticmethod
    def _workflow_family(action_names: set[str]) -> str:
        if action_names & {"change_user_email", "submit_transaction"}:
            return "high_risk_account_action"
        if any("human" in name and "transfer" in name for name in action_names):
            return "human_transfer"
        if any("referral" in name for name in action_names):
            return "referral"
        if any("credit_card" in name for name in action_names):
            return "credit_card"
        return "knowledge_only"

    @classmethod
    def _stratified_order(cls, descriptors: list[TaskDescriptor]) -> list[TaskDescriptor]:
        strata: dict[tuple[str, bool, int, int], list[TaskDescriptor]] = {}
        for item in descriptors:
            key = (
                item.workflow_family,
                item.high_risk,
                min(item.document_count, 3),
                min(item.tool_complexity, 3),
            )
            strata.setdefault(key, []).append(item)
        for bucket in strata.values():
            bucket.sort(key=lambda item: cls._hash_key(item.task_id))
        ordered: list[TaskDescriptor] = []
        keys = sorted(strata)
        while any(strata[key] for key in keys):
            for key in keys:
                if strata[key]:
                    ordered.append(strata[key].pop(0))
        return ordered

    @staticmethod
    def _hash_key(task_id: str) -> str:
        return hashlib.sha256(f"{TAU3_COMMIT}:{task_id}".encode()).hexdigest()


class Tau3Adapter:
    """Run and ingest the exact τ³ release used by the P0 contract."""

    def __init__(self, project_root: Path, *, checkout: Path) -> None:
        self.project_root = project_root.resolve()
        self.checkout = checkout.resolve()
        self.store = BenchmarkEvidenceStore(self.project_root)

    def doctor(self) -> AdapterHealth:
        if not self.checkout.is_dir() or shutil.which("uv") is None:
            return self._health(
                "unavailable",
                remediation=(
                    f"Clone tau2-bench {TAU3_TAG} at {TAU3_COMMIT} and install its knowledge extra."
                ),
            )
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.checkout,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            metadata = tomllib.loads(
                (self.checkout / "pyproject.toml").read_text(encoding="utf-8")
            )
            version = str(metadata["project"]["version"])
        except (OSError, KeyError, subprocess.CalledProcessError, tomllib.TOMLDecodeError):
            return self._health(
                "unavailable",
                remediation="Restore a complete tau2-bench checkout and its pyproject.toml.",
            )
        if commit != TAU3_COMMIT or version != TAU3_VERSION:
            return self._health(
                "version_mismatch",
                actual_commit=commit,
                version=version,
                remediation=f"Checkout {TAU3_TAG} at exact commit {TAU3_COMMIT}.",
            )
        tasks_path = self._tasks_path()
        try:
            tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._health(
                "data_mismatch",
                actual_commit=commit,
                version=version,
                remediation="Restore the pinned banking_knowledge tasks.json.",
            )
        task_count = len(tasks) if isinstance(tasks, list) else None
        if task_count != TAU3_TASK_COUNT or file_digest(tasks_path) != TAU3_TASKS_SHA256:
            return self._health(
                "data_mismatch",
                actual_commit=commit,
                version=version,
                task_count=task_count,
                remediation="Restore the unmodified v1.0.1 banking task catalog.",
            )
        return self._health(
            "ready",
            actual_commit=commit,
            version=version,
            task_count=task_count,
            remediation="No action required.",
        )

    def build_command(self, request: BenchmarkRunRequest) -> list[str]:
        command = [
            "uv",
            "run",
            "--with",
            SOCKSIO_REQUIREMENT,
            "tau2",
            "run",
            "--domain",
            TAU3_DOMAIN,
            "--retrieval-config",
            request.retrieval_config,
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
            str(request.max_concurrency),
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
        environment = os.environ.copy()
        environment.pop("VIRTUAL_ENV", None)
        environment.pop("UV_RUN_RECURSION_DEPTH", None)
        environment["TZ"] = "UTC"
        subprocess.run(
            self.build_command(request),
            cwd=self.checkout,
            env=environment,
            check=True,
        )
        result = self.checkout / "data" / "simulations" / request.run_name / "results.json"
        if not result.is_file():
            raise BenchmarkUnavailableError(
                "tau2 completed without producing data/simulations/<run>/results.json"
            )
        return result

    def ingest(
        self,
        result_path: Path,
        context: BenchmarkRunContext,
    ) -> BenchmarkIngestResult:
        return self._ingest(result_path, context, fail_fast_pair=None)

    def ingest_position_fail_fast(
        self,
        result_path: Path,
        context: BenchmarkRunContext,
        *,
        task_id: str,
        trial: int,
    ) -> BenchmarkIngestResult:
        """Ingest a verified partial result stopped at one infra-invalid position."""

        return self._ingest(
            result_path,
            context,
            fail_fast_pair=(task_id, trial),
        )

    def _ingest(
        self,
        result_path: Path,
        context: BenchmarkRunContext,
        *,
        fail_fast_pair: tuple[str, int] | None,
    ) -> BenchmarkIngestResult:
        raw = self._load_object(result_path)
        info = self._object(raw, "info")
        self._validate_info(info, context)
        tasks = self._list(raw, "tasks")
        task_by_id = {self._string(task, "id"): task for task in tasks if isinstance(task, dict)}
        if set(task_by_id) != set(context.expected_task_ids):
            raise OutcomeImportError("τ³ task list does not match expected task ids")
        simulations = self._list(raw, "simulations")
        expected_pairs = {
            (task_id, trial)
            for task_id in context.expected_task_ids
            for trial in range(context.expected_trials)
        }
        actual_pairs: set[tuple[str, int]] = set()
        run_ids: set[str] = set()
        for simulation in simulations:
            if not isinstance(simulation, dict):
                raise OutcomeImportError("τ³ simulations must be JSON objects")
            pair = (self._string(simulation, "task_id"), self._integer(simulation, "trial"))
            run_id = self._string(simulation, "id")
            if pair in actual_pairs or run_id in run_ids:
                raise OutcomeImportError("τ³ result contains a duplicate task trial or run id")
            actual_pairs.add(pair)
            run_ids.add(run_id)
        if fail_fast_pair is None:
            if actual_pairs != expected_pairs:
                raise OutcomeImportError("τ³ result is missing or adds an expected task trial")
        else:
            if (
                fail_fast_pair not in expected_pairs
                or fail_fast_pair not in actual_pairs
                or not actual_pairs < expected_pairs
            ):
                raise OutcomeImportError(
                    "τ³ fail-fast result is not a strict subset of expected trials"
                )
            trigger = next(
                simulation
                for simulation in simulations
                if isinstance(simulation, dict)
                and (simulation.get("task_id"), simulation.get("trial"))
                == fail_fast_pair
            )
            if trigger.get("termination_reason") != "infrastructure_error":
                raise OutcomeImportError(
                    "τ³ fail-fast trigger is not infrastructure-invalid"
                )

        created_at = self._datetime(raw.get("timestamp"))
        ref = self.store.attach(
            result_path,
            runtime_host=RuntimeHost.TAU3,
            persistence_kind=PersistenceKind.TAU_RAW,
            event_count=len(simulations),
            session_identity={
                "git_commit": info["git_commit"],
                "timestamp": raw.get("timestamp"),
                "tasks": sorted(context.expected_task_ids),
            },
            created_at=created_at,
        )
        records: list[RunRecord] = []
        receipts = []
        diagnostics: list[OutcomeDiagnostics] = []
        ordered = sorted(
            simulations,
            key=lambda item: (str(item["task_id"]), int(item["trial"]), str(item["id"])),
        )
        for index, simulation in enumerate(ordered):
            task_id = self._string(simulation, "task_id")
            task = task_by_id[task_id]
            collected_at = self._datetime(simulation.get("end_time") or simulation.get("timestamp"))
            record, receipt, diagnostic = self.store.persist_run(
                ref=ref,
                event_index=index,
                record_factory=lambda receipt_id, simulation=simulation: self._record(
                    simulation,
                    info=info,
                    ref=ref,
                    receipt_id=receipt_id,
                    context=context,
                ),
                diagnostic_factory=lambda receipt_id, simulation=simulation, task=task: (
                    self._diagnostic(
                        simulation,
                        task=task,
                        evidence_ref=receipt_id,
                    )
                ),
                collected_at=collected_at,
            )
            records.append(record)
            receipts.append(receipt)
            diagnostics.append(diagnostic)
        return BenchmarkIngestResult(
            schema_version="1.0",
            source_trace_ref=ref,
            receipts=receipts,
            records=records,
            diagnostics=diagnostics,
        )

    def verify(self, ref: SourceTraceRef) -> EvidenceStatus:
        return self.store.verify(ref)

    def _record(
        self,
        simulation: dict[str, Any],
        *,
        info: dict[str, Any],
        ref: SourceTraceRef,
        receipt_id: str,
        context: BenchmarkRunContext,
    ) -> RunRecord:
        termination = self._string(simulation, "termination_reason")
        infrastructure_error = termination == "infrastructure_error"
        reward_info = simulation.get("reward_info")
        if not infrastructure_error and not isinstance(reward_info, dict):
            raise OutcomeImportError("non-infrastructure τ³ run is missing reward_info")
        raw_cost = simulation.get("agent_cost")
        cost = None if infrastructure_error and raw_cost is None else self._decimal(
            raw_cost,
            field="agent_cost",
        )
        if cost is not None and cost < 0:
            raise OutcomeImportError("agent_cost cannot be negative")
        success = None if infrastructure_error else self._is_success(reward_info["reward"])
        input_tokens, output_tokens = self._agent_tokens(simulation.get("messages"))
        task_id = self._string(simulation, "task_id")
        trial = self._integer(simulation, "trial")
        run_id = self._string(simulation, "id")
        duration = simulation.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            raise OutcomeImportError("τ³ duration must be a non-negative number")
        return RunRecord(
            schema_version="1.0",
            run_id=run_id,
            attempt_id=f"{run_id}:T{trial + 1}",
            task_id=task_id,
            pool=context.pool,
            snapshot_id=context.snapshot_id,
            candidate_id=context.candidate_id,
            source=RunSource.TAU3,
            runtime_host=RuntimeHost.TAU3,
            runtime_version=f"tau2-bench@{TAU3_VERSION}",
            model_id=context.model_id,
            benchmark_commit=context.benchmark_commit,
            objective_digest=context.objective_digest,
            split_digest=context.split_digest,
            initial_state_digest=context.initial_state_digests[task_id],
            terminal_state_digest=canonical_digest(
                {"termination_reason": termination, "reward_info": reward_info}
            ),
            trial_index=trial + 1,
            run_validity=(
                RunValidity.INFRA_INVALID if infrastructure_error else RunValidity.VALID
            ),
            success=success,
            critical_violations=[],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(float(duration) * 1000),
            cost=cost,
            source_trace_ref=ref.source_trace_id,
            evidence_receipt_ref=receipt_id,
            created_at=self._datetime(simulation.get("end_time") or simulation.get("timestamp")),
        )

    def _diagnostic(
        self,
        simulation: dict[str, Any],
        *,
        task: dict[str, Any],
        evidence_ref: str,
    ) -> OutcomeDiagnostics:
        reward_info = simulation.get("reward_info")
        reward = None
        reward_basis: list[str] = []
        db_match = None
        action_checks: list[ActionDiagnostic] = []
        if isinstance(reward_info, dict):
            reward = self._decimal(reward_info.get("reward"), field="reward_info.reward")
            raw_basis = reward_info.get("reward_basis") or []
            if not isinstance(raw_basis, list) or not all(
                isinstance(item, str) for item in raw_basis
            ):
                raise OutcomeImportError("reward_basis must be a list of strings")
            reward_basis = raw_basis
            db_check = reward_info.get("db_check")
            if db_check is not None:
                if not isinstance(db_check, dict) or not isinstance(db_check.get("db_match"), bool):
                    raise OutcomeImportError("db_check must contain a boolean db_match")
                db_match = db_check["db_match"]
            for check in reward_info.get("action_checks") or []:
                if not isinstance(check, dict) or not isinstance(check.get("action"), dict):
                    raise OutcomeImportError("action_checks contain an invalid action")
                action_checks.append(
                    ActionDiagnostic(
                        name=self._string(check["action"], "name"),
                        matched=self._boolean(check, "action_match"),
                        tool_type=check.get("tool_type"),
                    )
                )
        required_documents = task.get("required_documents") or []
        if not isinstance(required_documents, list):
            raise OutcomeImportError("required_documents must be a list")
        return OutcomeDiagnostics(
            schema_version="1.0",
            run_id=self._string(simulation, "id"),
            evidence_ref=evidence_ref,
            termination_reason=self._string(simulation, "termination_reason"),
            reward=reward,
            reward_basis=reward_basis,
            db_match=db_match,
            required_document_count=len(required_documents),
            action_checks=action_checks,
            observed_tool_names=self._observed_tool_names(simulation.get("messages")),
        )

    def _validate_info(self, info: dict[str, Any], context: BenchmarkRunContext) -> None:
        commit = self._string(info, "git_commit")
        if commit != TAU3_COMMIT or context.benchmark_commit != TAU3_COMMIT:
            raise OutcomeImportError(
                f"τ³ commit must equal the pinned governance commit {TAU3_COMMIT}"
            )
        environment = self._object(info, "environment_info")
        if self._string(environment, "domain_name") != TAU3_DOMAIN:
            raise OutcomeImportError(f"τ³ domain must be {TAU3_DOMAIN}")
        if info.get("retrieval_config") != "bm25":
            raise OutcomeImportError("τ³ retrieval_config must be the frozen bm25 configuration")
        if self._integer(info, "num_trials") != context.expected_trials:
            raise OutcomeImportError("τ³ num_trials does not match the expected trial count")
        agent_info = self._object(info, "agent_info")
        if agent_info.get("llm") != context.model_id:
            raise OutcomeImportError("τ³ agent model does not match the run context")

    def _health(
        self,
        status: str,
        *,
        remediation: str,
        actual_commit: str | None = None,
        version: str | None = None,
        task_count: int | None = None,
    ) -> AdapterHealth:
        return AdapterHealth(
            status=status,
            benchmark=f"tau2-bench/{TAU3_DOMAIN}",
            expected_commit=TAU3_COMMIT,
            actual_commit=actual_commit,
            version=version,
            task_count=task_count,
            remediation=remediation,
        )

    def _tasks_path(self) -> Path:
        return self.checkout / "data" / "tau2" / "domains" / TAU3_DOMAIN / "tasks.json"

    @staticmethod
    def _load_object(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OutcomeImportError(f"cannot read τ³ result: {path}") from exc
        if not isinstance(raw, dict):
            raise OutcomeImportError("τ³ result must be a JSON object")
        return raw

    @staticmethod
    def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
        item = value.get(key)
        if not isinstance(item, dict):
            raise OutcomeImportError(f"{key} must be a JSON object")
        return item

    @staticmethod
    def _list(value: dict[str, Any], key: str) -> list[Any]:
        item = value.get(key)
        if not isinstance(item, list):
            raise OutcomeImportError(f"{key} must be a JSON list")
        return item

    @staticmethod
    def _string(value: dict[str, Any], key: str) -> str:
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise OutcomeImportError(f"{key} must be a non-empty string")
        return item

    @staticmethod
    def _integer(value: dict[str, Any], key: str) -> int:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int):
            raise OutcomeImportError(f"{key} must be an integer")
        return item

    @staticmethod
    def _boolean(value: dict[str, Any], key: str) -> bool:
        item = value.get(key)
        if not isinstance(item, bool):
            raise OutcomeImportError(f"{key} must be a boolean")
        return item

    @staticmethod
    def _datetime(value: Any) -> datetime:
        if not isinstance(value, str):
            raise OutcomeImportError("τ³ timestamp must be an ISO-8601 string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OutcomeImportError("τ³ timestamp is not valid ISO-8601") from exc
        # Pinned tau2-bench v1.0.1 emits naive ``datetime.now()`` values.  Runs
        # launched by this adapter force TZ=UTC, so attaching UTC here preserves
        # the upstream instant while keeping AgentLoopGate artifacts timezone-aware.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _decimal(value: Any, *, field: str) -> Decimal:
        if value is None or isinstance(value, bool):
            raise OutcomeImportError(f"{field} is required for formal evaluation")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise OutcomeImportError(f"{field} must be a finite decimal") from exc
        if not parsed.is_finite():
            raise OutcomeImportError(f"{field} must be a finite decimal")
        return parsed

    @classmethod
    def _is_success(cls, reward: Any) -> bool:
        value = cls._decimal(reward, field="reward_info.reward")
        return abs(value - Decimal(1)) <= _SUCCESS_TOLERANCE

    @classmethod
    def _agent_tokens(cls, messages: Any) -> tuple[int, int]:
        if messages is None:
            return 0, 0
        if not isinstance(messages, list):
            raise OutcomeImportError("τ³ messages must be a list")
        input_tokens = 0
        output_tokens = 0
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            usage = message.get("usage")
            if usage is None:
                continue
            if not isinstance(usage, dict):
                raise OutcomeImportError("assistant usage must be a JSON object")
            input_tokens += cls._token_value(usage, "input_tokens", "prompt_tokens")
            input_tokens += cls._token_value(
                usage,
                "cache_read_tokens",
                "cache_read_tokens",
            )
            output_tokens += cls._token_value(usage, "output_tokens", "completion_tokens")
        return input_tokens, output_tokens

    @staticmethod
    def _token_value(usage: dict[str, Any], primary: str, fallback: str) -> int:
        value = usage.get(primary, usage.get(fallback, 0))
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OutcomeImportError(f"usage.{primary} must be a non-negative integer")
        return value

    @staticmethod
    def _observed_tool_names(messages: Any) -> list[str]:
        names: list[str] = []
        if not isinstance(messages, list):
            return names
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise OutcomeImportError("assistant tool_calls must be a list")
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    raise OutcomeImportError("tool call must be a JSON object")
                name = tool_call.get("name")
                if name is None and isinstance(tool_call.get("function"), dict):
                    name = tool_call["function"].get("name")
                if not isinstance(name, str) or not name:
                    raise OutcomeImportError("tool call name must be a non-empty string")
                names.append(name)
        return names
