"""DeepSeek Harness turn protocol for the τ³ banking reference validation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest
from agentloopgate.runtime.tau3_evidence import current_task_attempt_identity_fields
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    append_model_call_event,
    make_model_call_event,
)
from agentloopgate.schemas.models import NonEmpty, StrictModel

_MILLION = Decimal(1_000_000)
_SECRET = re.compile(r"sk-[A-Za-z0-9]{20,}")
_SAFE_TOOL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MISSING_NAME_TOOL_CALL = re.compile(
    r'^\s*\{\s*"tool_calls"\s*:\s*\[\s*\{\s*'
    r'(?P<tool>"(?:\\.|[^"\\])+")\s*,\s*"arguments"\s*:'
)
DSH_TAU3_PROTOCOL_CURRENT = "dsh-tau3/1.1"
DSH_TAU3_SUPPORTED_PROTOCOLS = frozenset(
    {"dsh-tau3/1.0", DSH_TAU3_PROTOCOL_CURRENT}
)
DSH_TAU3_REPLY_POLICY_V3 = (
    "bounded_allow_list_v3_plain_content_and_flattened_arguments"
)
DSH_TAU3_REPLY_POLICY_V4 = (
    "bounded_allow_list_v4_redundant_allow_listed_name"
)
DSH_TAU3_REPLY_POLICY_CURRENT = (
    "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
)
DSH_TAU3_SUPPORTED_REPLY_POLICIES = frozenset(
    {
        DSH_TAU3_REPLY_POLICY_V3,
        DSH_TAU3_REPLY_POLICY_V4,
        DSH_TAU3_REPLY_POLICY_CURRENT,
    }
)
DSH_TAU3_FAILURE_USAGE_POLICY_CURRENT = "recover_verified_envelope"
DSH_TAU3_EMPTY_FINAL_POLICY_DISABLED = "disabled"
DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT = "bounded_same_session_final_only_v1"
DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT = 1
_EMPTY_FINAL_REPAIR_PROMPT = (
    "Your previous assistant message contained reasoning but no final tau3 reply. "
    "Do not repeat or summarize the reasoning. Emit exactly one missing final reply "
    "now under the existing tau3 contract: either plain customer-facing text or one "
    'complete {"tool_calls":[{"name":"tool_name","arguments":{}}]} JSON object. '
    "Do not add markdown or commentary."
)


class Tau3PilotError(RuntimeError):
    """The DSH-backed τ³ agent cannot produce an admissible turn."""


@dataclass(frozen=True)
class _Tau3TurnUsage:
    input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    provider_retry_count: int | None
    cost: Decimal
    event_seq_start: int
    event_seq_end: int


class EmptyFinalResponseError(Tau3PilotError):
    """The model completed a DSH turn without an executable or visible final reply."""

    def __init__(self, usage: _Tau3TurnUsage) -> None:
        super().__init__(
            "DSH agent completed reasoning but emitted no final τ³ reply"
        )
        self.usage = usage


class Tau3TurnEnvelope(StrictModel):
    protocol_version: Literal["1.0", "1.1"]
    event_seq_start: int = Field(ge=0)
    event_seq_end: int = Field(ge=0)
    final_response: str
    finish_reason: str | None
    input_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_retry_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def retry_count_matches_version(self) -> Tau3TurnEnvelope:
        if self.protocol_version == "1.1" and self.provider_retry_count is None:
            raise ValueError("turn protocol 1.1 requires provider_retry_count")
        if self.protocol_version == "1.0" and self.provider_retry_count is not None:
            raise ValueError("turn protocol 1.0 cannot contain provider_retry_count")
        return self


class Tau3ProposedToolCall(StrictModel):
    name: NonEmpty
    arguments: dict[str, Any]


class Tau3AgentReply(StrictModel):
    content: str | None = None
    tool_calls: list[Tau3ProposedToolCall] | None = None

    @model_validator(mode="after")
    def exactly_one_reply_shape(self) -> Tau3AgentReply:
        has_content = self.content is not None and bool(self.content.strip())
        has_calls = self.tool_calls is not None and bool(self.tool_calls)
        if has_content == has_calls:
            raise ValueError("reply must contain exactly one of content or tool_calls")
        return self


class Tau3TurnResult(StrictModel):
    reply: Tau3AgentReply
    input_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_retry_count: int | None = Field(default=None, ge=0)
    cost: Decimal = Field(ge=0)
    event_seq_start: int = Field(ge=0)
    event_seq_end: int = Field(ge=0)


@dataclass(frozen=True)
class DshTau3TurnConfig:
    project_root: Path
    dsh_executable: Path
    patch_path: Path
    profile: str
    session_root: Path
    provider: str
    model: str
    input_price_per_million: Decimal
    cache_read_price_per_million: Decimal
    output_price_per_million: Decimal
    timeout_seconds: int = 180
    usage_ledger_path: Path | None = None
    reply_normalization_policy: str = DSH_TAU3_REPLY_POLICY_CURRENT
    empty_final_repair_policy: str = DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT
    empty_final_repair_limit: int = DSH_TAU3_EMPTY_FINAL_REPAIR_LIMIT_CURRENT


class DshTau3TurnClient:
    """Invoke one resumable DSH turn and parse a strict τ³ message envelope."""

    def __init__(self, config: DshTau3TurnConfig) -> None:
        if config.reply_normalization_policy not in DSH_TAU3_SUPPORTED_REPLY_POLICIES:
            raise ValueError(
                "unsupported DSH reply normalization policy: "
                f"{config.reply_normalization_policy}"
            )
        expected_empty_policy = (
            DSH_TAU3_EMPTY_FINAL_POLICY_DISABLED
            if config.empty_final_repair_limit == 0
            else DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT
        )
        if (
            config.empty_final_repair_limit not in {0, 1}
            or config.empty_final_repair_policy != expected_empty_policy
        ):
            raise ValueError(
                "empty-final repair requires either disabled/0 or "
                f"{DSH_TAU3_EMPTY_FINAL_POLICY_CURRENT}/1"
            )
        self.config = config

    @staticmethod
    def session_id(namespace: str, task_id: str, seed: int) -> str:
        digest = canonical_digest(
            {"namespace": namespace, "task_id": task_id, "seed": seed}
        ).removeprefix("sha256:")
        return f"alg-tau3-{digest[:32]}"

    @staticmethod
    def build_prompt(
        *,
        input_message: str,
        domain_policy: str | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
        harness_context: str | None = None,
    ) -> str:
        protocol = (
            "Return exactly one reply and no markdown wrapper. For a customer-facing "
            "reply, return plain text without a JSON wrapper. For a tool action, return "
            'exactly {"tool_calls":[{"name":"tool_name","arguments":{}}]}. '
            "Never mix content and tool_calls. The outer τ³ evaluator executes tool_calls; "
            "do not claim that an action succeeded before receiving its tool result. "
            "For tool_calls, copy a name exactly from <available_tools>; never infer, "
            "translate, shorten, or invent a tool name. Follow discovery and unlock tools "
            "exactly as their schemas and policy require."
        )
        parts = [protocol]
        if harness_context is not None:
            parts.append(f"<agentloopgate_harness>\n{harness_context}\n</agentloopgate_harness>")
        if domain_policy is not None:
            parts.append(f"<policy>\n{domain_policy}\n</policy>")
        if tool_schemas is not None:
            parts.append(
                "<available_tools>\n"
                + json.dumps(tool_schemas, ensure_ascii=False, sort_keys=True)
                + "\n</available_tools>"
            )
        parts.append(f"<tau3_input>\n{input_message}\n</tau3_input>")
        parts.append(
            "<tau3_reply_reminder>\n"
            "For a customer-facing reply, emit plain text and do not start with { or [. "
            "For a tool call, emit one syntactically complete JSON object and close every "
            "quote, brace, and bracket. Output no commentary around a tool-call object.\n"
            "</tau3_reply_reminder>"
        )
        return "\n\n".join(parts)

    def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        allowed_tools: set[str],
    ) -> Tau3TurnResult:
        prior_usage: list[_Tau3TurnUsage] = []
        current_prompt = prompt
        for repair_index in range(self.config.empty_final_repair_limit + 1):
            try:
                result = self._run_one_turn(
                    session_id=session_id,
                    prompt=current_prompt,
                    allowed_tools=allowed_tools,
                )
            except EmptyFinalResponseError as exc:
                prior_usage.append(exc.usage)
                if repair_index >= self.config.empty_final_repair_limit:
                    raise
                current_prompt = _EMPTY_FINAL_REPAIR_PROMPT
                continue
            if not prior_usage:
                return result
            retry_counts = [
                usage.provider_retry_count
                for usage in prior_usage
            ] + [result.provider_retry_count]
            return Tau3TurnResult(
                reply=result.reply,
                input_tokens=sum(usage.input_tokens for usage in prior_usage)
                + result.input_tokens,
                cache_read_tokens=sum(
                    usage.cache_read_tokens for usage in prior_usage
                )
                + result.cache_read_tokens,
                output_tokens=sum(usage.output_tokens for usage in prior_usage)
                + result.output_tokens,
                provider_retry_count=(
                    None
                    if any(value is None for value in retry_counts)
                    else sum(value for value in retry_counts if value is not None)
                ),
                cost=sum((usage.cost for usage in prior_usage), Decimal(0))
                + result.cost,
                event_seq_start=prior_usage[0].event_seq_start,
                event_seq_end=result.event_seq_end,
            )
        raise AssertionError("empty-final repair loop did not terminate")

    def _run_one_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        allowed_tools: set[str],
    ) -> Tau3TurnResult:
        config = self.config
        call_id = f"MC_{uuid4().hex.upper()}"
        session_id_hash = canonical_digest({"session_id": session_id})
        started = time.monotonic()
        self._record_usage(
            call_id=call_id,
            state=AttemptState.STARTED,
            session_id_hash=session_id_hash,
            cost_status=CostStatus.PENDING,
        )
        root = config.project_root.resolve()
        executable = config.dsh_executable.resolve()
        patch = config.patch_path.resolve()
        bridge = root / ".venv/bin/agentloopgate"
        for path, label in (
            (executable, "dsh executable"),
            (patch, "τ³ DSH patch"),
            (bridge, "AgentLoopGate bridge executable"),
        ):
            if not path.is_file():
                raise Tau3PilotError(f"{label} is unavailable: {path}")
        config.session_root.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(
            {
                "AGENTLOOPGATE_PROJECT_ROOT": str(root),
                "AGENTLOOPGATE_BRIDGE_COMMAND": str(bridge),
                "AGENTLOOPGATE_TAU_PROMPT": prompt,
                "AGENTLOOPGATE_TAU_SESSION_ID": session_id,
                "AGENTLOOPGATE_DSH_SESSION_ROOT": str(config.session_root.resolve()),
                "AGENTLOOPGATE_DSH_PROVIDER": config.provider,
                "AGENTLOOPGATE_DSH_MODEL": config.model,
            }
        )
        try:
            completed = subprocess.run(
                [
                    str(executable),
                    "--profile",
                    config.profile,
                    "--patch",
                    str(patch),
                ],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._record_usage(
                call_id=call_id,
                state=AttemptState.FAILED,
                session_id_hash=session_id_hash,
                duration_ms=_elapsed_ms(started),
                cost_status=CostStatus.UNAVAILABLE,
                error_type=type(exc).__name__,
                error_message=_safe_excerpt(str(exc)),
            )
            raise Tau3PilotError(f"DeepSeek Harness turn failed to start: {exc}") from exc
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            if completed.returncode != 0:
                message = _safe_excerpt(
                    completed.stderr or "DeepSeek Harness returned no error text"
                )
                self._record_usage(
                    call_id=call_id,
                    state=AttemptState.FAILED,
                    session_id_hash=session_id_hash,
                    duration_ms=_elapsed_ms(started),
                    cost_status=CostStatus.UNAVAILABLE,
                    exit_code=completed.returncode,
                    error_type="DshProcessError",
                    error_message=message,
                )
                raise Tau3PilotError(f"DeepSeek Harness turn failed: {message}")
            self._record_usage(
                call_id=call_id,
                state=AttemptState.FAILED,
                session_id_hash=session_id_hash,
                duration_ms=_elapsed_ms(started),
                cost_status=CostStatus.UNAVAILABLE,
                exit_code=completed.returncode,
                error_type="TurnEnvelopeCountError",
                error_message="DeepSeek Harness runner did not emit exactly one JSON line",
            )
            raise Tau3PilotError("DeepSeek Harness runner must emit exactly one JSON line")
        try:
            envelope = Tau3TurnEnvelope.model_validate_json(lines[0])
        except ValueError as exc:
            if completed.returncode != 0:
                message = _safe_excerpt(
                    completed.stderr or "DeepSeek Harness emitted an invalid turn envelope"
                )
                self._record_usage(
                    call_id=call_id,
                    state=AttemptState.FAILED,
                    session_id_hash=session_id_hash,
                    duration_ms=_elapsed_ms(started),
                    cost_status=CostStatus.UNAVAILABLE,
                    exit_code=completed.returncode,
                    error_type="DshProcessError",
                    error_message=message,
                )
                raise Tau3PilotError(f"DeepSeek Harness turn failed: {message}") from exc
            self._record_usage(
                call_id=call_id,
                state=AttemptState.FAILED,
                session_id_hash=session_id_hash,
                duration_ms=_elapsed_ms(started),
                cost_status=CostStatus.UNAVAILABLE,
                exit_code=completed.returncode,
                error_type=type(exc).__name__,
                error_message="DeepSeek Harness emitted an invalid turn envelope",
            )
            raise Tau3PilotError("DeepSeek Harness emitted an invalid turn envelope") from exc
        cost = (
            Decimal(envelope.input_tokens) * config.input_price_per_million
            + Decimal(envelope.cache_read_tokens)
            * config.cache_read_price_per_million
            + Decimal(envelope.output_tokens) * config.output_price_per_million
        ) / _MILLION
        cost_status = (
            CostStatus.EXACT
            if envelope.provider_retry_count == 0
            else CostStatus.PARTIAL
        )
        if completed.returncode != 0:
            message = _safe_excerpt(
                completed.stderr
                or f"DeepSeek Harness turn ended as {envelope.finish_reason}"
            )
            self._record_usage(
                call_id=call_id,
                state=AttemptState.FAILED,
                session_id_hash=session_id_hash,
                duration_ms=_elapsed_ms(started),
                input_tokens=envelope.input_tokens,
                cache_read_tokens=envelope.cache_read_tokens,
                output_tokens=envelope.output_tokens,
                provider_retry_count=envelope.provider_retry_count,
                cost_usd=cost,
                cost_status=cost_status,
                exit_code=completed.returncode,
                error_type="DshProcessError",
                error_message=message,
            )
            reason = envelope.finish_reason or "unknown"
            raise Tau3PilotError(f"DeepSeek Harness turn did not complete: {reason}")
        try:
            if envelope.finish_reason != "completed":
                raise Tau3PilotError(
                    f"DeepSeek Harness turn did not complete: {envelope.finish_reason}"
                )
            if not envelope.final_response.strip():
                raise EmptyFinalResponseError(
                    _Tau3TurnUsage(
                        input_tokens=envelope.input_tokens,
                        cache_read_tokens=envelope.cache_read_tokens,
                        output_tokens=envelope.output_tokens,
                        provider_retry_count=envelope.provider_retry_count,
                        cost=cost,
                        event_seq_start=envelope.event_seq_start,
                        event_seq_end=envelope.event_seq_end,
                    )
                )
            reply = self.parse_reply(
                envelope.final_response,
                allowed_tools=allowed_tools,
                reply_normalization_policy=self.config.reply_normalization_policy,
            )
        except (Tau3PilotError, ValueError) as exc:
            self._record_usage(
                call_id=call_id,
                state=AttemptState.FAILED,
                session_id_hash=session_id_hash,
                duration_ms=_elapsed_ms(started),
                input_tokens=envelope.input_tokens,
                cache_read_tokens=envelope.cache_read_tokens,
                output_tokens=envelope.output_tokens,
                provider_retry_count=envelope.provider_retry_count,
                cost_usd=cost,
                cost_status=cost_status,
                exit_code=completed.returncode,
                error_type=type(exc).__name__,
                error_message=_safe_excerpt(str(exc)),
            )
            raise
        self._record_usage(
            call_id=call_id,
            state=AttemptState.COMPLETED,
            session_id_hash=session_id_hash,
            duration_ms=_elapsed_ms(started),
            input_tokens=envelope.input_tokens,
            cache_read_tokens=envelope.cache_read_tokens,
            output_tokens=envelope.output_tokens,
            provider_retry_count=envelope.provider_retry_count,
            cost_usd=cost,
            cost_status=cost_status,
            exit_code=completed.returncode,
        )
        return Tau3TurnResult(
            reply=reply,
            input_tokens=envelope.input_tokens,
            cache_read_tokens=envelope.cache_read_tokens,
            output_tokens=envelope.output_tokens,
            provider_retry_count=envelope.provider_retry_count,
            cost=cost,
            event_seq_start=envelope.event_seq_start,
            event_seq_end=envelope.event_seq_end,
        )

    def _record_usage(self, **payload: Any) -> None:
        path = self.config.usage_ledger_path
        if path is None:
            return
        append_model_call_event(
            path,
            make_model_call_event(
                model=f"{self.config.provider}/{self.config.model}",
                **current_task_attempt_identity_fields(),
                **payload,
            ),
        )

    @staticmethod
    def parse_reply(
        raw: str,
        *,
        allowed_tools: set[str],
        reply_normalization_policy: str = DSH_TAU3_REPLY_POLICY_CURRENT,
    ) -> Tau3AgentReply:
        text = raw.strip()
        if not text:
            raise Tau3PilotError("DSH agent response has no final τ³ reply")
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        try:
            # DeepSeek can preserve literal newlines inside an otherwise valid JSON
            # string. Accept only that JSON decoder relaxation; executable shapes
            # remain subject to the strict schema and tool allow-list below.
            decoded = json.loads(text, strict=False)
        except json.JSONDecodeError as exc:
            decoded = _decode_v5_missing_name_shape(
                text,
                allowed_tools=allowed_tools,
                reply_normalization_policy=reply_normalization_policy,
            )
            # Plain natural-language output is inert and can be represented as
            # ``content`` without inferring executable intent. JSON-like malformed
            # output still fails closed with an accurate syntax classification.
            if decoded is not None:
                pass
            elif text and not text.lstrip().startswith(("{", "[")):
                return Tau3AgentReply(content=text)
            else:
                raise Tau3PilotError(
                    "DSH agent response has invalid τ³ JSON syntax"
                ) from exc
        decoded = _normalize_explicit_tool_call_shape(
            decoded,
            allowed_tools=allowed_tools,
            reply_normalization_policy=reply_normalization_policy,
        )
        try:
            reply = Tau3AgentReply.model_validate(decoded)
        except ValueError as exc:
            raise Tau3PilotError(
                "DSH agent response is incompatible with the τ³ reply schema"
            ) from exc
        unknown = sorted(
            call.name for call in (reply.tool_calls or []) if call.name not in allowed_tools
        )
        if unknown:
            raise Tau3PilotError(f"DSH agent requested unknown τ³ tools: {unknown}")
        return reply


def _normalize_explicit_tool_call_shape(
    decoded: Any,
    *,
    allowed_tools: set[str],
    reply_normalization_policy: str,
) -> Any:
    if reply_normalization_policy not in DSH_TAU3_SUPPORTED_REPLY_POLICIES:
        raise Tau3PilotError(
            "unsupported DSH reply normalization policy: "
            f"{reply_normalization_policy}"
        )
    if not isinstance(decoded, dict) or set(decoded) != {"tool_calls"}:
        return decoded
    calls = decoded.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return decoded
    normalized: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            return decoded
        if set(call) == {"name", "arguments"}:
            normalized.append(call)
            continue
        if set(call) == {"function", "arguments"}:
            name = call["function"]
            arguments = call["arguments"]
            if not isinstance(name, str) or not name.strip():
                return decoded
            if name not in allowed_tools:
                raise Tau3PilotError(f"DSH agent requested unknown τ³ tools: [{name!r}]")
            if not isinstance(arguments, dict):
                return decoded
            normalized.append({"name": name, "arguments": arguments})
            continue
        if (
            reply_normalization_policy == DSH_TAU3_REPLY_POLICY_CURRENT
            and len(calls) == 1
            and set(call) == {"call_discoverable_agent_tool", "arguments"}
            and call["call_discoverable_agent_tool"]
            != "call_discoverable_agent_tool"
        ):
            wrapper = "call_discoverable_agent_tool"
            subtool = call[wrapper]
            arguments = call["arguments"]
            if wrapper not in allowed_tools:
                raise Tau3PilotError(
                    f"DSH agent requested unknown τ³ tools: [{wrapper!r}]"
                )
            if (
                not isinstance(subtool, str)
                or _SAFE_TOOL_IDENTIFIER.fullmatch(subtool) is None
                or not isinstance(arguments, dict)
            ):
                return decoded
            normalized.append(
                {
                    "name": wrapper,
                    "arguments": {
                        "agent_tool_name": subtool,
                        "arguments": json.dumps(
                            arguments,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                }
            )
            continue
        if (
            reply_normalization_policy
            in {DSH_TAU3_REPLY_POLICY_V4, DSH_TAU3_REPLY_POLICY_CURRENT}
            and "arguments" in call
            and len(call) == 2
        ):
            dynamic_names = set(call) - {"arguments"}
            if len(dynamic_names) != 1:
                return decoded
            name = next(iter(dynamic_names))
            redundant_name = call[name]
            arguments = call["arguments"]
            if name not in allowed_tools:
                raise Tau3PilotError(f"DSH agent requested unknown τ³ tools: [{name!r}]")
            if redundant_name != name or not isinstance(arguments, dict):
                return decoded
            normalized.append({"name": name, "arguments": arguments})
            continue
        if "name" in call and len(call) >= 2:
            name = call["name"]
            if not isinstance(name, str) or not name.strip():
                return decoded
            if name not in allowed_tools:
                raise Tau3PilotError(f"DSH agent requested unknown τ³ tools: [{name!r}]")
            reserved = {"arguments", "function", "content", "tool_calls"}
            if reserved.intersection(call):
                return decoded
            arguments = {key: value for key, value in call.items() if key != "name"}
            if not arguments:
                return decoded
            normalized.append({"name": name, "arguments": arguments})
            continue
        if len(call) != 1:
            return decoded
        name, arguments = next(iter(call.items()))
        if name not in allowed_tools:
            raise Tau3PilotError(f"DSH agent requested unknown τ³ tools: [{name!r}]")
        if not isinstance(arguments, dict):
            return decoded
        normalized.append({"name": name, "arguments": arguments})
    return {"tool_calls": normalized}


def _decode_v5_missing_name_shape(
    text: str,
    *,
    allowed_tools: set[str],
    reply_normalization_policy: str,
) -> Any | None:
    if reply_normalization_policy != DSH_TAU3_REPLY_POLICY_CURRENT:
        return None
    match = _MISSING_NAME_TOOL_CALL.match(text)
    if match is None:
        return None
    try:
        name = json.loads(match.group("tool"))
    except json.JSONDecodeError:
        return None
    if not isinstance(name, str) or name not in allowed_tools:
        raise Tau3PilotError(f"DSH agent requested unknown τ³ tools: [{name!r}]")
    repaired = text[: match.start("tool")] + '"name":' + text[match.start("tool") :]
    try:
        decoded = json.loads(repaired, strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict) or set(decoded) != {"tool_calls"}:
        return None
    calls = decoded.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        return None
    call = calls[0]
    if (
        not isinstance(call, dict)
        or set(call) != {"name", "arguments"}
        or call.get("name") != name
        or not isinstance(call.get("arguments"), dict)
    ):
        return None
    return decoded


def _safe_excerpt(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value.replace("\n", " "))[:400]


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
