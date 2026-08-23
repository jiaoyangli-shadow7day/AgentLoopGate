from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from agentloopgate.runtime import (
    CapabilityBindingError,
    DshTau3TurnClient,
    DshTau3TurnConfig,
    Tau3PilotError,
    validate_runtime_capability_binding,
)
from agentloopgate.runtime.tau3_evidence import (
    _CURRENT_TASK_ATTEMPT,
    POSITION_FAIL_FAST_POLICY_CURRENT,
    TaskAttemptIdentity,
    _append_task_event,
    _install_global_attempt_budget,
    _install_user_model_ledger,
    _verify_position_fail_fast_artifact,
    bind_current_task_attempt_session,
    current_task_attempt_identity_fields,
    task_attempt_count,
)
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    ModelCallUsageEvent,
    make_model_call_event,
    verify_model_call_event,
)


def client() -> DshTau3TurnClient:
    return DshTau3TurnClient(
        DshTau3TurnConfig(
            project_root=Path("."),
            dsh_executable=Path("dsh"),
            patch_path=Path("pilot.yml"),
            profile="headless",
            session_root=Path("sessions"),
            provider="deepseek-official",
            model="deepseek-v4-flash",
            input_price_per_million=Decimal("1"),
            cache_read_price_per_million=Decimal("0.1"),
            output_price_per_million=Decimal("2"),
        )
    )


def test_user_ledger_uses_frozen_prices_when_provider_reports_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "user-usage.jsonl"
    user_simulator = ModuleType("tau2.user.user_simulator")
    user_simulator.generate = lambda **_kwargs: SimpleNamespace(
        usage={
            "prompt_tokens": 100,
            "cache_read_input_tokens": 50,
            "completion_tokens": 10,
        },
        cost=0,
    )
    tau2 = ModuleType("tau2")
    tau2_user = ModuleType("tau2.user")
    tau2_user.user_simulator = user_simulator
    monkeypatch.setitem(sys.modules, "tau2", tau2)
    monkeypatch.setitem(sys.modules, "tau2.user", tau2_user)
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", user_simulator)
    monkeypatch.setenv("AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("AGENTLOOPGATE_INPUT_PRICE_PER_MILLION", "0.14")
    monkeypatch.setenv("AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION", "0.014")
    monkeypatch.setenv("AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION", "0.28")

    _install_user_model_ledger()
    result = user_simulator.generate(model="fixture", messages=[])

    assert result.cost == 0
    events = [
        ModelCallUsageEvent.model_validate_json(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.state.value for event in events] == ["started", "completed"]
    assert events[-1].input_tokens == 100
    assert events[-1].cache_read_tokens == 50
    assert events[-1].output_tokens == 10
    assert events[-1].cost_status is CostStatus.EXACT
    assert events[-1].cost_usd == Decimal("0.0000175")


def test_user_ledger_rejects_missing_frozen_price_before_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_simulator = ModuleType("tau2.user.user_simulator")
    calls = 0

    def generate(**_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(usage={}, cost=0)

    user_simulator.generate = generate
    tau2 = ModuleType("tau2")
    tau2_user = ModuleType("tau2.user")
    tau2_user.user_simulator = user_simulator
    monkeypatch.setitem(sys.modules, "tau2", tau2)
    monkeypatch.setitem(sys.modules, "tau2.user", tau2_user)
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", user_simulator)
    monkeypatch.setenv(
        "AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER",
        str(tmp_path / "user-usage.jsonl"),
    )
    monkeypatch.setenv("AGENTLOOPGATE_INPUT_PRICE_PER_MILLION", "0.14")
    monkeypatch.setenv("AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION", "0.014")
    monkeypatch.delenv("AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION", raising=False)

    with pytest.raises(RuntimeError, match="frozen token price"):
        _install_user_model_ledger()

    assert calls == 0


def test_user_empty_final_gets_one_ledgered_repair_with_aggregate_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "user-usage.jsonl"
    calls = 0

    def generate(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=None,
                usage={"prompt_tokens": 100, "completion_tokens": 2},
                cost=0.1,
                raw_data={"call": 1},
            )
        return SimpleNamespace(
            content="The missing user reply.",
            tool_calls=None,
            usage={"prompt_tokens": 120, "completion_tokens": 8},
            cost=0.2,
            raw_data={"call": 2},
        )

    user_simulator = ModuleType("tau2.user.user_simulator")
    user_simulator.generate = generate
    message_module = ModuleType("tau2.data_model.message")
    message_module.UserMessage = lambda **kwargs: SimpleNamespace(**kwargs)
    tau2 = ModuleType("tau2")
    tau2_user = ModuleType("tau2.user")
    tau2_data_model = ModuleType("tau2.data_model")
    tau2_user.user_simulator = user_simulator
    monkeypatch.setitem(sys.modules, "tau2", tau2)
    monkeypatch.setitem(sys.modules, "tau2.user", tau2_user)
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", user_simulator)
    monkeypatch.setitem(sys.modules, "tau2.data_model", tau2_data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.message", message_module)
    monkeypatch.setenv("AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("AGENTLOOPGATE_INPUT_PRICE_PER_MILLION", "0.14")
    monkeypatch.setenv("AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION", "0.014")
    monkeypatch.setenv("AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION", "0.28")
    monkeypatch.setenv(
        "AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_POLICY",
        "bounded_same_call_context_final_only_v1",
    )
    monkeypatch.setenv("AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_LIMIT", "1")

    _install_user_model_ledger()
    result = user_simulator.generate(
        model="fixture",
        messages=[],
        call_name="user_simulator_response",
    )

    assert calls == 2
    assert result.content == "The missing user reply."
    assert result.usage == {"prompt_tokens": 220, "completion_tokens": 10}
    assert result.cost == pytest.approx(0.3)
    assert result.raw_data["call"] == 2
    assert result.raw_data["agentloopgate_user_empty_final_repair"][
        "repair_count"
    ] == 1
    events = [
        ModelCallUsageEvent.model_validate_json(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.state.value for event in events] == [
        "started",
        "completed",
        "started",
        "completed",
    ]
    assert [event.input_tokens for event in events if event.state is AttemptState.COMPLETED] == [
        100,
        120,
    ]


def test_user_empty_final_repair_is_bounded_when_second_response_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def generate(**_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            content="",
            tool_calls=None,
            usage={"prompt_tokens": 10, "completion_tokens": 1},
            cost=0.01,
            raw_data={},
        )

    user_simulator = ModuleType("tau2.user.user_simulator")
    user_simulator.generate = generate
    message_module = ModuleType("tau2.data_model.message")
    message_module.UserMessage = lambda **kwargs: SimpleNamespace(**kwargs)
    tau2 = ModuleType("tau2")
    tau2_user = ModuleType("tau2.user")
    tau2_data_model = ModuleType("tau2.data_model")
    tau2_user.user_simulator = user_simulator
    monkeypatch.setitem(sys.modules, "tau2", tau2)
    monkeypatch.setitem(sys.modules, "tau2.user", tau2_user)
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", user_simulator)
    monkeypatch.setitem(sys.modules, "tau2.data_model", tau2_data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.message", message_module)
    monkeypatch.setenv(
        "AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER",
        str(tmp_path / "user-usage.jsonl"),
    )
    monkeypatch.setenv("AGENTLOOPGATE_INPUT_PRICE_PER_MILLION", "0.14")
    monkeypatch.setenv("AGENTLOOPGATE_CACHE_READ_PRICE_PER_MILLION", "0.014")
    monkeypatch.setenv("AGENTLOOPGATE_OUTPUT_PRICE_PER_MILLION", "0.28")
    monkeypatch.setenv(
        "AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_POLICY",
        "bounded_same_call_context_final_only_v1",
    )
    monkeypatch.setenv("AGENTLOOPGATE_USER_EMPTY_FINAL_REPAIR_LIMIT", "1")

    _install_user_model_ledger()
    result = user_simulator.generate(
        model="fixture",
        messages=[],
        call_name="user_simulator_response",
    )

    assert calls == 2
    assert result.content == ""
    assert result.tool_calls is None
    assert result.usage == {"prompt_tokens": 20, "completion_tokens": 2}


def test_task_attempt_ledger_counts_started_attempts_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "task-attempts.jsonl"
    _append_task_event(
        ledger,
        state="started",
        task_id="task_001",
        trial=0,
        seed=300,
        attempt_index=1,
    )
    _append_task_event(
        ledger,
        state="failed",
        task_id="task_001",
        trial=0,
        seed=300,
        attempt_index=1,
        duration_ms=10,
        error_type="FixtureError",
    )

    assert task_attempt_count(ledger, "task_001", 0, 300) == 1
    assert task_attempt_count(ledger, "task_002", 0, 300) == 0

    ledger.write_text(
        ledger.read_text(encoding="utf-8").replace("task_001", "task_999", 1),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="digest mismatch"):
        task_attempt_count(ledger, "task_001", 0, 300)


def test_position_fail_fast_stops_before_next_position_and_retains_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "task-attempts.jsonl"
    simulation_module = ModuleType("tau2.data_model.simulation")

    class TerminationReason:
        INFRASTRUCTURE_ERROR = "infrastructure_error"
        AGENT_STOP = "agent_stop"

    class SimulationRun(SimpleNamespace):
        pass

    simulation_module.SimulationRun = SimulationRun
    simulation_module.TerminationReason = TerminationReason
    runner_batch = ModuleType("tau2.runner.batch")
    runner_batch.ThreadPoolExecutor = ThreadPoolExecutor
    runner_batch.as_completed = as_completed

    def run_with_retry(run_fn, task, trial, seed, **kwargs):
        max_retries = kwargs.get("max_retries", 0)
        for attempt in range(max_retries + 1):
            try:
                return run_fn()
            except RuntimeError as exc:
                if attempt < max_retries:
                    continue
                result = SimulationRun(
                    id=f"infra-{task.id}",
                    task_id=task.id,
                    termination_reason=TerminationReason.INFRASTRUCTURE_ERROR,
                    agent_cost=None,
                    user_cost=None,
                    messages=[],
                    info={"error": str(exc)},
                )
                save_fn = kwargs.get("save_fn")
                if save_fn:
                    save_fn(result)
                return result
        raise AssertionError("unreachable")

    runner_batch.run_with_retry = run_with_retry
    tau2 = ModuleType("tau2")
    tau2_data_model = ModuleType("tau2.data_model")
    tau2_runner = ModuleType("tau2.runner")
    tau2_runner.batch = runner_batch
    tau2_utils = ModuleType("tau2.utils")
    utils_module = ModuleType("tau2.utils.utils")
    utils_module.get_now = lambda: "2026-08-23T00:00:00Z"
    monkeypatch.setitem(sys.modules, "tau2", tau2)
    monkeypatch.setitem(sys.modules, "tau2.data_model", tau2_data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.simulation", simulation_module)
    monkeypatch.setitem(sys.modules, "tau2.runner", tau2_runner)
    monkeypatch.setitem(sys.modules, "tau2.runner.batch", runner_batch)
    monkeypatch.setitem(sys.modules, "tau2.utils", tau2_utils)
    monkeypatch.setitem(sys.modules, "tau2.utils.utils", utils_module)
    monkeypatch.setenv("AGENTLOOPGATE_TASK_ATTEMPT_LEDGER", str(ledger))
    monkeypatch.setenv("AGENTLOOPGATE_GLOBAL_TASK_ATTEMPT_LIMIT", "2")
    monkeypatch.setenv(
        "AGENTLOOPGATE_POSITION_FAIL_FAST_POLICY",
        POSITION_FAIL_FAST_POLICY_CURRENT,
    )

    _install_global_attempt_budget()
    invoked: list[str] = []

    def execute(task: SimpleNamespace) -> SimulationRun:
        invoked.append(task.id)
        if task.id == "task_002":
            raise RuntimeError("fixture DNS failure")
        return SimulationRun(
            id=f"sim-{task.id}",
            task_id=task.id,
            termination_reason=TerminationReason.AGENT_STOP,
            agent_cost=Decimal("0.01"),
            user_cost=Decimal("0.001"),
            messages=[],
        )

    tasks = [SimpleNamespace(id=f"task_{index:03d}") for index in range(1, 5)]
    executor = runner_batch.ThreadPoolExecutor(max_workers=1)
    futures = [
        executor.submit(
            lambda task=task: runner_batch.run_with_retry(
                lambda: execute(task),
                task,
                0,
                300,
                max_retries=1,
            )
        )
        for task in tasks
    ]
    results = [future.result() for future in runner_batch.as_completed(futures)]
    executor.shutdown(wait=True)

    assert invoked == ["task_001", "task_002", "task_002"]
    assert [result.task_id for result in results] == ["task_001", "task_002"]
    assert task_attempt_count(ledger, "task_001", 0, 300) == 1
    assert task_attempt_count(ledger, "task_002", 0, 300) == 2
    assert task_attempt_count(ledger, "task_003", 0, 300) == 0
    artifact = _verify_position_fail_fast_artifact(
        ledger.with_suffix(".position_fail_fast.json"),
        POSITION_FAIL_FAST_POLICY_CURRENT,
    )
    assert artifact["task_id"] == "task_002"
    assert artifact["attempts_consumed"] == 2
    assert artifact["next_position_started"] is False

    resumed_batch = ModuleType("tau2.runner.batch")
    resumed_batch.ThreadPoolExecutor = ThreadPoolExecutor
    resumed_batch.as_completed = as_completed
    resumed_batch.run_with_retry = run_with_retry
    tau2_runner.batch = resumed_batch
    monkeypatch.setitem(sys.modules, "tau2.runner.batch", resumed_batch)
    _install_global_attempt_budget()
    resumed_executor = resumed_batch.ThreadPoolExecutor(max_workers=1)
    resumed_futures = [
        resumed_executor.submit(
            lambda task=task: resumed_batch.run_with_retry(
                lambda: execute(task),
                task,
                0,
                300,
                max_retries=1,
            )
        )
        for task in tasks[2:]
    ]
    resumed_results = [
        future.result() for future in resumed_batch.as_completed(resumed_futures)
    ]
    resumed_executor.shutdown(wait=True)

    assert resumed_results == []
    assert invoked == ["task_001", "task_002", "task_002"]


def test_task_attempt_schema_1_1_binds_session_and_model_calls_directly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "task-attempts.jsonl"
    monkeypatch.setenv("AGENTLOOPGATE_TASK_ATTEMPT_LEDGER", str(ledger))
    monkeypatch.setenv("AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION", "1.1")
    monkeypatch.setenv("AGENTLOOPGATE_MODEL_USAGE_LEDGER_SCHEMA_VERSION", "1.2")
    identity = TaskAttemptIdentity(
        task_id="task_001",
        trial=0,
        seed=300,
        attempt_index=1,
    )
    _append_task_event(
        ledger,
        state="started",
        task_id=identity.task_id,
        trial=identity.trial,
        seed=identity.seed,
        attempt_index=identity.attempt_index,
    )
    token = _CURRENT_TASK_ATTEMPT.set(identity)
    try:
        session_id_hash = bind_current_task_attempt_session("session-1")
        call = make_model_call_event(
            call_id="MC_TEST",
            state=AttemptState.STARTED,
            session_id_hash=session_id_hash,
            model="provider/model",
            cost_status=CostStatus.PENDING,
            provider_retry_count=0,
            **current_task_attempt_identity_fields(),
        )
    finally:
        _CURRENT_TASK_ATTEMPT.reset(token)
    _append_task_event(
        ledger,
        state="completed",
        task_id=identity.task_id,
        trial=identity.trial,
        seed=identity.seed,
        attempt_index=identity.attempt_index,
        duration_ms=12,
        session_binding_status="bound",
        session_id_hash=session_id_hash,
        source_locator=f"dsh-session:{session_id_hash}",
    )

    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [event["state"] for event in events] == [
        "started",
        "session_bound",
        "completed",
    ]
    assert all(event["schema_version"] == "1.1" for event in events)
    assert events[1]["session_id_hash"] == session_id_hash
    assert events[1]["source_locator"] == f"dsh-session:{session_id_hash}"
    assert call.schema_version == "1.2"
    assert call.task_id == "task_001"
    assert call.trial == 0
    assert call.seed == 300
    assert call.task_attempt_index == 1
    verify_model_call_event(call)
    assert task_attempt_count(ledger, "task_001", 0, 300) == 1


def test_session_identity_is_deterministic_and_hides_task_data() -> None:
    first = client().session_id("EXP_1", "sensitive-task-id", 42)
    second = client().session_id("EXP_1", "sensitive-task-id", 42)

    assert first == second
    assert "sensitive" not in first


def test_prompt_carries_policy_tools_and_external_execution_boundary() -> None:
    prompt = client().build_prompt(
        input_message="Customer asks a question",
        domain_policy="verify identity",
        tool_schemas=[{"name": "lookup"}],
        harness_context='<asset path="harness/system_prompt.md">\ncheck evidence\n</asset>',
    )

    assert "verify identity" in prompt
    assert '"name": "lookup"' in prompt
    assert "check evidence" in prompt
    assert "outer τ³ evaluator executes tool_calls" in prompt
    assert "copy a name exactly from <available_tools>" in prompt
    assert "For a customer-facing reply, return plain text without a JSON wrapper" in prompt
    assert prompt.endswith(
        "<tau3_reply_reminder>\n"
        "For a customer-facing reply, emit plain text and do not start with { or [. "
        "For a tool call, emit one syntactically complete JSON object and close every "
        "quote, brace, and bracket. Output no commentary around a tool-call object.\n"
        "</tau3_reply_reminder>"
    )


def test_tool_routing_targets_must_exist_in_current_runtime_schema() -> None:
    routing = """
schema_version: "1.0"
capability_binding:
  source: runtime_tool_schema
  reject_unknown_route_targets: true
intent_routing:
  routes:
    - intent: lookup
      capability_ref: runtime://tool/lookup_account
"""

    validate_runtime_capability_binding(routing, {"lookup_account"})

    with pytest.raises(CapabilityBindingError, match="absent from this task"):
        validate_runtime_capability_binding(routing, {"update_account"})


def test_tool_routing_requires_explicit_runtime_binding() -> None:
    with pytest.raises(CapabilityBindingError, match="not bound"):
        validate_runtime_capability_binding(
            "schema_version: '1.0'\nroutes: []\n",
            {"lookup_account"},
        )


def test_reply_parser_accepts_text_and_known_tool_calls() -> None:
    text = client().parse_reply('{"content":"hello"}', allowed_tools={"lookup"})
    multiline = client().parse_reply(
        '{"content":"first line\nsecond line"}', allowed_tools={"lookup"}
    )
    plain = client().parse_reply("A plain customer-facing answer.", allowed_tools={"lookup"})
    tool = client().parse_reply(
        '```json\n{"tool_calls":[{"name":"lookup","arguments":{"id":1}}]}\n```',
        allowed_tools={"lookup"},
    )
    compact_tool = client().parse_reply(
        '{"tool_calls":[{"lookup":{"id":2}}]}', allowed_tools={"lookup"}
    )
    function_alias = client().parse_reply(
        '{"tool_calls":[{"function":"lookup","arguments":{"id":3}}]}',
        allowed_tools={"lookup"},
    )
    flattened_tool = client().parse_reply(
        '{"tool_calls":[{"name":"lookup","query":"customer cards"}]}',
        allowed_tools={"lookup"},
    )
    redundant_name_tool = client().parse_reply(
        '{"tool_calls":[{"lookup":"lookup","arguments":{"id":4}}]}',
        allowed_tools={"lookup"},
    )

    assert text.content == "hello"
    assert multiline.content == "first line\nsecond line"
    assert plain.content == "A plain customer-facing answer."
    assert tool.tool_calls and tool.tool_calls[0].arguments == {"id": 1}
    assert compact_tool.tool_calls and compact_tool.tool_calls[0].arguments == {"id": 2}
    assert function_alias.tool_calls
    assert function_alias.tool_calls[0].name == "lookup"
    assert function_alias.tool_calls[0].arguments == {"id": 3}
    assert flattened_tool.tool_calls
    assert flattened_tool.tool_calls[0].name == "lookup"
    assert flattened_tool.tool_calls[0].arguments == {"query": "customer cards"}
    assert redundant_name_tool.tool_calls
    assert redundant_name_tool.tool_calls[0].name == "lookup"
    assert redundant_name_tool.tool_calls[0].arguments == {"id": 4}

    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"lookup":"lookup","arguments":{"id":4}}]}',
            allowed_tools={"lookup"},
            reply_normalization_policy=(
                "bounded_allow_list_v3_plain_content_and_flattened_arguments"
            ),
        )


def test_reply_policy_v5_accepts_only_the_two_r6_explicit_shapes() -> None:
    missing_name = client().parse_reply(
        '{"tool_calls":[{"call_discoverable_agent_tool",'
        '"arguments":{"agent_tool_name":"open_account_4821",'
        '"arguments":"{\\"user_id\\":\\"u_1\\"}"}}]}',
        allowed_tools={"call_discoverable_agent_tool"},
    )
    wrapper_alias = client().parse_reply(
        '{"tool_calls":[{"call_discoverable_agent_tool":'
        '"get_accounts_3847","arguments":{"user_id":"u_1"}}]}',
        allowed_tools={"call_discoverable_agent_tool"},
    )

    assert missing_name.tool_calls
    assert missing_name.tool_calls[0].name == "call_discoverable_agent_tool"
    assert missing_name.tool_calls[0].arguments == {
        "agent_tool_name": "open_account_4821",
        "arguments": '{"user_id":"u_1"}',
    }
    assert wrapper_alias.tool_calls
    assert wrapper_alias.tool_calls[0].name == "call_discoverable_agent_tool"
    assert wrapper_alias.tool_calls[0].arguments == {
        "agent_tool_name": "get_accounts_3847",
        "arguments": '{"user_id":"u_1"}',
    }

    for raw in (
        '{"tool_calls":[{"lookup","arguments":{"id":1},"extra":true}]}',
        '{"tool_calls":[{"lookup","arguments":{"id":1}},'
        '{"name":"lookup","arguments":{"id":2}}]}',
        '{"tool_calls":[{"lookup","arguments":[]}]}',
    ):
        with pytest.raises(Tau3PilotError, match="syntax"):
            client().parse_reply(raw, allowed_tools={"lookup"})

    with pytest.raises(Tau3PilotError, match="unknown"):
        client().parse_reply(
            '{"tool_calls":[{"delete_all","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"call_discoverable_agent_tool":'
            '"unsafe-tool","arguments":{}}]}',
            allowed_tools={"call_discoverable_agent_tool"},
        )

    for raw in (
        '{"tool_calls":[{"lookup","arguments":{"id":1}}]}',
        '{"tool_calls":[{"call_discoverable_agent_tool":'
        '"get_accounts_3847","arguments":{"user_id":"u_1"}}]}',
    ):
        with pytest.raises(Tau3PilotError):
            client().parse_reply(
                raw,
                allowed_tools={"lookup", "call_discoverable_agent_tool"},
                reply_normalization_policy=(
                    "bounded_allow_list_v4_redundant_allow_listed_name"
                ),
            )


def test_reply_parser_rejects_unknown_tools_and_ambiguous_shapes() -> None:
    with pytest.raises(Tau3PilotError, match="no final"):
        client().parse_reply("   ", allowed_tools={"lookup"})
    with pytest.raises(Tau3PilotError, match="unknown"):
        client().parse_reply(
            '{"tool_calls":[{"name":"delete_all","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"content":"hello","tool_calls":[{"name":"lookup","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="syntax"):
        client().parse_reply('{"content":"truncated"', allowed_tools={"lookup"})
    with pytest.raises(Tau3PilotError, match="unknown"):
        client().parse_reply(
            '{"tool_calls":[{"delete_all":{"id":1}}]}', allowed_tools={"lookup"}
        )
    with pytest.raises(Tau3PilotError, match="unknown"):
        client().parse_reply(
            '{"tool_calls":[{"function":"delete_all","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"function":"lookup","arguments":{},"extra":true}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"function":"lookup","arguments":[]}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"name":"lookup","content":"reserved"}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"lookup":"different","arguments":{"id":1}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="unknown"):
        client().parse_reply(
            '{"tool_calls":[{"delete_all":"delete_all","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="schema"):
        client().parse_reply(
            '{"tool_calls":[{"lookup":"lookup","arguments":[],"extra":true}]}',
            allowed_tools={"lookup"},
        )


def test_turn_usage_ledger_records_cache_tokens_cost_and_failed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "dsh"
    patch = tmp_path / "pilot.yml"
    bridge = tmp_path / ".venv/bin/agentloopgate"
    for path in (executable, patch, bridge):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    usage_path = tmp_path / "runs/model-usage.jsonl"
    runtime = DshTau3TurnClient(
        DshTau3TurnConfig(
            project_root=tmp_path,
            dsh_executable=executable,
            patch_path=patch,
            profile="headless",
            session_root=tmp_path / "sessions",
            provider="deepseek-official",
            model="deepseek-v4-flash",
            input_price_per_million=Decimal("1"),
            cache_read_price_per_million=Decimal("0.1"),
            output_price_per_million=Decimal("2"),
            usage_ledger_path=usage_path,
        )
    )
    response = {
        "protocol_version": "1.1",
        "event_seq_start": 1,
        "event_seq_end": 2,
        "final_response": '{"content":"ok"}',
        "finish_reason": "completed",
        "input_tokens": 100,
        "cache_read_tokens": 50,
        "output_tokens": 10,
        "provider_retry_count": 0,
    }
    monkeypatch.setattr(
        "agentloopgate.runtime.tau3_pilot.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(response) + "\n",
            stderr="",
        ),
    )

    result = runtime.run_turn(
        session_id="fixture-session",
        prompt="fixture prompt",
        allowed_tools={"lookup"},
    )
    assert result.cost == Decimal("0.000125")

    response["final_response"] = '{"content":"truncated"'
    with pytest.raises(Tau3PilotError, match="syntax"):
        runtime.run_turn(
            session_id="fixture-session-2",
            prompt="fixture prompt",
            allowed_tools={"lookup"},
        )

    events = [
        ModelCallUsageEvent.model_validate_json(line)
        for line in usage_path.read_text(encoding="utf-8").splitlines()
    ]
    for event in events:
        verify_model_call_event(event)
    assert [event.state.value for event in events] == [
        "started",
        "completed",
        "started",
        "failed",
    ]
    assert events[1].cache_read_tokens == 50
    assert events[1].cost_usd == Decimal("0.000125")
    assert events[1].provider_retry_count == 0
    assert events[-1].cost_status.value == "exact"
    assert events[-1].cost_usd == Decimal("0.000125")


def test_empty_final_gets_one_same_session_repair_and_aggregates_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "dsh"
    patch = tmp_path / "pilot.yml"
    bridge = tmp_path / ".venv/bin/agentloopgate"
    for path in (executable, patch, bridge):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    usage_path = tmp_path / "runs/model-usage.jsonl"
    runtime = DshTau3TurnClient(
        DshTau3TurnConfig(
            project_root=tmp_path,
            dsh_executable=executable,
            patch_path=patch,
            profile="headless",
            session_root=tmp_path / "sessions",
            provider="deepseek-official",
            model="deepseek-v4-flash",
            input_price_per_million=Decimal("1"),
            cache_read_price_per_million=Decimal("0.1"),
            output_price_per_million=Decimal("2"),
            usage_ledger_path=usage_path,
        )
    )
    responses = [
        {
            "protocol_version": "1.1",
            "event_seq_start": 1,
            "event_seq_end": 6,
            "final_response": "",
            "finish_reason": "completed",
            "input_tokens": 100,
            "cache_read_tokens": 50,
            "output_tokens": 56,
            "provider_retry_count": 0,
        },
        {
            "protocol_version": "1.1",
            "event_seq_start": 7,
            "event_seq_end": 10,
            "final_response": '{"content":"repaired"}',
            "finish_reason": "completed",
            "input_tokens": 20,
            "cache_read_tokens": 180,
            "output_tokens": 10,
            "provider_retry_count": 0,
        },
    ]
    child_environments: list[dict[str, str]] = []

    def fake_run(*_args, **kwargs):
        child_environments.append(kwargs["env"])
        response = responses.pop(0)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(response) + "\n",
            stderr="",
        )

    monkeypatch.setattr("agentloopgate.runtime.tau3_pilot.subprocess.run", fake_run)

    result = runtime.run_turn(
        session_id="same-session",
        prompt="original task and policy",
        allowed_tools={"lookup"},
    )

    assert result.reply.content == "repaired"
    assert result.input_tokens == 120
    assert result.cache_read_tokens == 230
    assert result.output_tokens == 66
    assert result.cost == Decimal("0.000275")
    assert result.event_seq_start == 1
    assert result.event_seq_end == 10
    assert len(child_environments) == 2
    assert {
        environment["AGENTLOOPGATE_TAU_SESSION_ID"]
        for environment in child_environments
    } == {"same-session"}
    assert child_environments[0]["AGENTLOOPGATE_TAU_PROMPT"] == (
        "original task and policy"
    )
    repair_prompt = child_environments[1]["AGENTLOOPGATE_TAU_PROMPT"]
    assert "no final tau3 reply" in repair_prompt
    assert "original task and policy" not in repair_prompt

    events = [
        ModelCallUsageEvent.model_validate_json(line)
        for line in usage_path.read_text(encoding="utf-8").splitlines()
    ]
    for event in events:
        verify_model_call_event(event)
    assert [event.state.value for event in events] == [
        "started",
        "failed",
        "started",
        "completed",
    ]
    assert events[0].call_id == events[1].call_id
    assert events[2].call_id == events[3].call_id
    assert events[0].call_id != events[2].call_id
    assert events[1].error_type == "EmptyFinalResponseError"
    assert events[1].cost_status.value == "exact"


def test_empty_final_repair_is_bounded_and_second_reply_still_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "dsh"
    patch = tmp_path / "pilot.yml"
    bridge = tmp_path / ".venv/bin/agentloopgate"
    for path in (executable, patch, bridge):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    usage_path = tmp_path / "runs/model-usage.jsonl"
    runtime = DshTau3TurnClient(
        DshTau3TurnConfig(
            project_root=tmp_path,
            dsh_executable=executable,
            patch_path=patch,
            profile="headless",
            session_root=tmp_path / "sessions",
            provider="deepseek-official",
            model="deepseek-v4-flash",
            input_price_per_million=Decimal("1"),
            cache_read_price_per_million=Decimal("0.1"),
            output_price_per_million=Decimal("2"),
            usage_ledger_path=usage_path,
        )
    )
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        response = {
            "protocol_version": "1.1",
            "event_seq_start": calls,
            "event_seq_end": calls,
            "final_response": "" if calls == 1 else (
                '{"tool_calls":[{"name":"delete_all","arguments":{}}]}'
            ),
            "finish_reason": "completed",
            "input_tokens": 1,
            "cache_read_tokens": 0,
            "output_tokens": 56,
            "provider_retry_count": 0,
        }
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(response) + "\n",
            stderr="",
        )

    monkeypatch.setattr("agentloopgate.runtime.tau3_pilot.subprocess.run", fake_run)

    with pytest.raises(Tau3PilotError, match="unknown"):
        runtime.run_turn(
            session_id="bounded-session",
            prompt="original",
            allowed_tools={"lookup"},
        )

    assert calls == 2
    events = [
        ModelCallUsageEvent.model_validate_json(line)
        for line in usage_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.state.value for event in events] == [
        "started",
        "failed",
        "started",
        "failed",
    ]


def test_nonzero_runner_envelope_recovers_failed_call_usage_and_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "dsh"
    patch = tmp_path / "pilot.yml"
    bridge = tmp_path / ".venv/bin/agentloopgate"
    for path in (executable, patch, bridge):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    usage_path = tmp_path / "runs/model-usage.jsonl"
    runtime = DshTau3TurnClient(
        DshTau3TurnConfig(
            project_root=tmp_path,
            dsh_executable=executable,
            patch_path=patch,
            profile="headless",
            session_root=tmp_path / "sessions",
            provider="deepseek-official",
            model="deepseek-v4-flash",
            input_price_per_million=Decimal("1"),
            cache_read_price_per_million=Decimal("0.1"),
            output_price_per_million=Decimal("2"),
            usage_ledger_path=usage_path,
        )
    )
    response = {
        "protocol_version": "1.1",
        "event_seq_start": 1,
        "event_seq_end": 2,
        "final_response": "",
        "finish_reason": "max-tokens",
        "input_tokens": 100,
        "cache_read_tokens": 50,
        "output_tokens": 4096,
        "provider_retry_count": 0,
    }
    monkeypatch.setattr(
        "agentloopgate.runtime.tau3_pilot.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(response) + "\n",
            stderr="agentloopgate-tau3-runner: turn ended as max-tokens\n",
        ),
    )

    with pytest.raises(Tau3PilotError, match="max-tokens"):
        runtime.run_turn(
            session_id="fixture-session",
            prompt="fixture prompt",
            allowed_tools={"lookup"},
        )

    events = [
        ModelCallUsageEvent.model_validate_json(line)
        for line in usage_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.state.value for event in events] == ["started", "failed"]
    terminal = events[-1]
    assert terminal.input_tokens == 100
    assert terminal.cache_read_tokens == 50
    assert terminal.output_tokens == 4096
    assert terminal.provider_retry_count == 0
    assert terminal.cost_status.value == "exact"
    assert terminal.cost_usd == Decimal("0.008297")
