"""τ³ HalfDuplexAgent whose model turns run inside DeepSeek Harness."""

from __future__ import annotations

import hashlib
import json
import os
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.data_model.tasks import Task
from tau2.environment.tool import Tool

from agentloopgate.contracts import canonical_digest
from agentloopgate.runtime import (
    DSH_TAU3_PROTOCOL_CURRENT,
    DshTau3TurnClient,
    DshTau3TurnConfig,
    bind_current_task_attempt_session,
    validate_runtime_capability_binding,
)

_HARNESS_PATHS = (
    "harness/system_prompt.md",
    "harness/context/policy_reasoning.md",
    "harness/skills/recovery.md",
    "harness/retrieval/policy.yaml",
    "harness/tools/routing.yaml",
    "harness/orchestration/state.yaml",
)
_MAX_HARNESS_BYTES = 128 * 1024


class AgentLoopGateState(BaseModel):
    turn_index: int = Field(default=0, ge=0)
    context_initialized: bool = False


class AgentLoopGateDshAgent(HalfDuplexAgent[AgentLoopGateState]):
    """Translate τ³ messages while preserving τ³ tool and evaluator authority."""

    def __init__(
        self,
        *,
        tools: list[Tool],
        domain_policy: str,
        task: Task,
        client: DshTau3TurnClient,
        namespace: str,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.task = task
        self.client = client
        self.namespace = namespace
        self._session_id: str | None = None

    def set_seed(self, seed: int) -> None:
        base = self.client.session_id(self.namespace, self.task.id, seed)
        self._session_id = _fresh_session_id(base)
        bind_current_task_attempt_session(self._session_id)

    def get_init_state(
        self,
        message_history: list[Message] | None = None,
    ) -> AgentLoopGateState:
        return AgentLoopGateState(
            turn_index=_assistant_turns(message_history or []),
            context_initialized=False,
        )

    def generate_next_message(
        self,
        message: ValidAgentInputMessage,
        state: AgentLoopGateState,
    ) -> tuple[AssistantMessage, AgentLoopGateState]:
        if self._session_id is None:
            raise RuntimeError("τ³ must call set_seed before the first AgentLoopGate turn")
        # τ³ seeds a default assistant greeting before the first generated turn,
        # so history length cannot determine whether DSH received its policy/tools.
        first_turn = not state.context_initialized
        prompt = self.client.build_prompt(
            input_message=json.dumps(
                _input_payload(message), ensure_ascii=False, sort_keys=True
            ),
            domain_policy=self.domain_policy if first_turn else None,
            tool_schemas=[tool.openai_schema for tool in self.tools] if first_turn else None,
            harness_context=(
                _load_harness_context({tool.name for tool in self.tools})
                if first_turn
                else None
            ),
        )
        started = time.monotonic()
        result = self.client.run_turn(
            session_id=self._session_id,
            prompt=prompt,
            allowed_tools={tool.name for tool in self.tools},
        )
        elapsed = time.monotonic() - started
        tool_calls = None
        if result.reply.tool_calls:
            tool_calls = [
                ToolCall(
                    id=_tool_call_id(state.turn_index, index, call.name, call.arguments),
                    name=call.name,
                    arguments=call.arguments,
                    requestor="assistant",
                )
                for index, call in enumerate(result.reply.tool_calls)
            ]
        assistant = AssistantMessage.text(
            result.reply.content or "",
            tool_calls=tool_calls,
            cost=float(result.cost),
            usage={
                "prompt_tokens": result.input_tokens,
                "cache_read_tokens": result.cache_read_tokens,
                "completion_tokens": result.output_tokens,
            },
            raw_data={
                "agentloopgate_protocol": DSH_TAU3_PROTOCOL_CURRENT,
                "dsh_session_id_hash": canonical_digest(
                    {"session_id": self._session_id}
                ),
                "event_seq_start": result.event_seq_start,
                "event_seq_end": result.event_seq_end,
                "provider_retry_count": result.provider_retry_count,
            },
            generation_time_seconds=elapsed,
        )
        return assistant, AgentLoopGateState(
            turn_index=state.turn_index + 1,
            context_initialized=True,
        )


def create_agentloopgate_dsh_agent(
    *,
    tools: list[Tool],
    domain_policy: str,
    task: Task,
    **_kwargs: Any,
) -> AgentLoopGateDshAgent:
    return AgentLoopGateDshAgent(
        tools=tools,
        domain_policy=domain_policy,
        task=task,
        client=_client_from_environment(),
        namespace=_required_environment("AGENTLOOPGATE_EXPERIMENT_NAMESPACE"),
    )


def _client_from_environment() -> DshTau3TurnClient:
    return DshTau3TurnClient(
        DshTau3TurnConfig(
            project_root=Path(_required_environment("AGENTLOOPGATE_PROJECT_ROOT")),
            dsh_executable=Path(_required_environment("AGENTLOOPGATE_DSH_EXECUTABLE")),
            patch_path=Path(_required_environment("AGENTLOOPGATE_DSH_PATCH")),
            profile=os.environ.get("AGENTLOOPGATE_DSH_PROFILE", "headless"),
            session_root=Path(_required_environment("AGENTLOOPGATE_DSH_SESSION_ROOT")),
            provider=_required_environment("AGENTLOOPGATE_DSH_PROVIDER"),
            model=_required_environment("AGENTLOOPGATE_DSH_MODEL"),
            input_price_per_million=_price("AGENTLOOPGATE_INPUT_PRICE_PER_MILLION"),
            cache_read_price_per_million=_price(
                "AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION"
            ),
            output_price_per_million=_price("AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION"),
            timeout_seconds=_positive_int(
                "AGENTLOOPGATE_DSH_TURN_TIMEOUT_SECONDS"
            ),
            reply_normalization_policy=_required_environment(
                "AGENTLOOPGATE_REPLY_NORMALIZATION_POLICY"
            ),
            empty_final_repair_policy=_required_environment(
                "AGENTLOOPGATE_EMPTY_FINAL_REPAIR_POLICY"
            ),
            empty_final_repair_limit=_non_negative_int(
                "AGENTLOOPGATE_EMPTY_FINAL_REPAIR_LIMIT"
            ),
            usage_ledger_path=(
                Path(os.environ["AGENTLOOPGATE_MODEL_USAGE_LEDGER"])
                if os.environ.get("AGENTLOOPGATE_MODEL_USAGE_LEDGER")
                else None
            ),
        )
    )


def _positive_int(name: str) -> int:
    raw = _required_environment(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _non_negative_int(name: str) -> int:
    raw = _required_environment(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a non-negative integer") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be a non-negative integer")
    return value


def _load_harness_context(runtime_capabilities: set[str]) -> str:
    root = Path(_required_environment("AGENTLOOPGATE_HARNESS_ROOT")).resolve()
    sections: list[str] = []
    total = 0
    for relative in _HARNESS_PATHS:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise RuntimeError(f"frozen harness asset is unavailable: {relative}")
        encoded = path.read_bytes()
        total += len(encoded)
        if total > _MAX_HARNESS_BYTES:
            raise RuntimeError("frozen harness context exceeds 128 KiB")
        try:
            content = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"frozen harness asset is not UTF-8: {relative}") from exc
        if relative == "harness/tools/routing.yaml":
            validate_runtime_capability_binding(content, runtime_capabilities)
        sections.append(f"<asset path=\"{relative}\">\n{content.rstrip()}\n</asset>")
    return "\n\n".join(sections)


def _input_payload(message: ValidAgentInputMessage) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        return {"kind": "user", "content": message.content or ""}
    if isinstance(message, ToolMessage):
        return {"kind": "tool_result", "result": _tool_result(message)}
    if isinstance(message, MultiToolMessage):
        return {
            "kind": "tool_results",
            "results": [_tool_result(item) for item in message.tool_messages],
        }
    raise TypeError(f"unsupported τ³ input message: {type(message).__name__}")


def _tool_result(message: ToolMessage) -> dict[str, Any]:
    return {
        "tool_call_id": message.id,
        "content": message.content,
        "error": message.error,
        "requestor": message.requestor,
    }


def _assistant_turns(messages: list[Message]) -> int:
    return sum(isinstance(message, AssistantMessage) for message in messages)


def _fresh_session_id(base: str) -> str:
    root = Path(_required_environment("AGENTLOOPGATE_DSH_SESSION_ROOT")).resolve()
    existing = {
        path.parent.name
        for path in root.rglob("session.jsonl")
        if path.is_file() and not path.is_symlink()
    }
    if base not in existing:
        return base
    attempt = 2
    while f"{base}-r{attempt}" in existing:
        attempt += 1
    return f"{base}-r{attempt}"


def _tool_call_id(turn: int, index: int, name: str, arguments: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"turn": turn, "index": index, "name": name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"alg-{turn + 1}-{index + 1}-{hashlib.sha256(encoded).hexdigest()[:12]}"


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"required pilot environment variable is missing: {name}")
    return value


def _price(name: str) -> Decimal:
    raw = _required_environment(name)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise RuntimeError(f"{name} must be a decimal") from exc
    if not value.is_finite() or value < 0:
        raise RuntimeError(f"{name} must be a finite non-negative decimal")
    return value
