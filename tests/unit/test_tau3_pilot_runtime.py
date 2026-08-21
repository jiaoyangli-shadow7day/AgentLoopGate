from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentloopgate.runtime import DshTau3TurnClient, DshTau3TurnConfig, Tau3PilotError
from agentloopgate.runtime.usage import ModelCallUsageEvent, verify_model_call_event


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

    assert text.content == "hello"
    assert multiline.content == "first line\nsecond line"
    assert plain.content == "A plain customer-facing answer."
    assert tool.tool_calls and tool.tool_calls[0].arguments == {"id": 1}
    assert compact_tool.tool_calls and compact_tool.tool_calls[0].arguments == {"id": 2}


def test_reply_parser_rejects_unknown_tools_and_ambiguous_shapes() -> None:
    with pytest.raises(Tau3PilotError, match="unknown"):
        client().parse_reply(
            '{"tool_calls":[{"name":"delete_all","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="valid"):
        client().parse_reply(
            '{"content":"hello","tool_calls":[{"name":"lookup","arguments":{}}]}',
            allowed_tools={"lookup"},
        )
    with pytest.raises(Tau3PilotError, match="valid"):
        client().parse_reply('{"content":"truncated"', allowed_tools={"lookup"})
    with pytest.raises(Tau3PilotError, match="valid"):
        client().parse_reply(
            '{"tool_calls":[{"delete_all":{"id":1}}]}', allowed_tools={"lookup"}
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
    with pytest.raises(Tau3PilotError, match="valid"):
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
