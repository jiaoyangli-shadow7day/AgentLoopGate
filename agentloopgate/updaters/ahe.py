"""Adapter for the pinned Agentic Harness Engineering evolve agent."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Protocol
from uuid import uuid4

import yaml
from pydantic import Field

from agentloopgate.candidates import CandidateRegistry, CandidateRejectedError
from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.mutation import HarnessAssetManifest, MutationPolicy
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    ModelCallUsageEvent,
    verify_model_call_event,
)
from agentloopgate.schemas import (
    ArtifactId,
    CandidateRecord,
    Digest,
    FailureBundle,
    SnapshotManifest,
)
from agentloopgate.schemas.models import StrictModel
from agentloopgate.updaters.base import UpdaterError, UpdaterHealth

AHE_VERSION = "0.1.0"
AHE_COMMIT = "8b2a55d97590363fe50c3cc6b5e833b020a4bb4c"
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{20,}")


class AheRunRequest(StrictModel):
    attempt_id: ArtifactId
    candidate_id: ArtifactId
    experiment_id: ArtifactId | None = None
    protocol_digest: Digest | None = None
    study_digest: Digest | None = None
    source_revision: str | None = None
    experiment_root: Path
    allowed_paths: list[str] = Field(min_length=1)
    query: str = Field(min_length=1)
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"


class AheRunOutput(StrictModel):
    exit_code: int
    stdout: str
    stderr: str
    trace_path: Path | None
    summary_path: Path | None
    input_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    model_call_count: int = Field(default=0, ge=0)
    unresolved_model_call_count: int = Field(default=0, ge=0)
    cost: Decimal | None = Field(default=None, ge=0)
    cost_status: CostStatus = CostStatus.EXACT
    usage_path: Path | None = None
    duration_ms: int = Field(default=0, ge=0)
    attempt_artifact_root: Path | None = None


class AheRunner(Protocol):
    def doctor(self) -> UpdaterHealth: ...

    def run(self, request: AheRunRequest) -> AheRunOutput: ...


class AheSandbox:
    """macOS sandbox profile with project reads denied and writes confined."""

    def __init__(
        self,
        staging_root: Path,
        *,
        protected_root: Path | None = None,
        runtime_roots: tuple[Path, ...] = (),
    ) -> None:
        self.staging_root = staging_root.resolve()
        self.protected_root = protected_root.resolve() if protected_root else None
        self.runtime_roots = tuple(path.resolve() for path in runtime_roots)

    def profile(self) -> str:
        staging = _sandbox_path(self.staging_root)
        rules = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow sysctl-read)",
            "(allow mach*)",
            "(allow signal)",
            "(allow file-read*)",
        ]
        if self.protected_root is not None:
            rules.append(
                f'(deny file-read* (subpath "{_sandbox_path(self.protected_root)}"))'
            )
        for root in (*self.runtime_roots, self.staging_root):
            rules.append(f'(allow file-read* (subpath "{_sandbox_path(root)}"))')
        rules.extend(
            [
                "(allow network*)",
                f'(allow file-write* (subpath "{staging}"))',
                '(allow file-write* (literal "/dev/null"))',
            ]
        )
        return " ".join(rules)


class AheExternalRunner:
    def __init__(
        self,
        checkout: Path,
        *,
        project_root: Path,
        timeout_seconds: int = 3600,
        max_iterations: int = 80,
        max_output_tokens: int = 8000,
        temperature: Decimal = Decimal("0.3"),
        max_retries: int = 0,
        retry_delay_seconds: Decimal = Decimal("1"),
        input_price_per_million: Decimal = Decimal(0),
        cache_read_price_per_million: Decimal = Decimal(0),
        output_price_per_million: Decimal = Decimal(0),
    ) -> None:
        self.checkout = checkout.resolve()
        self.project_root = project_root.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_iterations = max_iterations
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.input_price_per_million = input_price_per_million
        self.cache_read_price_per_million = cache_read_price_per_million
        self.output_price_per_million = output_price_per_million

    def doctor(self) -> UpdaterHealth:
        sandbox_available = Path("/usr/bin/sandbox-exec").is_file()
        credentials = bool(os.environ.get("DEEPSEEK_API_KEY"))
        if not self.checkout.is_dir():
            return self._health(
                "unavailable",
                credentials=credentials,
                sandbox=sandbox_available,
                remediation=f"Clone AHE at exact commit {AHE_COMMIT} and run uv sync.",
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
                credentials=credentials,
                sandbox=sandbox_available,
                remediation="Restore the complete pinned AHE checkout and isolated environment.",
            )
        if commit != AHE_COMMIT or version != AHE_VERSION:
            return self._health(
                "version_mismatch",
                actual_commit=commit,
                version=version,
                credentials=credentials,
                sandbox=sandbox_available,
                remediation=f"Checkout the exact AHE commit {AHE_COMMIT}.",
            )
        python = self.checkout / ".venv/bin/python"
        if not python.is_file() or not sandbox_available:
            return self._health(
                "unavailable",
                actual_commit=commit,
                version=version,
                credentials=credentials,
                sandbox=sandbox_available,
                remediation="Run uv sync in the AHE checkout and enable macOS sandbox-exec.",
            )
        if not credentials:
            return self._health(
                "missing_credentials",
                actual_commit=commit,
                version=version,
                credentials=False,
                sandbox=True,
                remediation=(
                    "Export DEEPSEEK_API_KEY in the invoking process; "
                    "never store it in config."
                ),
            )
        return self._health(
            "ready",
            actual_commit=commit,
            version=version,
            credentials=True,
            sandbox=True,
            remediation="No action required.",
        )

    def run(self, request: AheRunRequest) -> AheRunOutput:
        health = self.doctor()
        if not health.ready:
            raise UpdaterError(health.remediation)
        started = time.monotonic()
        self._install_evolve_agent(request.experiment_root)
        (request.experiment_root / "query.txt").write_text(
            request.query,
            encoding="utf-8",
        )
        driver = request.experiment_root / "run_ahe.py"
        driver.write_text(_AHE_DRIVER, encoding="utf-8")
        runtime_dir = request.experiment_root / ".runtime"
        runtime_dir.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "LLM_API_KEY": env["DEEPSEEK_API_KEY"],
                "LLM_BASE_URL": request.base_url,
                "LLM_MODEL": request.model,
                "AGENTLOOPGATE_AHE_ATTEMPT_ID": request.attempt_id,
                "AGENTLOOPGATE_AHE_EXPERIMENT": str(request.experiment_root),
                "AGENTLOOPGATE_INPUT_PRICE_PER_MILLION": str(
                    self.input_price_per_million
                ),
                "AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION": str(
                    self.cache_read_price_per_million
                ),
                "AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION": str(
                    self.output_price_per_million
                ),
                "AGENTLOOPGATE_AHE_RETRY_DELAY_SECONDS": str(
                    self.retry_delay_seconds
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": str(runtime_dir),
                "XDG_CACHE_HOME": str(runtime_dir / "cache"),
            }
        )
        command = [
            "/usr/bin/sandbox-exec",
            "-p",
            AheSandbox(
                request.experiment_root,
                protected_root=self.project_root,
                runtime_roots=(self.checkout,),
            ).profile(),
            str(self.checkout / ".venv/bin/python"),
            str(driver),
        ]
        attempt_root = self._begin_attempt(request, command=command)
        try:
            completed = subprocess.run(
                command,
                cwd=self.checkout,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = _subprocess_text(exc.stdout)
            stderr = _subprocess_text(exc.stderr) or (
                f"AHE exceeded the frozen {self.timeout_seconds}s timeout"
            )
        except OSError as exc:
            exit_code = 127
            stdout = ""
            stderr = f"AHE process launch failed: {exc}"
        result_path = request.experiment_root / "ahe_result.json"
        result = {}
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                result = {}
        trace = request.experiment_root / "runs/iteration_001/evolve/evolve_trace.json"
        summary = request.experiment_root / "runs/iteration_001/evolve/evolve_summary.md"
        usage = request.experiment_root / "ahe_model_usage.jsonl"
        (
            input_tokens,
            cache_read_tokens,
            output_tokens,
            call_count,
            unresolved,
            cost_status,
            cost,
        ) = self._usage_accounting(usage)
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        attempt_root = self._preserve_attempt(
            request,
            destination=attempt_root,
            command=command,
            exit_code=exit_code,
            stdout=self._redact(stdout),
            stderr=self._redact(stderr or str(result.get("error", ""))),
            duration_ms=duration_ms,
            cost_status=cost_status,
            known_cost_usd=cost,
            model_call_count=call_count,
            unresolved_model_call_count=unresolved,
        )
        raw_attempt = attempt_root / "raw"
        retained_usage = raw_attempt / "ahe_model_usage.jsonl"
        retained_trace = raw_attempt / trace.relative_to(request.experiment_root)
        retained_summary = raw_attempt / summary.relative_to(request.experiment_root)
        return AheRunOutput(
            exit_code=exit_code,
            stdout=self._redact(stdout),
            stderr=self._redact(stderr or str(result.get("error", ""))),
            trace_path=retained_trace if retained_trace.is_file() else None,
            summary_path=retained_summary if retained_summary.is_file() else None,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            output_tokens=output_tokens,
            model_call_count=call_count,
            unresolved_model_call_count=unresolved,
            cost=cost,
            cost_status=cost_status,
            usage_path=retained_usage if retained_usage.is_file() else None,
            duration_ms=duration_ms,
            attempt_artifact_root=attempt_root,
        )

    def _install_evolve_agent(self, experiment_root: Path) -> None:
        source = self.checkout / "agents/evolve_agent"
        destination = experiment_root / "evolve_agent"
        shutil.copytree(source, destination)
        config_path = destination / "evolve_agent.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["max_iterations"] = self.max_iterations
        config["retry_attempts"] = self.max_retries + 1
        config.setdefault("llm_config", {})["max_tokens"] = self.max_output_tokens
        config["llm_config"]["temperature"] = float(self.temperature)
        for middleware in config.get("middlewares", []):
            if not isinstance(middleware, dict):
                continue
            if middleware.get("import") == (
                "middleware.context_compaction:ContextCompactionMiddleware"
            ):
                middleware.setdefault("params", {})["retry_attempts"] = (
                    self.max_retries + 1
                )
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    @staticmethod
    def _usage_accounting(
        path: Path,
    ) -> tuple[int, int, int, int, int, CostStatus, Decimal | None]:
        events: list[ModelCallUsageEvent] = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = ModelCallUsageEvent.model_validate_json(line)
                verify_model_call_event(event)
                events.append(event)
        started = {event.call_id for event in events if event.state is AttemptState.STARTED}
        terminals: dict[str, ModelCallUsageEvent] = {}
        for event in events:
            if event.state is AttemptState.STARTED:
                continue
            if event.call_id in terminals:
                raise UpdaterError("AHE usage ledger contains duplicate terminal events")
            terminals[event.call_id] = event
        if not set(terminals).issubset(started):
            raise UpdaterError("AHE usage terminal has no STARTED event")
        unresolved = len(started - set(terminals))
        known = [
            event
            for event in terminals.values()
            if event.cost_usd is not None
            and event.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
        ]
        cost = sum((event.cost_usd or Decimal(0) for event in known), Decimal(0))
        exact = (
            bool(terminals)
            and not unresolved
            and all(event.cost_status is CostStatus.EXACT for event in terminals.values())
        )
        status = (
            CostStatus.EXACT
            if exact
            else CostStatus.PARTIAL
            if known
            else CostStatus.UNAVAILABLE
        )
        return (
            sum(event.input_tokens or 0 for event in known),
            sum(event.cache_read_tokens or 0 for event in known),
            sum(event.output_tokens or 0 for event in known),
            len(terminals),
            unresolved,
            status,
            cost if known else None,
        )

    def _begin_attempt(self, request: AheRunRequest, *, command: list[str]) -> Path:
        destination = self.project_root / "runs/updaters/ahe/attempts" / request.attempt_id
        destination.mkdir(parents=True, exist_ok=False)
        payload = {
            "schema_version": "1.0",
            "attempt_id": request.attempt_id,
            "candidate_id": request.candidate_id,
            "experiment_id": request.experiment_id,
            "protocol_digest": request.protocol_digest,
            "study_digest": request.study_digest,
            "source_revision": request.source_revision,
            "state": "started",
            "recorded_at": datetime.now(UTC),
            "command": command,
            "cost_status": CostStatus.PENDING.value,
            "runtime": {
                "timeout_seconds": self.timeout_seconds,
                "max_iterations": self.max_iterations,
                "max_output_tokens": self.max_output_tokens,
                "temperature": self.temperature,
                "max_retries": self.max_retries,
                "retry_delay_seconds": self.retry_delay_seconds,
            },
            "pricing": {
                "input_cache_miss": self.input_price_per_million,
                "input_cache_hit": self.cache_read_price_per_million,
                "output": self.output_price_per_million,
            },
        }
        (destination / "started.json").write_bytes(
            canonical_json_bytes({**payload, "attempt_digest": canonical_digest(payload)})
            + b"\n"
        )
        return destination

    def _preserve_attempt(
        self,
        request: AheRunRequest,
        *,
        destination: Path,
        command: list[str],
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
        cost_status: CostStatus,
        known_cost_usd: Decimal | None,
        model_call_count: int,
        unresolved_model_call_count: int,
    ) -> Path:
        raw = destination / "raw"
        shutil.copytree(
            request.experiment_root,
            raw,
            ignore=shutil.ignore_patterns(".runtime", ".git", "__pycache__", "*.pyc"),
        )
        (destination / "stdout.txt").write_text(stdout, encoding="utf-8")
        (destination / "stderr.txt").write_text(stderr, encoding="utf-8")
        payload = {
            "schema_version": "1.0",
            "attempt_id": request.attempt_id,
            "candidate_id": request.candidate_id,
            "command": command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "state": "completed" if exit_code == 0 else "failed",
            "cost_status": cost_status.value,
            "known_cost_usd": known_cost_usd,
            "model_call_count": model_call_count,
            "unresolved_model_call_count": unresolved_model_call_count,
            "model_usage_artifact": "raw/ahe_model_usage.jsonl",
        }
        (destination / "terminal.json").write_bytes(
            canonical_json_bytes({**payload, "attempt_digest": canonical_digest(payload)})
            + b"\n"
        )
        return destination

    @staticmethod
    def _redact(value: str) -> str:
        return _SECRET_PATTERN.sub("[REDACTED]", value)

    @staticmethod
    def _health(
        status: str,
        *,
        credentials: bool,
        sandbox: bool,
        remediation: str,
        actual_commit: str | None = None,
        version: str | None = None,
    ) -> UpdaterHealth:
        return UpdaterHealth(
            status=status,
            name="ahe",
            expected_commit=AHE_COMMIT,
            actual_commit=actual_commit,
            version=version,
            credentials_configured=credentials,
            sandbox_available=sandbox,
            remediation=remediation,
        )


class AheAdapter:
    name = "ahe"
    version = f"{AHE_VERSION}@{AHE_COMMIT}"

    def __init__(
        self,
        project_root: Path,
        *,
        registry: CandidateRegistry,
        runner: AheRunner,
        experiment_id: str | None = None,
        protocol_digest: str | None = None,
        study_digest: str | None = None,
        source_revision: str | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.registry = registry
        self.runner = runner
        self.experiment_id = experiment_id
        self.protocol_digest = protocol_digest
        self.study_digest = study_digest
        self.source_revision = source_revision

    def doctor(self) -> UpdaterHealth:
        return self.runner.doctor()

    def propose(
        self,
        parent_snapshot: SnapshotManifest,
        failure_bundle: FailureBundle,
        asset_manifest: HarnessAssetManifest,
        mutation_policy: MutationPolicy,
        count: int,
        *,
        created_at: datetime | None = None,
    ) -> list[CandidateRecord]:
        if not 1 <= count <= 6:
            raise UpdaterError("AHE proposal count must be between 1 and 6")
        health = self.doctor()
        if not health.ready:
            raise UpdaterError(health.remediation)
        if failure_bundle.snapshot_id != parent_snapshot.snapshot_id:
            raise UpdaterError("FailureBundle snapshot does not match the parent snapshot")
        allowed_paths = self._allowed_paths(
            parent_snapshot,
            failure_bundle,
            asset_manifest,
        )
        timestamp = created_at or datetime.now(UTC)
        records: list[CandidateRecord] = []
        for index in range(count):
            identity = canonical_digest(
                {
                    "parent_snapshot_id": parent_snapshot.snapshot_id,
                    "failure_bundle": canonical_digest(failure_bundle),
                    "ahe_commit": AHE_COMMIT,
                    "proposal_index": index,
                }
            ).removeprefix("sha256:")[:12].upper()
            candidate_id = f"C_AHE_{identity}"
            existing_directory = self.project_root / "candidates" / candidate_id
            if existing_directory.exists():
                record = self.registry.load(candidate_id)
                metadata = (
                    self.project_root
                    / "runs/updaters/ahe"
                    / candidate_id
                    / "run_metadata.json"
                )
                if (
                    record.parent_snapshot_id != parent_snapshot.snapshot_id
                    or record.failure_bundle_digest != canonical_digest(failure_bundle)
                    or record.updater.name != self.name
                    or not metadata.is_file()
                ):
                    raise UpdaterError(
                        f"existing AHE candidate is incomplete or conflicts: {candidate_id}"
                    )
                records.append(record)
                continue
            rejected_directory = (
                self.project_root / "runs/updaters/ahe/rejected" / candidate_id
            )
            if rejected_directory.exists():
                try:
                    rejected = json.loads(
                        (rejected_directory / "rejection.json").read_text(
                            encoding="utf-8"
                        )
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    raise UpdaterError(
                        f"existing AHE rejection is corrupt: {candidate_id}"
                    ) from exc
                if (
                    rejected.get("parent_snapshot_id") != parent_snapshot.snapshot_id
                    or rejected.get("failure_bundle_digest")
                    != canonical_digest(failure_bundle)
                ):
                    raise UpdaterError(
                        f"existing AHE rejection conflicts: {candidate_id}"
                    )
                continue
            with TemporaryDirectory(prefix="agentloopgate-ahe-") as temporary:
                experiment_root = Path(temporary).resolve()
                baseline = self._stage_experiment(
                    experiment_root,
                    parent_snapshot=parent_snapshot,
                    allowed_paths=allowed_paths,
                    failure_bundle=failure_bundle,
                )
                output = self.runner.run(
                    AheRunRequest(
                        attempt_id=f"AHEATT_{uuid4().hex.upper()}",
                        candidate_id=candidate_id,
                        experiment_id=self.experiment_id,
                        protocol_digest=self.protocol_digest,
                        study_digest=self.study_digest,
                        source_revision=self.source_revision,
                        experiment_root=experiment_root,
                        allowed_paths=allowed_paths,
                        query=self._query(failure_bundle, allowed_paths),
                    )
                )
                if output.exit_code != 0:
                    raise UpdaterError(f"AHE failed: {output.stderr[:400]}")
                patch_path = self._extract_patch(experiment_root / "workspace", baseline)
                try:
                    record = self.registry.register(
                        candidate_id=candidate_id,
                        parent_snapshot_id=parent_snapshot.snapshot_id,
                        failure_bundle=failure_bundle,
                        updater_name=self.name,
                        updater_version=self.version,
                        hypothesis=failure_bundle.expected_behavior_change,
                        patch_path=patch_path,
                        predicted_metric="stable_success_task_count",
                        predicted_direction="increase",
                        created_at=timestamp,
                    )
                except CandidateRejectedError as exc:
                    self._preserve_rejection(
                        candidate_id,
                        parent_snapshot=parent_snapshot,
                        failure_bundle=failure_bundle,
                        output=output,
                        patch_path=patch_path,
                        reason=str(exc),
                    )
                    continue
                self._preserve_raw(
                    candidate_id,
                    emission_ordinal=index + 1,
                    output=output,
                    patch_path=patch_path,
                    parent_snapshot=parent_snapshot,
                    failure_bundle=failure_bundle,
                    asset_manifest=asset_manifest,
                    mutation_policy=mutation_policy,
                )
                records.append(record)
        return records

    def _preserve_rejection(
        self,
        candidate_id: str,
        *,
        parent_snapshot: SnapshotManifest,
        failure_bundle: FailureBundle,
        output: AheRunOutput,
        patch_path: Path,
        reason: str,
    ) -> None:
        destination = self.project_root / "runs/updaters/ahe/rejected" / candidate_id
        destination.mkdir(parents=True)
        shutil.copy2(patch_path, destination / "candidate.patch")
        for source, name in (
            (output.trace_path, "evolve_trace.json"),
            (output.summary_path, "evolve_summary.md"),
        ):
            if source is not None and source.is_file():
                shutil.copy2(source, destination / name)
        check = self.registry.checker.check(
            destination / "candidate.patch",
            budget=failure_bundle.budget,
        )
        payload = {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "parent_snapshot_id": parent_snapshot.snapshot_id,
            "failure_bundle_digest": canonical_digest(failure_bundle),
            "updater": {"name": self.name, "version": self.version},
            "patch_digest": file_digest(destination / "candidate.patch"),
            "check": check.model_dump(mode="json"),
            "reason": reason,
            "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens,
            "cache_read_tokens": output.cache_read_tokens,
            "model_call_count": output.model_call_count,
            "unresolved_model_call_count": output.unresolved_model_call_count,
            "cost": str(output.cost) if output.cost is not None else None,
            "cost_status": output.cost_status.value,
            "attempt_artifact_root": (
                output.attempt_artifact_root.relative_to(self.project_root).as_posix()
                if output.attempt_artifact_root is not None
                else None
            ),
            "exit_code": output.exit_code,
        }
        (destination / "rejection.json").write_bytes(
            canonical_json_bytes(payload) + b"\n"
        )

    def _allowed_paths(
        self,
        parent: SnapshotManifest,
        bundle: FailureBundle,
        manifest: HarnessAssetManifest,
    ) -> list[str]:
        allowed: list[str] = []
        targets = set(bundle.target_asset_families)
        for path, expected_digest in parent.harness_files.items():
            matching = [
                asset
                for asset in manifest.assets
                if asset.family in targets
                and any(PurePosixPath(path).match(pattern) for pattern in asset.path_patterns)
            ]
            if len(matching) != 1:
                continue
            source = (
                self.project_root
                / "snapshots"
                / parent.snapshot_id
                / "files"
                / path
            ).resolve()
            try:
                source.relative_to(self.project_root)
            except ValueError as exc:
                raise UpdaterError("snapshot harness path escapes the project root") from exc
            if not source.is_file() or file_digest(source) != expected_digest:
                raise UpdaterError(f"parent snapshot harness file drifted: {path}")
            allowed.append(path)
        if not allowed:
            raise UpdaterError("FailureBundle target families resolve to no parent snapshot assets")
        return sorted(allowed)

    def _stage_experiment(
        self,
        experiment_root: Path,
        *,
        parent_snapshot: SnapshotManifest,
        allowed_paths: list[str],
        failure_bundle: FailureBundle,
    ) -> str:
        workspace = experiment_root / "workspace"
        for relative in allowed_paths:
            source = (
                self.project_root
                / "snapshots"
                / parent_snapshot.snapshot_id
                / "files"
                / relative
            )
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        analysis = experiment_root / "runs/iteration_001/input/analysis"
        analysis.mkdir(parents=True)
        (analysis / "overview.md").write_text(
            "# Redacted failure evidence\n\n"
            f"Type: {failure_bundle.failure_type.value}\n\n"
            f"Summary: {failure_bundle.redacted_summary}\n\n"
            f"Expected behavior: {failure_bundle.expected_behavior_change}\n",
            encoding="utf-8",
        )
        (experiment_root / "runs/iteration_001/evolve").mkdir(parents=True)
        (experiment_root / "evolution_history.md").write_text(
            "# Evolution history\n\nNo previous candidate has been evaluated.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(
            ["git", "add", "--", *allowed_paths],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=AgentLoopGate",
                "-c",
                "user.email=local@agentloopgate.invalid",
                "commit",
                "-m",
                "AHE staged parent snapshot",
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    @staticmethod
    def _extract_patch(workspace: Path, baseline: str) -> Path:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=workspace,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        new_paths = [item.decode() for item in untracked if item]
        if new_paths:
            subprocess.run(
                ["git", "add", "-N", "--", *new_paths],
                cwd=workspace,
                check=True,
                capture_output=True,
            )
        diff = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff", baseline, "--"],
            cwd=workspace,
            check=True,
            capture_output=True,
        ).stdout
        if not diff.strip():
            raise UpdaterError("AHE completed without producing a file-level candidate")
        path = workspace.parent / "candidate.patch"
        path.write_bytes(diff)
        return path

    @staticmethod
    def _query(bundle: FailureBundle, allowed_paths: list[str]) -> str:
        return (
            "Produce exactly one falsifiable harness change from this redacted FailureBundle.\n"
            f"Affected runs: {', '.join(bundle.affected_run_ids)}\n"
            f"Failure type: {bundle.failure_type.value}\n"
            f"Evidence summary: {bundle.redacted_summary}\n"
            f"Expected behavior: {bundle.expected_behavior_change}\n"
            f"Writable files only: {', '.join(allowed_paths)}\n"
            f"Budget: {bundle.budget.max_files} files, {bundle.budget.max_changed_lines} lines.\n"
            "Do not read or infer benchmark answers, evaluator internals, or held-out tasks. "
            "Do not create files outside workspace. Make one atomic change, commit it, and stop."
        )

    def _preserve_raw(
        self,
        candidate_id: str,
        *,
        emission_ordinal: int,
        output: AheRunOutput,
        patch_path: Path,
        parent_snapshot: SnapshotManifest,
        failure_bundle: FailureBundle,
        asset_manifest: HarnessAssetManifest,
        mutation_policy: MutationPolicy,
    ) -> None:
        destination = self.project_root / "runs/updaters/ahe" / candidate_id
        destination.mkdir(parents=True)
        for source, name in (
            (output.trace_path, "evolve_trace.json"),
            (output.summary_path, "evolve_summary.md"),
        ):
            if source is not None and source.is_file():
                shutil.copy2(source, destination / name)
        metadata = {
            "schema_version": "1.0",
            "updater": {"name": self.name, "version": self.version},
            "input_digest": canonical_digest(
                {
                    "parent_snapshot": parent_snapshot,
                    "failure_bundle": failure_bundle,
                    "asset_manifest": asset_manifest,
                    "mutation_policy": mutation_policy,
                }
            ),
            "patch_digest": file_digest(patch_path),
            "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens,
            "cache_read_tokens": output.cache_read_tokens,
            "model_call_count": output.model_call_count,
            "unresolved_model_call_count": output.unresolved_model_call_count,
            "cost": str(output.cost) if output.cost is not None else None,
            "cost_status": output.cost_status.value,
            "duration_ms": output.duration_ms,
            "attempt_artifact_root": (
                output.attempt_artifact_root.relative_to(self.project_root).as_posix()
                if output.attempt_artifact_root is not None
                else None
            ),
            "exit_code": output.exit_code,
            "stderr_summary": output.stderr[:400],
            "native_selection_signal": {
                "kind": "emission_order",
                "ordinal": emission_ordinal,
                "source": "ahe.run_evolve_agent",
            },
            "unsupported_fields": ["native_score", "native_selector"],
        }
        (destination / "run_metadata.json").write_bytes(
            canonical_json_bytes(metadata) + b"\n"
        )


def _subprocess_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _sandbox_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


_AHE_DRIVER = r'''from __future__ import annotations
import hashlib
import json
import os
import re
import time
import traceback
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import evolve
import openai
from nexau.archs.main_sub.execution.llm_caller import LLMCaller

root = Path(os.environ["AGENTLOOPGATE_AHE_EXPERIMENT"]).resolve()
usage_path = root / "ahe_model_usage.jsonl"
attempt_id = os.environ["AGENTLOOPGATE_AHE_ATTEMPT_ID"]
query = (root / "query.txt").read_text(encoding="utf-8")
iteration = root / "runs/iteration_001"
job = iteration / "input/benchmark/agentloopgate"
job.mkdir(parents=True, exist_ok=True)
secret_pattern = re.compile(r"(?i)(?:sk|api[_-]?key|token)[=: ]+[A-Za-z0-9._-]{12,}")

input_price = Decimal(os.environ["AGENTLOOPGATE_INPUT_PRICE_PER_MILLION"])
cache_price = Decimal(os.environ["AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION"])
output_price = Decimal(os.environ["AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION"])
million = Decimal(1_000_000)


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def append_event(**values):
    payload = {
        "schema_version": "1.1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id_hash": digest({"attempt_id": attempt_id}),
        "model": os.environ["LLM_MODEL"],
        "duration_ms": None,
        "input_tokens": None,
        "cache_read_tokens": None,
        "output_tokens": None,
        "provider_retry_count": 0,
        "cost_usd": None,
        "exit_code": None,
        "error_type": None,
        "error_message": None,
        **values,
    }
    event_digest = digest(payload)
    event = {
        **payload,
        "event_id": "MCE_" + event_digest.removeprefix("sha256:")[:24].upper(),
        "event_digest": event_digest,
    }
    encoded = canonical_bytes(event) + b"\n"
    descriptor = os.open(usage_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def nonnegative_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def cache_tokens(usage):
    details = usage.get("prompt_tokens_details") or {}
    return nonnegative_int(
        usage.get(
            "prompt_cache_hit_tokens",
            usage.get("cache_read_input_tokens", details.get("cached_tokens", 0)),
        )
    )


# Disable SDK-owned network retries. Nexau is separately pinned to one total
# attempt below, so each STARTED event corresponds to at most one wire request.
original_openai_init = openai.OpenAI.__init__
def openai_init(self, *args, **kwargs):
    kwargs["max_retries"] = 0
    return original_openai_init(self, *args, **kwargs)
openai.OpenAI.__init__ = openai_init

original_async_openai_init = openai.AsyncOpenAI.__init__
def async_openai_init(self, *args, **kwargs):
    kwargs["max_retries"] = 0
    return original_async_openai_init(self, *args, **kwargs)
openai.AsyncOpenAI.__init__ = async_openai_init

original_call_llm = LLMCaller.call_llm
def recorded_call_llm(self, *args, **kwargs):
    call_id = "MC_" + uuid.uuid4().hex.upper()
    started = time.monotonic()
    append_event(
        call_id=call_id,
        state="started",
        cost_status="pending",
    )
    try:
        result = original_call_llm(self, *args, **kwargs)
    except BaseException as exc:
        append_event(
            call_id=call_id,
            state="failed",
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            cost_status="unavailable",
            error_type=type(exc).__name__,
            error_message=secret_pattern.sub("[REDACTED]", str(exc))[:2000] or type(exc).__name__,
        )
        raise
    usage = getattr(result, "usage", None) if result is not None else None
    if not isinstance(usage, dict) or not (
        ("input_tokens" in usage or "prompt_tokens" in usage)
        and ("completion_tokens" in usage or "output_tokens" in usage)
    ):
        append_event(
            call_id=call_id,
            state="failed",
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            cost_status="unavailable",
            error_type="UsageUnavailableError",
            error_message="AHE model response did not expose complete token usage",
        )
        return result
    total_input = nonnegative_int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    cached = cache_tokens(usage)
    uncached = max(0, total_input - cached)
    output = nonnegative_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    cost = (
        Decimal(uncached) * input_price
        + Decimal(cached) * cache_price
        + Decimal(output) * output_price
    ) / million
    append_event(
        call_id=call_id,
        state="completed",
        duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        input_tokens=uncached,
        cache_read_tokens=cached,
        output_tokens=output,
        cost_usd=format(cost, "f"),
        cost_status="exact",
        exit_code=0,
    )
    return result
LLMCaller.call_llm = recorded_call_llm

config = {
    "llm": {
        "api_key": os.environ["LLM_API_KEY"],
        "base_url": os.environ["LLM_BASE_URL"],
        "model": os.environ["LLM_MODEL"],
    },
    "evolve_agent": {},
    "agent_debugger": {"enabled": False},
}
try:
    result = evolve.run_evolve_agent(config, root, 1, query, job, iteration)
    summary = iteration / "evolve/evolve_summary.md"
    summary.write_text(result or "AHE completed.", encoding="utf-8")
    payload = {"ok": True}
except Exception as exc:
    payload = {
        "ok": False,
        "error": secret_pattern.sub("[REDACTED]", str(exc)),
        "traceback": secret_pattern.sub("[REDACTED]", traceback.format_exc()),
    }
    raise
finally:
    (root / "ahe_result.json").write_text(json.dumps(payload), encoding="utf-8")
'''
