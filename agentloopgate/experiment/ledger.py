"""Append-only attempt and cost evidence for protocol-bound experiments."""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.runtime.tau3_evidence import verified_task_attempt_events
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    ModelCallUsageEvent,
    verify_model_call_event,
)
from agentloopgate.schemas import ArtifactId, Digest, RunRecord, RunValidity
from agentloopgate.schemas.models import NonEmpty, StrictModel, UtcDateTime

_SECRET = re.compile(r"(?i)(?:sk|api[_-]?key|token)[=: ]+[A-Za-z0-9._-]{12,}")


class FormalCostAccounting(StrictModel):
    """Cost reconciliation across final τ³ evidence and every observed DSH call."""

    schema_version: Literal["1.1", "1.2", "1.3", "1.4"] = "1.1"
    batch_id: ArtifactId
    currency: Literal["USD"] = "USD"
    scope: Literal["whole_observed_attempt"] = "whole_observed_attempt"
    accounting_status: CostStatus
    accounting_notes: list[NonEmpty]
    valid_run_count: int = Field(ge=0)
    infra_invalid_count: int = Field(ge=0)
    agent_model_call_count: int = Field(ge=0)
    unresolved_agent_call_count: int = Field(ge=0)
    unretained_agent_call_count: int = Field(ge=0)
    agent_provider_retry_count: int = Field(ge=0)
    agent_input_tokens: int = Field(ge=0)
    agent_cache_read_tokens: int = Field(ge=0)
    agent_output_tokens: int = Field(ge=0)
    user_model_call_count_retained: int = Field(ge=0)
    user_input_tokens_retained: int = Field(ge=0)
    user_cache_read_tokens_retained: int = Field(ge=0)
    user_output_tokens_retained: int = Field(ge=0)
    valid_agent_cost_usd: Decimal = Field(ge=0)
    valid_user_cost_usd: Decimal | None = Field(default=None, ge=0)
    infra_agent_cost_usd: Decimal | None = Field(default=None, ge=0)
    infra_user_cost_usd: Decimal | None = Field(default=None, ge=0)
    observed_agent_attempt_cost_usd: Decimal | None = Field(default=None, ge=0)
    retained_user_cost_usd: Decimal | None = Field(default=None, ge=0)
    total_cost_lower_bound_usd: Decimal | None = Field(default=None, ge=0)
    scored_valid_mean_agent_cost_usd: Decimal | None = Field(default=None, ge=0)
    scored_valid_mean_total_cost_usd: Decimal | None = Field(default=None, ge=0)
    valid_cost_status: CostStatus | None = None
    user_model_call_count: int | None = Field(default=None, ge=0)
    unresolved_user_call_count: int | None = Field(default=None, ge=0)
    unretained_user_call_count: int | None = Field(default=None, ge=0)
    user_provider_retry_count: int | None = Field(default=None, ge=0)
    user_input_tokens: int | None = Field(default=None, ge=0)
    user_cache_read_tokens: int | None = Field(default=None, ge=0)
    user_output_tokens: int | None = Field(default=None, ge=0)
    observed_user_attempt_cost_usd: Decimal | None = Field(default=None, ge=0)
    valid_cost_source: Literal["direct_task_attempt_model_calls"] | None = None
    direct_task_attempt_count: int | None = Field(default=None, ge=0)
    direct_valid_task_attempt_count: int | None = Field(default=None, ge=0)
    direct_infra_task_attempt_count: int | None = Field(default=None, ge=0)
    direct_task_attempt_digest: Digest | None = None
    raw_valid_agent_cost_usd: Decimal | None = Field(default=None, ge=0)
    raw_valid_user_cost_usd: Decimal | None = Field(default=None, ge=0)
    raw_direct_cost_mismatch_count: int | None = Field(default=None, ge=0)
    cost_digest: Digest

    @model_validator(mode="after")
    def enhanced_fields_match_version(self) -> FormalCostAccounting:
        enhanced = (
            "valid_cost_status",
            "user_model_call_count",
            "unresolved_user_call_count",
            "unretained_user_call_count",
            "user_provider_retry_count",
            "user_input_tokens",
            "user_cache_read_tokens",
            "user_output_tokens",
        )
        present = [getattr(self, name) is not None for name in enhanced]
        if self.schema_version in {"1.2", "1.3", "1.4"} and not all(present):
            raise ValueError("cost accounting 1.2+ requires valid and user-call evidence")
        if self.schema_version == "1.1" and any(present):
            raise ValueError("cost accounting 1.1 cannot contain 1.2 evidence fields")
        direct = (
            "valid_cost_source",
            "direct_task_attempt_count",
            "direct_valid_task_attempt_count",
            "direct_infra_task_attempt_count",
            "direct_task_attempt_digest",
            "raw_valid_agent_cost_usd",
            "raw_direct_cost_mismatch_count",
        )
        direct_present = [getattr(self, name) is not None for name in direct]
        if self.schema_version in {"1.3", "1.4"} and not all(direct_present):
            raise ValueError("cost accounting 1.3+ requires direct task-attempt lineage")
        if self.schema_version not in {"1.3", "1.4"} and any(direct_present):
            raise ValueError("only cost accounting 1.3+ can contain direct lineage")
        if self.schema_version == "1.4":
            expected_mean = (
                (self.valid_agent_cost_usd + (self.valid_user_cost_usd or Decimal(0)))
                / self.valid_run_count
                if self.valid_cost_status is CostStatus.EXACT and self.valid_run_count
                else None
            )
            if self.scored_valid_mean_total_cost_usd != expected_mean:
                raise ValueError(
                    "cost accounting 1.4 total mean must match exact direct valid cost"
                )
        elif self.scored_valid_mean_total_cost_usd is not None:
            raise ValueError("only cost accounting 1.4 can contain total mean cost")
        return self


class ExperimentAttemptEvent(StrictModel):
    """One immutable state transition in a formal or ablation attempt."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: ArtifactId
    attempt_id: ArtifactId
    experiment_id: ArtifactId
    operation: NonEmpty
    state: AttemptState
    recorded_at: UtcDateTime
    protocol_digest: Digest
    study_digest: Digest | None = None
    source_revision: str | None = None
    stage: str | None = None
    batch_id: ArtifactId | None = None
    snapshot_id: ArtifactId | None = None
    candidate_id: ArtifactId | None = None
    spec_digest: Digest | None = None
    command: list[str] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, ge=0)
    exit_code: int | None = None
    resumed: bool = False
    cost_status: CostStatus
    known_cost_usd: Decimal | None = Field(default=None, ge=0)
    cost_artifact: str | None = None
    cost_digest: Digest | None = None
    result_artifacts: dict[str, Digest] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    recovery_action: str | None = None
    event_digest: Digest

    @model_validator(mode="after")
    def lifecycle_is_consistent(self) -> ExperimentAttemptEvent:
        if self.state is AttemptState.STARTED and self.cost_status is not CostStatus.PENDING:
            raise ValueError("started attempts require pending cost status")
        if self.state is AttemptState.FAILED and not self.error_type:
            raise ValueError("failed attempts require an error type")
        if self.cost_status is CostStatus.EXACT and self.known_cost_usd is None:
            raise ValueError("exact attempt cost requires a value")
        if any(value < 0 for value in self.counters.values()):
            raise ValueError("attempt counters must be non-negative")
        return self


class AttemptHandle:
    def __init__(
        self,
        ledger: ExperimentAttemptLedger,
        event: ExperimentAttemptEvent,
        started_monotonic: float,
    ) -> None:
        self.ledger = ledger
        self.event = event
        self.started_monotonic = started_monotonic

    @property
    def attempt_id(self) -> str:
        return self.event.attempt_id


class ExperimentAttemptLedger:
    """Write-once event ledger; a logging failure aborts protocol-bound work."""

    def __init__(self, project_root: Path, experiment_id: str) -> None:
        self.root = project_root.resolve()
        self.experiment_id = experiment_id
        self.path = self.root / "runs/experiments" / experiment_id / "attempt_ledger"

    def begin(
        self,
        *,
        operation: str,
        protocol_digest: str,
        study_digest: str | None = None,
        source_revision: str | None = None,
        stage: str | None = None,
        batch_id: str | None = None,
        snapshot_id: str | None = None,
        candidate_id: str | None = None,
        spec_digest: str | None = None,
        command: list[str] | None = None,
        recovery_action: str | None = None,
    ) -> AttemptHandle:
        attempt_id = f"ATT_{uuid4().hex.upper()}"
        event = self._event(
            attempt_id=attempt_id,
            operation=operation,
            state=AttemptState.STARTED,
            protocol_digest=protocol_digest,
            study_digest=study_digest,
            source_revision=source_revision,
            stage=stage,
            batch_id=batch_id,
            snapshot_id=snapshot_id,
            candidate_id=candidate_id,
            spec_digest=spec_digest,
            command=command or [],
            cost_status=CostStatus.PENDING,
            recovery_action=recovery_action,
        )
        self._append(event)
        return AttemptHandle(self, event, time.monotonic())

    def complete(
        self,
        handle: AttemptHandle,
        *,
        exit_code: int,
        resumed: bool,
        cost: FormalCostAccounting,
        cost_artifact: Path,
        result_artifacts: dict[str, str],
        counters: dict[str, int],
        attempt_cost_status: CostStatus | None = None,
        attempt_known_cost_usd: Decimal | None = None,
    ) -> ExperimentAttemptEvent:
        event = self._event_from_handle(
            handle,
            state=AttemptState.COMPLETED,
            duration_ms=_duration_ms(handle.started_monotonic),
            exit_code=exit_code,
            resumed=resumed,
            cost_status=attempt_cost_status or cost.accounting_status,
            known_cost_usd=(
                attempt_known_cost_usd
                if attempt_known_cost_usd is not None
                else cost.total_cost_lower_bound_usd
            ),
            cost_artifact=cost_artifact.relative_to(self.root).as_posix(),
            cost_digest=cost.cost_digest,
            result_artifacts=result_artifacts,
            counters=counters,
        )
        self._append(event)
        return event

    def fail(
        self,
        handle: AttemptHandle,
        exc: BaseException,
        *,
        exit_code: int | None = None,
        recovery_action: str,
        cost_status: CostStatus = CostStatus.UNAVAILABLE,
        known_cost_usd: Decimal | None = None,
        result_artifacts: dict[str, str] | None = None,
    ) -> ExperimentAttemptEvent:
        event = self._event_from_handle(
            handle,
            state=AttemptState.FAILED,
            duration_ms=_duration_ms(handle.started_monotonic),
            exit_code=exit_code,
            cost_status=cost_status,
            known_cost_usd=known_cost_usd,
            result_artifacts=result_artifacts or {},
            error_type=type(exc).__name__,
            error_message=_sanitize(str(exc)) or type(exc).__name__,
            recovery_action=recovery_action,
        )
        self._append(event)
        return event

    def complete_no_model_operation(
        self,
        handle: AttemptHandle,
        *,
        exit_code: int,
        result_artifacts: dict[str, str],
        counters: dict[str, int] | None = None,
    ) -> ExperimentAttemptEvent:
        event = self._event_from_handle(
            handle,
            state=AttemptState.COMPLETED,
            duration_ms=_duration_ms(handle.started_monotonic),
            exit_code=exit_code,
            cost_status=CostStatus.NOT_APPLICABLE,
            known_cost_usd=Decimal(0),
            result_artifacts=result_artifacts,
            counters=counters or {},
        )
        self._append(event)
        return event

    def events_for_batch(self, batch_id: str) -> list[ExperimentAttemptEvent]:
        events: list[ExperimentAttemptEvent] = []
        if not self.path.is_dir():
            return events
        for path in sorted(self.path.glob("ATT_*/*.json")):
            event = ExperimentAttemptEvent.model_validate_json(path.read_text(encoding="utf-8"))
            _verify_event(event)
            if event.batch_id == batch_id:
                events.append(event)
        events.sort(
            key=lambda event: (
                event.recorded_at,
                0 if event.state is AttemptState.STARTED else 1,
                event.event_id,
            )
        )
        return events

    def has_completed_batch(self, batch_id: str, spec_digest: str) -> bool:
        return any(
            event.state is AttemptState.COMPLETED and event.spec_digest == spec_digest
            for event in self.events_for_batch(batch_id)
        )

    def _event_from_handle(
        self,
        handle: AttemptHandle,
        **updates: Any,
    ) -> ExperimentAttemptEvent:
        base = handle.event.model_dump(
            mode="python", exclude={"event_id", "event_digest", "recorded_at"}
        )
        base.update(updates)
        return self._event(**base)

    def _event(self, **payload: Any) -> ExperimentAttemptEvent:
        payload["experiment_id"] = self.experiment_id
        payload["recorded_at"] = datetime.now(UTC)
        payload.setdefault("resumed", False)
        payload.setdefault("result_artifacts", {})
        payload.setdefault("counters", {})
        draft = ExperimentAttemptEvent.model_validate(
            {
                **payload,
                "event_id": "EV_" + "0" * 24,
                "event_digest": "sha256:" + "0" * 64,
            }
        )
        normalized = draft.model_dump(
            mode="python", exclude={"event_id", "event_digest"}
        )
        digest = canonical_digest(normalized)
        return draft.model_copy(
            update={
                "event_id": f"EV_{digest.removeprefix('sha256:')[:24].upper()}",
                "event_digest": digest,
            }
        )

    def _append(self, event: ExperimentAttemptEvent) -> None:
        _verify_event(event)
        target = self.path / event.attempt_id / f"{event.event_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical_json_bytes(event.model_dump(mode="json")) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise RuntimeError(f"attempt ledger write failed: {target}") from exc


def reconcile_formal_costs(
    *,
    batch_id: str,
    raw_result_path: Path,
    records: list[RunRecord],
    model_usage_path: Path | None,
    user_model_usage_path: Path | None = None,
    task_attempt_path: Path | None = None,
    frozen_token_prices: tuple[Decimal, Decimal, Decimal] | None = None,
    cost_gate_scope: Literal["whole_attempt", "valid_runs"] = "whole_attempt",
) -> FormalCostAccounting:
    """Reconcile final τ³ costs with all separately journaled agent calls."""

    if cost_gate_scope == "valid_runs":
        return _reconcile_formal_costs_v12(
            batch_id=batch_id,
            raw_result_path=raw_result_path,
            records=records,
            model_usage_path=model_usage_path,
            user_model_usage_path=user_model_usage_path,
            task_attempt_path=task_attempt_path,
            frozen_token_prices=frozen_token_prices,
        )

    raw = json.loads(raw_result_path.read_text(encoding="utf-8"))
    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ValueError("formal cost reconciliation requires τ³ simulations")
    valid = [record for record in records if record.run_validity is RunValidity.VALID]
    infra = [record for record in records if record.run_validity is RunValidity.INFRA_INVALID]
    valid_agent = sum((record.cost or Decimal(0) for record in valid), Decimal(0))
    infra_agent_values = [record.cost for record in infra if record.cost is not None]
    infra_agent = (
        sum(infra_agent_values, Decimal(0))
        if len(infra_agent_values) == len(infra)
        else None
    )
    user_costs: list[tuple[bool, Decimal | None]] = []
    agent_raw_calls = 0
    agent_raw_input = agent_raw_cache = agent_raw_output = 0
    user_calls = 0
    user_input = user_cache = user_output = 0
    for simulation in simulations:
        if not isinstance(simulation, dict):
            raise ValueError("τ³ simulation must be an object for cost reconciliation")
        is_infra = simulation.get("termination_reason") == "infrastructure_error"
        user_costs.append((is_infra, _optional_decimal(simulation.get("user_cost"))))
        messages = simulation.get("messages") or []
        if not isinstance(messages, list):
            raise ValueError("τ³ messages must be a list for cost reconciliation")
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                continue
            usage = message["usage"]
            role = message.get("role")
            if role == "assistant":
                agent_raw_calls += 1
                agent_raw_input += _token(usage, "input_tokens", "prompt_tokens")
                agent_raw_cache += _token(
                    usage, "cache_read_tokens", "cache_read_tokens"
                )
                agent_raw_output += _token(
                    usage, "output_tokens", "completion_tokens"
                )
            elif role == "user":
                user_calls += 1
                user_input += _token(usage, "input_tokens", "prompt_tokens")
                user_cache += _token(usage, "cache_read_tokens", "cache_read_tokens")
                user_output += _token(usage, "output_tokens", "completion_tokens")

    valid_user_values = [value for is_infra, value in user_costs if not is_infra]
    valid_user = (
        sum((value or Decimal(0) for value in valid_user_values), Decimal(0))
        if all(value is not None for value in valid_user_values)
        else None
    )
    infra_user_values = [value for is_infra, value in user_costs if is_infra]
    infra_user = (
        sum((value or Decimal(0) for value in infra_user_values), Decimal(0))
        if all(value is not None for value in infra_user_values)
        else None
    )
    retained_user_values = [value for _, value in user_costs]
    retained_user = (
        sum((value or Decimal(0) for value in retained_user_values), Decimal(0))
        if all(value is not None for value in retained_user_values)
        else None
    )

    calls = _model_call_terminals(model_usage_path)
    unresolved = _unresolved_model_calls(model_usage_path)
    exact_calls = [call for call in calls if call.cost_status is CostStatus.EXACT]
    known_calls = [
        call
        for call in calls
        if call.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
        and call.cost_usd is not None
    ]
    provider_retries = sum(call.provider_retry_count or 0 for call in calls)
    retry_observation_complete = all(
        call.provider_retry_count is not None for call in calls
    )
    observed_agent = (
        sum((call.cost_usd or Decimal(0) for call in exact_calls), Decimal(0))
        if calls and len(exact_calls) == len(calls) and not unresolved
        else None
    )
    known_agent = sum((call.cost_usd or Decimal(0) for call in known_calls), Decimal(0))
    unretained_agent_calls = max(0, len(calls) - agent_raw_calls)
    notes: list[str] = []
    if model_usage_path is None or not model_usage_path.is_file():
        notes.append(
            "agent model-call ledger unavailable; retained τ³ agent cost used as a "
            "lower bound"
        )
        known_agent = sum((record.cost or Decimal(0) for record in records), Decimal(0))
    if unresolved:
        notes.append(f"{unresolved} agent calls have STARTED without a terminal usage event")
    if len(exact_calls) != len(calls):
        notes.append("one or more terminal agent calls have unavailable cost evidence")
    if not retry_observation_complete and calls:
        notes.append("one or more agent calls lack provider-retry observability")
    if provider_retries:
        notes.append(
            f"{provider_retries} provider retries occurred; failed-request billing is "
            "not included in the known agent cost"
        )
    if unretained_agent_calls:
        notes.append(
            f"{unretained_agent_calls} agent calls are outside retained final simulations; "
            "failed-attempt user-simulator cost may be unavailable"
        )
    if retained_user is None:
        notes.append("one or more retained simulations lack exact user-simulator cost")

    if model_usage_path is not None:
        agent_exact = (
            model_usage_path.is_file()
            and bool(calls)
            and observed_agent is not None
            and retry_observation_complete
        )
    else:
        agent_exact = not infra and all(record.cost is not None for record in records)
        observed_agent = known_agent if agent_exact else None
    total_exact = agent_exact and retained_user is not None and unretained_agent_calls == 0
    known_user = sum((value or Decimal(0) for value in retained_user_values), Decimal(0))
    lower_bound = known_agent + known_user
    if total_exact:
        status = CostStatus.EXACT
    elif lower_bound > 0:
        status = CostStatus.PARTIAL
    else:
        status = CostStatus.UNAVAILABLE
    if status is CostStatus.EXACT:
        notes.append("all observed agent calls and retained user-simulator calls have exact cost")
    elif not notes:
        notes.append("whole-attempt cost is not fully observable")

    payload = {
        "schema_version": "1.1",
        "batch_id": batch_id,
        "currency": "USD",
        "scope": "whole_observed_attempt",
        "accounting_status": status,
        "accounting_notes": notes,
        "valid_run_count": len(valid),
        "infra_invalid_count": len(infra),
        "agent_model_call_count": len(calls) if calls else agent_raw_calls,
        "unresolved_agent_call_count": unresolved,
        "unretained_agent_call_count": unretained_agent_calls,
        "agent_provider_retry_count": provider_retries,
        "agent_input_tokens": (
            sum(call.input_tokens or 0 for call in exact_calls)
            if calls
            else agent_raw_input
        ),
        "agent_cache_read_tokens": (
            sum(call.cache_read_tokens or 0 for call in exact_calls)
            if calls
            else agent_raw_cache
        ),
        "agent_output_tokens": (
            sum(call.output_tokens or 0 for call in exact_calls)
            if calls
            else agent_raw_output
        ),
        "user_model_call_count_retained": user_calls,
        "user_input_tokens_retained": user_input,
        "user_cache_read_tokens_retained": user_cache,
        "user_output_tokens_retained": user_output,
        "valid_agent_cost_usd": valid_agent,
        "valid_user_cost_usd": valid_user,
        "infra_agent_cost_usd": infra_agent,
        "infra_user_cost_usd": infra_user,
        "observed_agent_attempt_cost_usd": observed_agent,
        "retained_user_cost_usd": retained_user,
        "total_cost_lower_bound_usd": lower_bound,
        "scored_valid_mean_agent_cost_usd": (
            valid_agent / len(valid) if valid else None
        ),
    }
    return FormalCostAccounting.model_validate(
        {**payload, "cost_digest": canonical_digest(payload)}
    )


def _reconcile_formal_costs_v12(
    *,
    batch_id: str,
    raw_result_path: Path,
    records: list[RunRecord],
    model_usage_path: Path | None,
    user_model_usage_path: Path | None,
    task_attempt_path: Path | None,
    frozen_token_prices: tuple[Decimal, Decimal, Decimal] | None,
) -> FormalCostAccounting:
    """Separate valid-run exactness from whole-attempt operational accounting."""

    raw = json.loads(raw_result_path.read_text(encoding="utf-8"))
    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ValueError("formal cost reconciliation requires τ³ simulations")
    valid = [record for record in records if record.run_validity is RunValidity.VALID]
    infra = [record for record in records if record.run_validity is RunValidity.INFRA_INVALID]
    valid_agent_values = [record.cost for record in valid]
    valid_agent = sum(
        (value or Decimal(0) for value in valid_agent_values), Decimal(0)
    )
    valid_agent_complete = all(value is not None for value in valid_agent_values)
    raw_valid_agent = valid_agent
    infra_agent_values = [record.cost for record in infra]
    infra_agent = (
        sum((value or Decimal(0) for value in infra_agent_values), Decimal(0))
        if all(value is not None for value in infra_agent_values)
        else None
    )

    user_costs: list[tuple[bool, Decimal | None]] = []
    agent_raw_calls = 0
    user_retained_calls = 0
    user_retained_input = user_retained_cache = user_retained_output = 0
    for simulation in simulations:
        if not isinstance(simulation, dict):
            raise ValueError("τ³ simulation must be an object for cost reconciliation")
        is_infra = simulation.get("termination_reason") == "infrastructure_error"
        user_costs.append((is_infra, _optional_decimal(simulation.get("user_cost"))))
        messages = simulation.get("messages") or []
        if not isinstance(messages, list):
            raise ValueError("τ³ messages must be a list for cost reconciliation")
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                continue
            usage = message["usage"]
            if message.get("role") == "assistant":
                agent_raw_calls += 1
            elif message.get("role") == "user":
                user_retained_calls += 1
                user_retained_input += _token(usage, "input_tokens", "prompt_tokens")
                user_retained_cache += _token(
                    usage, "cache_read_tokens", "cache_read_tokens"
                )
                user_retained_output += _token(
                    usage, "output_tokens", "completion_tokens"
                )

    valid_user_values = [value for is_infra, value in user_costs if not is_infra]
    valid_user = (
        sum((value or Decimal(0) for value in valid_user_values), Decimal(0))
        if all(value is not None for value in valid_user_values)
        else None
    )
    raw_valid_user = valid_user
    infra_user_values = [value for is_infra, value in user_costs if is_infra]
    infra_user = (
        sum((value or Decimal(0) for value in infra_user_values), Decimal(0))
        if all(value is not None for value in infra_user_values)
        else None
    )
    retained_values = [value for _, value in user_costs]
    retained_user = (
        sum((value or Decimal(0) for value in retained_values), Decimal(0))
        if all(value is not None for value in retained_values)
        else None
    )
    retained_user_known = sum(
        (value for value in retained_values if value is not None), Decimal(0)
    )

    agent_calls = _model_call_terminals(model_usage_path)
    unresolved_agent = _unresolved_model_calls(model_usage_path)
    exact_agent_calls = [
        call for call in agent_calls if call.cost_status is CostStatus.EXACT
    ]
    known_agent_calls = [
        call
        for call in agent_calls
        if call.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
        and call.cost_usd is not None
    ]
    agent_provider_retries = sum(call.provider_retry_count or 0 for call in agent_calls)
    agent_retry_complete = all(
        call.provider_retry_count is not None for call in agent_calls
    )
    known_agent = sum(
        (call.cost_usd or Decimal(0) for call in known_agent_calls), Decimal(0)
    )
    observed_agent = (
        known_agent
        if agent_calls
        and len(exact_agent_calls) == len(agent_calls)
        and not unresolved_agent
        and agent_retry_complete
        else None
    )
    unretained_agent_calls = max(0, len(agent_calls) - agent_raw_calls)

    user_calls = _model_call_terminals(user_model_usage_path)
    unresolved_user = _unresolved_model_calls(user_model_usage_path)
    exact_user_calls = [
        call for call in user_calls if call.cost_status is CostStatus.EXACT
    ]
    known_user_calls = [
        call
        for call in user_calls
        if call.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
        and call.cost_usd is not None
    ]
    user_provider_retries = sum(call.provider_retry_count or 0 for call in user_calls)
    user_retry_complete = all(call.provider_retry_count is not None for call in user_calls)
    user_known_from_ledger = sum(
        (call.cost_usd or Decimal(0) for call in known_user_calls), Decimal(0)
    )
    known_user = max(user_known_from_ledger, retained_user_known)
    user_ledger_exact = (
        user_model_usage_path is not None
        and user_model_usage_path.is_file()
        and bool(user_calls or not user_retained_calls)
        and len(exact_user_calls) == len(user_calls)
        and len(user_calls) >= user_retained_calls
        and not unresolved_user
        and user_retry_complete
    )
    observed_user = known_user if user_ledger_exact else None
    unretained_user_calls = max(0, len(user_calls) - user_retained_calls)

    direct_lineage = None
    if task_attempt_path is not None:
        direct_lineage = _direct_cost_lineage(
            simulations=simulations,
            records=records,
            task_attempt_path=task_attempt_path,
            model_usage_path=model_usage_path,
            user_model_usage_path=user_model_usage_path,
            frozen_token_prices=frozen_token_prices,
        )
        valid_agent = direct_lineage.agent.valid_known
        valid_agent_complete = direct_lineage.agent.valid_exact
        valid_user = (
            direct_lineage.user.valid_known
            if user_model_usage_path is not None and user_model_usage_path.is_file()
            else None
        )
        infra_agent = (
            direct_lineage.agent.infra_known
            if direct_lineage.agent.infra_exact
            else None
        )
        infra_user = (
            direct_lineage.user.infra_known
            if direct_lineage.user.infra_exact
            else None
        )
        retained_user = (
            direct_lineage.user.retained_known
            if user_model_usage_path is not None and user_model_usage_path.is_file()
            else None
        )

    valid_exact = (
        valid_agent_complete
        and valid_user is not None
        and (direct_lineage is None or direct_lineage.user.valid_exact)
    )
    valid_known = valid_agent + (valid_user or Decimal(0))
    valid_status = (
        CostStatus.EXACT
        if valid_exact
        else CostStatus.PARTIAL
        if valid_known > 0
        else CostStatus.UNAVAILABLE
    )
    agent_exact = observed_agent is not None
    total_exact = agent_exact and user_ledger_exact
    lower_bound = known_agent + known_user
    status = (
        CostStatus.EXACT
        if total_exact
        else CostStatus.PARTIAL
        if lower_bound > 0
        else CostStatus.UNAVAILABLE
    )

    notes: list[str] = []
    if direct_lineage is not None:
        notes.append(
            "valid-run cost is derived from direct final task-attempt model-call "
            "lineage; retained raw cost is comparison evidence only"
        )
        if direct_lineage.raw_mismatch_count:
            notes.append(
                f"{direct_lineage.raw_mismatch_count} retained raw cost values differ "
                "from frozen-price direct call accounting"
            )
    if valid_status is CostStatus.EXACT:
        notes.append("all scored valid runs contain exact agent and user cost")
    else:
        notes.append("one or more scored valid runs lack exact agent or user cost")
    if unresolved_agent:
        notes.append(f"{unresolved_agent} agent calls have STARTED without a terminal event")
    if len(exact_agent_calls) != len(agent_calls):
        notes.append("one or more terminal agent calls have unavailable cost evidence")
    if not agent_retry_complete and agent_calls:
        notes.append("one or more agent calls lack provider-retry observability")
    if agent_provider_retries:
        notes.append(
            f"{agent_provider_retries} agent provider retries occurred; failed-request "
            "billing may be unavailable"
        )
    if unretained_agent_calls:
        notes.append(
            f"{unretained_agent_calls} agent calls are outside retained final simulations"
        )
    if user_model_usage_path is None or not user_model_usage_path.is_file():
        notes.append("user model-call ledger unavailable; retained user cost is a lower bound")
    if unresolved_user:
        notes.append(f"{unresolved_user} user calls have STARTED without a terminal event")
    if len(exact_user_calls) != len(user_calls):
        notes.append("one or more terminal user calls have unavailable cost evidence")
    if user_provider_retries:
        notes.append(
            f"{user_provider_retries} user provider retries occurred; failed-request "
            "billing may be unavailable"
        )
    if unretained_user_calls:
        notes.append(
            f"{unretained_user_calls} user calls are outside retained final simulations"
        )
    if status is CostStatus.EXACT:
        notes.append("all observed agent and user calls have exact terminal cost evidence")
    else:
        notes.append(
            "whole-attempt total is an explicit lower bound; unknown scopes are not zero-filled"
        )

    payload = {
        "schema_version": "1.4" if direct_lineage is not None else "1.2",
        "batch_id": batch_id,
        "currency": "USD",
        "scope": "whole_observed_attempt",
        "accounting_status": status,
        "accounting_notes": notes,
        "valid_run_count": len(valid),
        "infra_invalid_count": len(infra),
        "agent_model_call_count": len(agent_calls),
        "unresolved_agent_call_count": unresolved_agent,
        "unretained_agent_call_count": unretained_agent_calls,
        "agent_provider_retry_count": agent_provider_retries,
        "agent_input_tokens": sum(call.input_tokens or 0 for call in exact_agent_calls),
        "agent_cache_read_tokens": sum(
            call.cache_read_tokens or 0 for call in exact_agent_calls
        ),
        "agent_output_tokens": sum(call.output_tokens or 0 for call in exact_agent_calls),
        "user_model_call_count_retained": user_retained_calls,
        "user_input_tokens_retained": user_retained_input,
        "user_cache_read_tokens_retained": user_retained_cache,
        "user_output_tokens_retained": user_retained_output,
        "valid_agent_cost_usd": valid_agent,
        "valid_user_cost_usd": valid_user,
        "infra_agent_cost_usd": infra_agent,
        "infra_user_cost_usd": infra_user,
        "observed_agent_attempt_cost_usd": observed_agent,
        "retained_user_cost_usd": retained_user,
        "total_cost_lower_bound_usd": lower_bound,
        "scored_valid_mean_agent_cost_usd": (
            valid_agent / len(valid) if valid and valid_agent_complete else None
        ),
        "scored_valid_mean_total_cost_usd": (
            valid_known / len(valid)
            if direct_lineage is not None
            and valid
            and valid_status is CostStatus.EXACT
            else None
        ),
        "valid_cost_status": valid_status,
        "user_model_call_count": len(user_calls),
        "unresolved_user_call_count": unresolved_user,
        "unretained_user_call_count": unretained_user_calls,
        "user_provider_retry_count": user_provider_retries,
        "user_input_tokens": sum(call.input_tokens or 0 for call in exact_user_calls),
        "user_cache_read_tokens": sum(
            call.cache_read_tokens or 0 for call in exact_user_calls
        ),
        "user_output_tokens": sum(call.output_tokens or 0 for call in exact_user_calls),
        "observed_user_attempt_cost_usd": observed_user,
    }
    if direct_lineage is not None:
        payload.update(
            {
                "valid_cost_source": "direct_task_attempt_model_calls",
                "direct_task_attempt_count": direct_lineage.retained_count,
                "direct_valid_task_attempt_count": direct_lineage.valid_count,
                "direct_infra_task_attempt_count": direct_lineage.infra_count,
                "direct_task_attempt_digest": direct_lineage.identity_digest,
                "raw_valid_agent_cost_usd": raw_valid_agent,
                "raw_valid_user_cost_usd": raw_valid_user,
                "raw_direct_cost_mismatch_count": direct_lineage.raw_mismatch_count,
            }
        )
    return FormalCostAccounting.model_validate(
        {**payload, "cost_digest": canonical_digest(payload)}
    )


_TaskIdentity = tuple[str, int, int, int]
_RAW_COST_TOLERANCE = Decimal("0.000000000001")


@dataclass(frozen=True)
class _DirectChannelCost:
    valid_known: Decimal
    valid_exact: bool
    infra_known: Decimal
    infra_exact: bool
    retained_known: Decimal
    retained_exact: bool
    exact_by_identity: dict[_TaskIdentity, Decimal]


@dataclass(frozen=True)
class _DirectCostLineage:
    retained_count: int
    valid_count: int
    infra_count: int
    identity_digest: str
    agent: _DirectChannelCost
    user: _DirectChannelCost
    raw_mismatch_count: int


def _direct_cost_lineage(
    *,
    simulations: list[Any],
    records: list[RunRecord],
    task_attempt_path: Path,
    model_usage_path: Path | None,
    user_model_usage_path: Path | None,
    frozen_token_prices: tuple[Decimal, Decimal, Decimal] | None,
) -> _DirectCostLineage:
    """Bind every retained result to one completed task attempt and its calls."""

    if not task_attempt_path.is_file():
        raise ValueError("direct cost accounting requires a task-attempt ledger")
    if frozen_token_prices is None:
        raise ValueError("direct cost accounting requires frozen token prices")
    if any(not price.is_finite() or price < 0 for price in frozen_token_prices):
        raise ValueError("frozen token prices must be non-negative finite decimals")
    task_events = verified_task_attempt_events(task_attempt_path)
    if any(event.get("schema_version") != "1.1" for event in task_events):
        raise ValueError("direct cost accounting requires task-attempt ledger 1.1")
    completed_by_simulation: dict[str, dict[str, Any]] = {}
    for event in task_events:
        if event.get("state") != "completed":
            continue
        simulation_id = event.get("simulation_id")
        if not isinstance(simulation_id, str) or not simulation_id:
            raise ValueError("completed task attempt lacks its simulation id")
        if simulation_id in completed_by_simulation:
            raise ValueError("multiple completed task attempts claim one simulation")
        completed_by_simulation[simulation_id] = event

    retained: dict[_TaskIdentity, bool] = {}
    raw_costs: dict[_TaskIdentity, tuple[Decimal | None, Decimal | None]] = {}
    raw_positions: Counter[tuple[str, int]] = Counter()
    for simulation in simulations:
        if not isinstance(simulation, dict):
            raise ValueError("direct cost accounting requires object simulations")
        simulation_id = simulation.get("id")
        task_id = simulation.get("task_id")
        trial = simulation.get("trial")
        seed = simulation.get("seed")
        if (
            not isinstance(simulation_id, str)
            or not isinstance(task_id, str)
            or isinstance(trial, bool)
            or not isinstance(trial, int)
            or isinstance(seed, bool)
            or not isinstance(seed, int)
        ):
            raise ValueError(
                "direct cost accounting requires simulation id/task_id/trial/seed"
            )
        terminal = completed_by_simulation.get(simulation_id)
        if terminal is None:
            raise ValueError("retained simulation has no completed task-attempt lineage")
        if (
            terminal.get("task_id") != task_id
            or terminal.get("trial") != trial
            or terminal.get("seed") != seed
        ):
            raise ValueError("retained simulation changed task-attempt identity")
        attempt_index = terminal.get("attempt_index")
        if isinstance(attempt_index, bool) or not isinstance(attempt_index, int):
            raise ValueError("completed task attempt has no valid attempt index")
        identity = (task_id, trial, seed, attempt_index)
        if identity in retained:
            raise ValueError("retained results reuse one task-attempt identity")
        is_infra = simulation.get("termination_reason") == "infrastructure_error"
        terminal_infra = str(terminal.get("termination_reason", "")).lower().endswith(
            "infrastructure_error"
        )
        if is_infra != terminal_infra:
            raise ValueError("task-attempt and retained termination reasons disagree")
        retained[identity] = is_infra
        raw_costs[identity] = (
            _optional_decimal(simulation.get("agent_cost")),
            _optional_decimal(simulation.get("user_cost")),
        )
        raw_positions[(task_id, trial + 1)] += 1

    record_positions = Counter((record.task_id, record.trial_index) for record in records)
    if raw_positions != record_positions:
        raise ValueError("normalized records do not match retained task/trial positions")

    agent = _direct_channel_cost(
        model_usage_path,
        retained,
        frozen_token_prices=frozen_token_prices,
        channel="agent",
    )
    user = _direct_channel_cost(
        user_model_usage_path,
        retained,
        frozen_token_prices=frozen_token_prices,
        channel="user",
    )
    mismatch_count = 0
    for identity, is_infra in retained.items():
        raw_agent, raw_user = raw_costs[identity]
        for raw_value, exact_values in (
            (raw_agent, agent.exact_by_identity),
            (raw_user, user.exact_by_identity),
        ):
            direct_value = exact_values.get(identity)
            if direct_value is None:
                continue
            if raw_value is None:
                if not is_infra:
                    mismatch_count += 1
            elif abs(raw_value - direct_value) > _RAW_COST_TOLERANCE:
                mismatch_count += 1

    identities = [
        {
            "task_id": identity[0],
            "trial": identity[1],
            "seed": identity[2],
            "task_attempt_index": identity[3],
            "run_validity": "infra_invalid" if is_infra else "valid",
        }
        for identity, is_infra in sorted(retained.items())
    ]
    valid_count = sum(not is_infra for is_infra in retained.values())
    return _DirectCostLineage(
        retained_count=len(retained),
        valid_count=valid_count,
        infra_count=len(retained) - valid_count,
        identity_digest=canonical_digest(identities),
        agent=agent,
        user=user,
        raw_mismatch_count=mismatch_count,
    )


def _direct_channel_cost(
    path: Path | None,
    retained: dict[_TaskIdentity, bool],
    *,
    frozen_token_prices: tuple[Decimal, Decimal, Decimal],
    channel: Literal["agent", "user"],
) -> _DirectChannelCost:
    if path is None or not path.is_file():
        return _DirectChannelCost(
            valid_known=Decimal(0),
            valid_exact=False,
            infra_known=Decimal(0),
            infra_exact=False,
            retained_known=Decimal(0),
            retained_exact=False,
            exact_by_identity={},
        )
    events = _model_call_events(path)
    if any(event.schema_version != "1.2" for event in events):
        raise ValueError(f"direct {channel} cost accounting requires usage ledger 1.2")

    def identity(event: ModelCallUsageEvent) -> _TaskIdentity:
        assert event.task_id is not None
        assert event.trial is not None
        assert event.seed is not None
        assert event.task_attempt_index is not None
        return (
            event.task_id,
            event.trial,
            event.seed,
            event.task_attempt_index,
        )

    selected = [event for event in events if identity(event) in retained]
    started_by_identity: Counter[_TaskIdentity] = Counter(
        identity(event) for event in selected if event.state is AttemptState.STARTED
    )
    terminal_by_identity: Counter[_TaskIdentity] = Counter(
        identity(event) for event in selected if event.state is not AttemptState.STARTED
    )
    terminals = [event for event in selected if event.state is not AttemptState.STARTED]
    known_by_identity: dict[_TaskIdentity, Decimal] = {
        item: Decimal(0) for item in retained
    }
    exact_by_identity: dict[_TaskIdentity, Decimal] = {}
    for event in terminals:
        if event.cost_status is CostStatus.EXACT:
            if (
                event.input_tokens is None
                or event.cache_read_tokens is None
                or event.output_tokens is None
            ):
                raise ValueError(
                    f"exact {channel} cost requires complete token counters"
                )
            expected = (
                Decimal(event.input_tokens) * frozen_token_prices[0]
                + Decimal(event.cache_read_tokens) * frozen_token_prices[1]
                + Decimal(event.output_tokens) * frozen_token_prices[2]
            ) / Decimal(1_000_000)
            if event.cost_usd != expected:
                raise ValueError(
                    f"exact {channel} cost does not match frozen token prices"
                )
        if (
            event.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
            and event.cost_usd is not None
        ):
            item = identity(event)
            known_by_identity[item] += event.cost_usd
    for item, is_infra in retained.items():
        has_required_activity = started_by_identity[item] > 0 or is_infra
        complete = started_by_identity[item] == terminal_by_identity[item]
        item_terminals = [event for event in terminals if identity(event) == item]
        exact = (
            has_required_activity
            and complete
            and all(event.cost_status is CostStatus.EXACT for event in item_terminals)
            and all(event.provider_retry_count is not None for event in item_terminals)
        )
        if exact:
            exact_by_identity[item] = known_by_identity[item]

    valid_identities = {item for item, is_infra in retained.items() if not is_infra}
    infra_identities = set(retained) - valid_identities
    valid_known = sum(
        (known_by_identity[item] for item in valid_identities), Decimal(0)
    )
    infra_known = sum(
        (known_by_identity[item] for item in infra_identities), Decimal(0)
    )
    return _DirectChannelCost(
        valid_known=valid_known,
        valid_exact=valid_identities.issubset(exact_by_identity),
        infra_known=infra_known,
        infra_exact=infra_identities.issubset(exact_by_identity),
        retained_known=valid_known + infra_known,
        retained_exact=set(retained).issubset(exact_by_identity),
        exact_by_identity=exact_by_identity,
    )


def write_cost_accounting_once(path: Path, accounting: FormalCostAccounting) -> None:
    encoded = canonical_json_bytes(accounting.model_dump(mode="json")) + b"\n"
    if path.exists():
        if path.read_bytes() != encoded:
            raise RuntimeError("cost accounting conflicts with an existing artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def artifact_hashes(paths: dict[str, Path | None]) -> dict[str, str]:
    return {
        name: file_digest(path)
        for name, path in paths.items()
        if path is not None and path.is_file()
    }


def observed_usage_cost(
    path: Path | None,
    *,
    user_model_usage_path: Path | None = None,
    raw_result_path: Path | None = None,
) -> tuple[CostStatus, Decimal | None]:
    """Return a failed-attempt lower bound without claiming completeness."""

    calls = _model_call_terminals(path)
    _unresolved_model_calls(path)
    known_calls = [
        call
        for call in calls
        if call.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
        and call.cost_usd is not None
    ]
    known = sum((call.cost_usd or Decimal(0) for call in known_calls), Decimal(0))
    observed = bool(known_calls)
    raw_user_cost, raw_user_observed = _observed_raw_user_cost(raw_result_path)
    user_calls = _model_call_terminals(user_model_usage_path)
    user_known = sum(
        (
            call.cost_usd or Decimal(0)
            for call in user_calls
            if call.cost_status in {CostStatus.EXACT, CostStatus.PARTIAL}
            and call.cost_usd is not None
        ),
        Decimal(0),
    )
    known += max(user_known, raw_user_cost)
    observed = observed or bool(user_calls) or raw_user_observed
    if observed:
        # Failed batches can still omit failed-request bills, simulator attempts,
        # or local compute. Every recoverable value therefore remains a lower bound.
        return CostStatus.PARTIAL, known
    return CostStatus.UNAVAILABLE, None


def _observed_raw_user_cost(path: Path | None) -> tuple[Decimal, bool]:
    if path is None or not path.is_file():
        return Decimal(0), False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        simulations = raw.get("simulations")
        if not isinstance(simulations, list):
            return Decimal(0), False
        values: list[Decimal] = []
        for simulation in simulations:
            if not isinstance(simulation, dict) or simulation.get("user_cost") is None:
                continue
            value = _optional_decimal(simulation["user_cost"])
            if value is not None:
                values.append(value)
    except (OSError, json.JSONDecodeError, ValueError):
        # Cost recovery must not mask the original batch failure. The immutable raw
        # artifact remains attached to the Attempt for later incident reconciliation.
        return Decimal(0), False
    return sum(values, Decimal(0)), bool(values)


def _model_call_events(path: Path | None) -> list[ModelCallUsageEvent]:
    if path is None or not path.is_file():
        return []
    events: list[ModelCallUsageEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = ModelCallUsageEvent.model_validate_json(line)
        verify_model_call_event(event)
        events.append(event)
    started: dict[str, ModelCallUsageEvent] = {}
    terminal: set[str] = set()
    identity_fields = (
        "session_id_hash",
        "model",
        "task_id",
        "trial",
        "seed",
        "task_attempt_index",
    )
    for event in events:
        if event.state is AttemptState.STARTED:
            if event.call_id in started:
                raise ValueError("model call ledger contains duplicate STARTED events")
            started[event.call_id] = event
            continue
        initial = started.get(event.call_id)
        if initial is None:
            raise ValueError("model call terminal event has no STARTED event")
        if event.call_id in terminal:
            raise ValueError("model call ledger contains duplicate terminal events")
        if any(
            getattr(initial, field) != getattr(event, field)
            for field in identity_fields
        ):
            raise ValueError("model call lifecycle changed its direct identity")
        terminal.add(event.call_id)
    return events


def _model_call_terminals(path: Path | None) -> list[ModelCallUsageEvent]:
    events = _model_call_events(path)
    terminals: dict[str, ModelCallUsageEvent] = {}
    for event in events:
        if event.state is not AttemptState.STARTED:
            if event.call_id in terminals:
                raise ValueError("model call ledger contains duplicate terminal events")
            terminals[event.call_id] = event
    return list(terminals.values())


def _unresolved_model_calls(path: Path | None) -> int:
    events = _model_call_events(path)
    started = {event.call_id for event in events if event.state is AttemptState.STARTED}
    terminal = {event.call_id for event in events if event.state is not AttemptState.STARTED}
    if not terminal.issubset(started):
        raise ValueError("model call terminal event has no STARTED event")
    return len(started - terminal)


def _verify_event(event: ExperimentAttemptEvent) -> None:
    payload = event.model_dump(
        mode="python", exclude={"event_id", "event_digest"}
    )
    if canonical_digest(payload) != event.event_digest:
        raise ValueError("attempt event digest mismatch")
    expected = f"EV_{event.event_digest.removeprefix('sha256:')[:24].upper()}"
    if event.event_id != expected:
        raise ValueError("attempt event id mismatch")


def _duration_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _sanitize(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)[:2000]


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("cost must be a finite decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("cost must be a non-negative finite decimal")
    return parsed


def _token(usage: dict[str, Any], primary: str, fallback: str) -> int:
    value = usage.get(primary, usage.get(fallback, 0))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"usage.{primary} must be a non-negative integer")
    return value
