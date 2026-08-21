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
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    append_model_call_event,
    make_model_call_event,
)
from agentloopgate.schemas.models import NonEmpty, StrictModel

_MILLION = Decimal(1_000_000)
_SECRET = re.compile(r"sk-[A-Za-z0-9]{20,}")


class Tau3PilotError(RuntimeError):
    """The DSH-backed τ³ agent cannot produce an admissible turn."""


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


class DshTau3TurnClient:
    """Invoke one resumable DSH turn and parse a strict τ³ message envelope."""

    def __init__(self, config: DshTau3TurnConfig) -> None:
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
            "Return exactly one JSON object and no markdown. Either return "
            '{"content":"message to the customer"} or '
            '{"tool_calls":[{"name":"tool_name","arguments":{}}]}. '
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
        return "\n\n".join(parts)

    def run_turn(
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
        if completed.returncode != 0:
            message = _safe_excerpt(completed.stderr or "DeepSeek Harness returned no error text")
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
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
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
        try:
            if envelope.finish_reason != "completed":
                raise Tau3PilotError(
                    f"DeepSeek Harness turn did not complete: {envelope.finish_reason}"
                )
            reply = self.parse_reply(envelope.final_response, allowed_tools=allowed_tools)
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
                **payload,
            ),
        )

    @staticmethod
    def parse_reply(raw: str, *, allowed_tools: set[str]) -> Tau3AgentReply:
        text = raw.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        try:
            reply = Tau3AgentReply.model_validate_json(text)
        except ValueError:
            # DeepSeek can preserve literal newlines inside an otherwise valid JSON
            # string.  Accept that narrowly defined JSON decoder relaxation, then
            # apply the same strict Pydantic envelope and tool allow-list checks.
            try:
                decoded = json.loads(text, strict=False)
                decoded = _normalize_explicit_tool_call_shape(
                    decoded, allowed_tools=allowed_tools
                )
                reply = Tau3AgentReply.model_validate(decoded)
            except (json.JSONDecodeError, ValueError) as relaxed_exc:
                # Plain natural-language output is inert and can be represented as
                # ``content`` without inferring any executable intent.  JSON-like
                # malformed output still fails closed.
                if text and not text.lstrip().startswith(("{", "[")):
                    reply = Tau3AgentReply(content=text)
                else:
                    raise Tau3PilotError(
                        "DSH agent response is not a valid τ³ JSON reply"
                    ) from relaxed_exc
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
) -> Any:
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
        if len(call) != 1:
            return decoded
        name, arguments = next(iter(call.items()))
        if name not in allowed_tools or not isinstance(arguments, dict):
            return decoded
        normalized.append({"name": name, "arguments": arguments})
    return {"tool_calls": normalized}


def _safe_excerpt(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value.replace("\n", " "))[:400]


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
