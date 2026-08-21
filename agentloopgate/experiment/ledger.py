"""Append-only attempt and cost evidence for protocol-bound experiments."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
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

    schema_version: Literal["1.1"] = "1.1"
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
    cost_digest: Digest


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
) -> FormalCostAccounting:
    """Reconcile final τ³ costs with all separately journaled agent calls."""

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


def artifact_hashes(paths: dict[str, Path]) -> dict[str, str]:
    return {name: file_digest(path) for name, path in paths.items() if path.is_file()}


def observed_usage_cost(path: Path | None) -> tuple[CostStatus, Decimal | None]:
    """Return the known DSH cost for a failed attempt without claiming completeness."""

    calls = _model_call_terminals(path)
    unresolved = _unresolved_model_calls(path)
    exact = [call for call in calls if call.cost_status is CostStatus.EXACT]
    known = sum((call.cost_usd or Decimal(0) for call in exact), Decimal(0))
    if calls and len(exact) == len(calls) and not unresolved:
        # User-simulator and external billing evidence are absent on a failed batch,
        # so even exact DSH call costs are only a whole-attempt lower bound.
        return CostStatus.PARTIAL, known
    if exact:
        return CostStatus.PARTIAL, known
    return CostStatus.UNAVAILABLE, None


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
