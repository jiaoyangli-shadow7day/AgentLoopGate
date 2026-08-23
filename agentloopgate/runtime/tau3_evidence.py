"""Process-level evidence hooks for the pinned tau3 reference runner.

The hooks live outside the upstream checkout so the benchmark remains pinned and
unmodified.  They provide two pieces of evidence that tau3's retained final
results cannot provide on their own:

* every user-simulator model invocation, including calls from discarded runs;
* a global per-task-position attempt budget that survives process resume.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentloopgate.contracts import canonical_digest, canonical_json_bytes

from .usage import (
    AttemptState,
    CostStatus,
    append_model_call_event,
    make_model_call_event,
)

_TASK_LEDGER_ENV = "AGENTLOOPGATE_TASK_ATTEMPT_LEDGER"
_USER_LEDGER_ENV = "AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER"
_ATTEMPT_LIMIT_ENV = "AGENTLOOPGATE_GLOBAL_TASK_ATTEMPT_LIMIT"
_TASK_LEDGER_SCHEMA_ENV = "AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION"
_MODEL_USAGE_SCHEMA_ENV = "AGENTLOOPGATE_MODEL_USAGE_LEDGER_SCHEMA_VERSION"
_INPUT_PRICE_ENV = "AGENTLOOPGATE_INPUT_PRICE_PER_MILLION"
_CACHE_READ_PRICE_ENV = "AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION"
_OUTPUT_PRICE_ENV = "AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION"
_USER_EMPTY_FINAL_POLICY_ENV = "AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_POLICY"
_USER_EMPTY_FINAL_LIMIT_ENV = "AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_LIMIT"
USER_EMPTY_FINAL_REPAIR_POLICY_CURRENT = "bounded_same_call_context_final_only_v1"
USER_EMPTY_FINAL_REPAIR_LIMIT_CURRENT = 1
_USER_EMPTY_FINAL_REPAIR_PROMPT = (
    "Your preceding simulated-user response contained neither text nor a tool call. "
    "Using the unchanged conversation and user goal, emit only the missing final user "
    "response. Do not introduce new facts or alter the simulated user's intent."
)
_SECRET = re.compile(r"(?i)(?:sk|api[_-]?key|token)[=: ]+[A-Za-z0-9._-]{12,}")
_INVOCATION_ID = f"INV_{uuid4().hex.upper()}"
_INSTALLED = False


@dataclass(frozen=True)
class TaskAttemptIdentity:
    task_id: str
    trial: int
    seed: int
    attempt_index: int
    session_id_hash: str | None = None

    def model_call_fields(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trial": self.trial,
            "seed": self.seed,
            "task_attempt_index": self.attempt_index,
        }


_CURRENT_TASK_ATTEMPT: ContextVar[TaskAttemptIdentity | None] = ContextVar(
    "agentloopgate_current_task_attempt",
    default=None,
)


class GlobalTaskAttemptBudgetExhausted(RuntimeError):
    """No additional paid attempt is allowed for this task/trial/seed."""


def install_tau3_evidence_hooks() -> None:
    """Install idempotent hooks before handing control to the tau3 CLI."""

    global _INSTALLED
    if _INSTALLED:
        return
    if os.environ.get(_USER_LEDGER_ENV):
        _install_user_model_ledger()
    if os.environ.get(_TASK_LEDGER_ENV):
        _install_global_attempt_budget()
    _INSTALLED = True


def _install_user_model_ledger() -> None:
    from tau2.user import user_simulator

    original = user_simulator.generate
    ledger = Path(os.environ[_USER_LEDGER_ENV]).resolve()
    pricing = _frozen_token_pricing()
    repair_limit = _user_empty_final_repair_limit()

    def record_one_generate(
        model: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        tool_choice: str | None = None,
        call_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        call_id = f"UMC_{uuid4().hex.upper()}"
        session_id_hash = canonical_digest(
            {
                "invocation_id": _INVOCATION_ID,
                "model": model,
                "call_name": call_name,
                "message_count": len(messages),
                "roles": [getattr(message, "role", None) for message in messages],
            }
        )
        started = time.monotonic()
        append_model_call_event(
            ledger,
            make_model_call_event(
                call_id=call_id,
                state=AttemptState.STARTED,
                session_id_hash=session_id_hash,
                model=model,
                cost_status=CostStatus.PENDING,
                provider_retry_count=0,
                **_model_call_identity_fields(),
            ),
        )
        try:
            result = original(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                call_name=call_name,
                **kwargs,
            )
        except Exception as exc:
            append_model_call_event(
                ledger,
                make_model_call_event(
                    call_id=call_id,
                    state=AttemptState.FAILED,
                    session_id_hash=session_id_hash,
                    model=model,
                    duration_ms=_duration_ms(started),
                    provider_retry_count=0,
                    cost_status=CostStatus.UNAVAILABLE,
                    error_type=type(exc).__name__,
                    error_message=_sanitize(str(exc)) or type(exc).__name__,
                    **_model_call_identity_fields(),
                ),
            )
            raise
        usage = result.usage if isinstance(result.usage, dict) else {}
        input_tokens = _token(usage, "input_tokens", "prompt_tokens")
        cache_read_tokens = _token(
            usage,
            "cache_read_tokens",
            "cache_read_input_tokens",
            missing=0,
        )
        output_tokens = _token(usage, "output_tokens", "completion_tokens")
        cost = _frozen_usage_cost(
            pricing,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            output_tokens=output_tokens,
        )
        append_model_call_event(
            ledger,
            make_model_call_event(
                call_id=call_id,
                state=AttemptState.COMPLETED,
                session_id_hash=session_id_hash,
                model=model,
                duration_ms=_duration_ms(started),
                input_tokens=input_tokens,
                cache_read_tokens=cache_read_tokens,
                output_tokens=output_tokens,
                provider_retry_count=0,
                cost_usd=cost,
                cost_status=(CostStatus.EXACT if cost is not None else CostStatus.UNAVAILABLE),
                **_model_call_identity_fields(),
            ),
        )
        return result

    def recorded_generate(
        model: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        tool_choice: str | None = None,
        call_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        first = record_one_generate(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            call_name=call_name,
            **kwargs,
        )
        if (
            repair_limit == 0
            or call_name != "user_simulator_response"
            or not _is_empty_user_model_response(first)
        ):
            return first

        from tau2.data_model.message import UserMessage

        repair_messages = [
            *messages,
            UserMessage(role="user", content=_USER_EMPTY_FINAL_REPAIR_PROMPT),
        ]
        repaired = record_one_generate(
            model=model,
            messages=repair_messages,
            tools=tools,
            tool_choice=tool_choice,
            call_name="user_simulator_response_empty_final_repair",
            **kwargs,
        )
        return _aggregate_user_empty_final_repair(first, repaired)

    user_simulator.generate = recorded_generate


def _user_empty_final_repair_limit() -> int:
    policy = os.environ.get(_USER_EMPTY_FINAL_POLICY_ENV)
    raw_limit = os.environ.get(_USER_EMPTY_FINAL_LIMIT_ENV)
    if policy is None and raw_limit is None:
        return 0
    if policy != USER_EMPTY_FINAL_REPAIR_POLICY_CURRENT:
        raise RuntimeError(
            "unsupported User Simulator empty-final repair policy: "
            f"{policy!r}"
        )
    try:
        limit = int(raw_limit or "")
    except ValueError as exc:
        raise RuntimeError(
            "User Simulator empty-final repair limit must be exactly 1"
        ) from exc
    if limit != USER_EMPTY_FINAL_REPAIR_LIMIT_CURRENT:
        raise RuntimeError("User Simulator empty-final repair limit must be exactly 1")
    return limit


def _is_empty_user_model_response(result: Any) -> bool:
    content = getattr(result, "content", None)
    has_content = isinstance(content, str) and bool(content.strip())
    return not has_content and not bool(getattr(result, "tool_calls", None))


def _aggregate_user_empty_final_repair(first: Any, repaired: Any) -> Any:
    first_usage = first.usage if isinstance(getattr(first, "usage", None), dict) else {}
    repaired_usage = (
        repaired.usage if isinstance(getattr(repaired, "usage", None), dict) else {}
    )
    usage: dict[str, Any] = {}
    for key in set(first_usage) | set(repaired_usage):
        first_value = first_usage.get(key)
        repaired_value = repaired_usage.get(key)
        if (
            isinstance(first_value, int)
            and not isinstance(first_value, bool)
            and isinstance(repaired_value, int)
            and not isinstance(repaired_value, bool)
        ):
            usage[key] = first_value + repaired_value
        else:
            usage[key] = repaired_value if key in repaired_usage else first_value

    first_cost = _decimal(getattr(first, "cost", None))
    repaired_cost = _decimal(getattr(repaired, "cost", None))
    aggregate_cost = (
        float(first_cost + repaired_cost)
        if first_cost is not None and repaired_cost is not None
        else None
    )
    raw_data = getattr(repaired, "raw_data", None)
    raw_payload = dict(raw_data) if isinstance(raw_data, dict) else {}
    raw_payload["agentloopgate_user_empty_final_repair"] = {
        "policy": USER_EMPTY_FINAL_REPAIR_POLICY_CURRENT,
        "repair_count": 1,
        "usage_digest": canonical_digest(
            {"empty_call": first_usage, "repair_call": repaired_usage}
        ),
    }
    updates = {
        "usage": usage,
        "cost": aggregate_cost,
        "raw_data": raw_payload,
    }
    model_copy = getattr(repaired, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=updates)
    for key, value in updates.items():
        setattr(repaired, key, value)
    return repaired


def _install_global_attempt_budget() -> None:
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.runner import batch as runner_batch
    from tau2.utils.utils import get_now

    original = runner_batch.run_with_retry
    ledger = Path(os.environ[_TASK_LEDGER_ENV]).resolve()
    try:
        limit = int(os.environ[_ATTEMPT_LIMIT_ENV])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("global task attempt limit must be a positive integer") from exc
    if limit < 1:
        raise RuntimeError("global task attempt limit must be a positive integer")

    def bounded_run_with_retry(
        run_fn: Callable[[], Any],
        task: Any,
        trial: int,
        seed: int,
        **kwargs: Any,
    ) -> Any:
        consumed = task_attempt_count(ledger, task.id, trial, seed)
        remaining = max(0, limit - consumed)
        if remaining == 0:
            now = get_now()
            failed = SimulationRun(
                id=str(uuid4()),
                task_id=task.id,
                timestamp=now,
                start_time=now,
                end_time=now,
                duration=0.0,
                termination_reason=TerminationReason.INFRASTRUCTURE_ERROR,
                messages=[],
                trial=trial,
                seed=seed,
                info={
                    "error": "global task-position attempt budget exhausted",
                    "error_type": GlobalTaskAttemptBudgetExhausted.__name__,
                    "failed_after_attempts": consumed,
                    "global_task_attempt_limit": limit,
                },
            )
            save_fn = kwargs.get("save_fn")
            if save_fn:
                save_fn(failed)
            return failed

        requested_retries = int(kwargs.get("max_retries", 0))
        kwargs["max_retries"] = min(requested_retries, remaining - 1)

        def recorded_run() -> Any:
            prior = task_attempt_count(ledger, task.id, trial, seed)
            if prior >= limit:
                raise GlobalTaskAttemptBudgetExhausted(
                    "global task-position attempt budget exhausted"
                )
            attempt_index = prior + 1
            started = time.monotonic()
            identity = TaskAttemptIdentity(
                task_id=task.id,
                trial=trial,
                seed=seed,
                attempt_index=attempt_index,
            )
            context_token = _CURRENT_TASK_ATTEMPT.set(identity)
            _append_task_event(
                ledger,
                state="started",
                task_id=task.id,
                trial=trial,
                seed=seed,
                attempt_index=attempt_index,
            )
            try:
                try:
                    simulation = run_fn()
                except Exception as exc:
                    terminal_identity = _CURRENT_TASK_ATTEMPT.get() or identity
                    _append_task_event(
                        ledger,
                        state="failed",
                        task_id=task.id,
                        trial=trial,
                        seed=seed,
                        attempt_index=attempt_index,
                        duration_ms=_duration_ms(started),
                        error_type=type(exc).__name__,
                        error_message=_sanitize(str(exc)) or type(exc).__name__,
                        **_task_terminal_session_fields(terminal_identity),
                    )
                    raise
                terminal_identity = _CURRENT_TASK_ATTEMPT.get() or identity
                _append_task_event(
                    ledger,
                    state="completed",
                    task_id=task.id,
                    trial=trial,
                    seed=seed,
                    attempt_index=attempt_index,
                    duration_ms=_duration_ms(started),
                    simulation_id=simulation.id,
                    termination_reason=str(simulation.termination_reason),
                    agent_cost_usd=_decimal(simulation.agent_cost),
                    user_cost_usd=_decimal(simulation.user_cost),
                    message_count=len(simulation.messages or []),
                    **_task_terminal_session_fields(terminal_identity),
                )
                return simulation
            finally:
                _CURRENT_TASK_ATTEMPT.reset(context_token)

        return original(recorded_run, task, trial, seed, **kwargs)

    runner_batch.run_with_retry = bounded_run_with_retry


def bind_current_task_attempt_session(session_id: str) -> str:
    """Bind the actual DSH session before the first Agent model invocation."""

    session_id_hash = canonical_digest({"session_id": session_id})
    identity = _CURRENT_TASK_ATTEMPT.get()
    if identity is None:
        return session_id_hash
    if identity.session_id_hash is not None:
        if identity.session_id_hash != session_id_hash:
            raise RuntimeError("task attempt cannot bind more than one DSH session")
        return session_id_hash
    bound = replace(identity, session_id_hash=session_id_hash)
    _CURRENT_TASK_ATTEMPT.set(bound)
    if _task_ledger_schema_version() == "1.1":
        ledger_value = os.environ.get(_TASK_LEDGER_ENV)
        if not ledger_value:
            raise RuntimeError("task-attempt session binding requires its ledger")
        _append_task_event(
            Path(ledger_value).resolve(),
            state="session_bound",
            task_id=bound.task_id,
            trial=bound.trial,
            seed=bound.seed,
            attempt_index=bound.attempt_index,
            session_id_hash=session_id_hash,
            source_locator=f"dsh-session:{session_id_hash}",
        )
    return session_id_hash


def current_task_attempt_identity_fields() -> dict[str, Any]:
    """Return direct call-lineage fields only under the versioned 1.2 contract."""

    return _model_call_identity_fields()


def _model_call_identity_fields() -> dict[str, Any]:
    if os.environ.get(_MODEL_USAGE_SCHEMA_ENV) != "1.2":
        return {}
    identity = _CURRENT_TASK_ATTEMPT.get()
    if identity is None:
        raise RuntimeError("model usage 1.2 requires an active task attempt")
    return identity.model_call_fields()


def _task_terminal_session_fields(identity: TaskAttemptIdentity) -> dict[str, Any]:
    if _task_ledger_schema_version() != "1.1":
        return {}
    if identity.session_id_hash is None:
        return {"session_binding_status": "not_bound"}
    return {
        "session_binding_status": "bound",
        "session_id_hash": identity.session_id_hash,
        "source_locator": f"dsh-session:{identity.session_id_hash}",
    }


def _task_ledger_schema_version() -> str:
    version = os.environ.get(_TASK_LEDGER_SCHEMA_ENV, "1.0")
    if version not in {"1.0", "1.1"}:
        raise RuntimeError(f"unsupported task-attempt ledger schema: {version}")
    return version


def task_attempt_count(path: Path, task_id: str, trial: int, seed: int) -> int:
    """Count consumed attempts after verifying every existing ledger event."""

    if not path.is_file():
        return 0
    started: set[tuple[str, int]] = set()
    for event in verified_task_attempt_events(path):
        if (
            event.get("state") == "started"
            and event.get("task_id") == task_id
            and event.get("trial") == trial
            and event.get("seed") == seed
        ):
            started.add((str(event.get("invocation_id")), int(event["attempt_index"])))
    return len(started)


def verified_task_attempt_events(path: Path) -> list[dict[str, Any]]:
    """Load and verify task-attempt lifecycle and direct session lineage."""

    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid task attempt ledger line {line_number}") from exc
        declared = event.pop("event_digest", None)
        if declared != canonical_digest(event):
            raise RuntimeError(f"task attempt ledger digest mismatch at line {line_number}")
        event["event_digest"] = declared
        events.append(event)

    started: dict[tuple[Any, ...], dict[str, Any]] = {}
    bound: dict[tuple[Any, ...], dict[str, Any]] = {}
    terminal: set[tuple[Any, ...]] = set()
    for line_number, event in enumerate(events, 1):
        schema_version = event.get("schema_version")
        state = event.get("state")
        if schema_version not in {"1.0", "1.1"}:
            raise RuntimeError(
                f"unsupported task attempt ledger schema at line {line_number}"
            )
        supported_states = (
            {"started", "completed", "failed"}
            if schema_version == "1.0"
            else {"started", "session_bound", "completed", "failed"}
        )
        if state not in supported_states:
            raise RuntimeError(f"invalid task attempt state at line {line_number}")
        key = (
            event.get("invocation_id"),
            event.get("task_id"),
            event.get("trial"),
            event.get("seed"),
            event.get("attempt_index"),
        )
        if state == "started":
            if key in started:
                raise RuntimeError("task attempt ledger contains duplicate STARTED events")
            started[key] = event
            continue
        initial = started.get(key)
        if initial is None or initial.get("schema_version") != schema_version:
            raise RuntimeError("task attempt event has no matching STARTED identity")
        if state == "session_bound":
            if key in bound:
                raise RuntimeError("task attempt ledger contains duplicate session binding")
            session_id_hash = event.get("session_id_hash")
            if (
                not isinstance(session_id_hash, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", session_id_hash) is None
                or event.get("source_locator") != f"dsh-session:{session_id_hash}"
            ):
                raise RuntimeError("task attempt session binding is invalid")
            bound[key] = event
            continue
        if key in terminal:
            raise RuntimeError("task attempt ledger contains duplicate terminal events")
        if schema_version == "1.1":
            binding = bound.get(key)
            status = event.get("session_binding_status")
            if binding is None and status != "not_bound":
                raise RuntimeError("unbound task attempt terminal must say not_bound")
            if binding is not None and (
                status != "bound"
                or event.get("session_id_hash") != binding.get("session_id_hash")
                or event.get("source_locator") != binding.get("source_locator")
            ):
                raise RuntimeError("task attempt terminal changed its session binding")
        terminal.add(key)
    return events


def _append_task_event(
    path: Path,
    *,
    state: str,
    task_id: str,
    trial: int,
    seed: int,
    attempt_index: int,
    **details: Any,
) -> None:
    payload = {
        "schema_version": _task_ledger_schema_version(),
        "event_id": f"TAE_{uuid4().hex.upper()}",
        "invocation_id": _INVOCATION_ID,
        "state": state,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "task_id": task_id,
        "trial": trial,
        "seed": seed,
        "attempt_index": attempt_index,
        **details,
    }
    payload["event_digest"] = canonical_digest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(payload) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _token(
    usage: dict[str, Any],
    *names: str,
    missing: int | None = None,
) -> int | None:
    for name in names:
        if name not in usage:
            continue
        value = usage[name]
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None
    return missing


def _frozen_token_pricing() -> tuple[Decimal, Decimal, Decimal]:
    """Load the protocol-bound prices before any paid User model call."""

    prices: list[Decimal] = []
    for name in (_INPUT_PRICE_ENV, _CACHE_READ_PRICE_ENV, _OUTPUT_PRICE_ENV):
        value = _decimal(os.environ.get(name))
        if value is None:
            raise RuntimeError(
                f"frozen token price {name} must be a non-negative finite decimal"
            )
        prices.append(value)
    return prices[0], prices[1], prices[2]


def _frozen_usage_cost(
    pricing: tuple[Decimal, Decimal, Decimal],
    *,
    input_tokens: int | None,
    cache_read_tokens: int | None,
    output_tokens: int | None,
) -> Decimal | None:
    """Calculate exact cost from verified usage and frozen protocol prices."""

    if input_tokens is None or cache_read_tokens is None or output_tokens is None:
        return None
    input_price, cache_read_price, output_price = pricing
    cost = (
        Decimal(input_tokens) * input_price
        + Decimal(cache_read_tokens) * cache_read_price
        + Decimal(output_tokens) * output_price
    ) / Decimal(1_000_000)
    positive_priced_usage = (
        (input_tokens > 0 and input_price > 0)
        or (cache_read_tokens > 0 and cache_read_price > 0)
        or (output_tokens > 0 and output_price > 0)
    )
    if positive_priced_usage and cost <= 0:
        raise RuntimeError("positive priced token usage cannot have exact zero cost")
    return cost


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _duration_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _sanitize(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)[:2000]
