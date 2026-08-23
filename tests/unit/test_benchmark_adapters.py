from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentloopgate.adapters import (
    BenchmarkAdapter,
    BenchmarkRunContext,
    BenchmarkRunRequest,
    DshTau3Adapter,
    DshTau3EvidenceLinker,
    DshTau3PilotConfig,
    JsonlOutcomeAdapter,
    OutcomeImportError,
    PilotPricingConfig,
    Tau3Adapter,
    Tau3TaskCatalog,
)
from agentloopgate.bridge import BridgeRequest, BridgeService
from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.runtime import DshTau3TurnClient
from agentloopgate.schemas import Pool, RunSource, RuntimeHost, RunValidity

PINNED_TAU3_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def context(
    *,
    pool: Pool = Pool.PILOT,
    snapshot_id: str = "S_A0",
    model_id: str = "deepseek/deepseek-chat",
) -> BenchmarkRunContext:
    return BenchmarkRunContext(
        pool=pool,
        snapshot_id=snapshot_id,
        candidate_id=None,
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        benchmark_commit=PINNED_TAU3_COMMIT,
        model_id=model_id,
        expected_task_ids=["task_001"],
        initial_state_digests={"task_001": DIGEST_C},
        expected_trials=1,
    )


def tau3_result(*, infrastructure_error: bool = False) -> dict:
    reward_info = None
    if not infrastructure_error:
        reward_info = {
            "reward": 1.0,
            "db_check": {"db_match": True, "db_reward": 1.0},
            "env_assertions": None,
            "action_checks": [
                {
                    "action": {
                        "action_id": "reference_1",
                        "requestor": "assistant",
                        "name": "apply_for_credit_card",
                        "arguments": {"card_type": "example"},
                    },
                    "action_match": False,
                    "action_reward": 0.0,
                    "tool_type": "write",
                }
            ],
            "nl_assertions": None,
            "communicate_checks": None,
            "reward_basis": ["DB"],
            "reward_breakdown": {"DB": 1.0},
            "info": None,
        }
    return {
        "timestamp": "2026-08-20T00:00:00Z",
        "info": {
            "git_commit": PINNED_TAU3_COMMIT,
            "num_trials": 1,
            "max_steps": 100,
            "max_errors": 10,
            "user_info": {"implementation": "user_simulator", "llm": "deepseek/deepseek-chat"},
            "agent_info": {"implementation": "tool_calling", "llm": "deepseek/deepseek-chat"},
            "environment_info": {"domain_name": "banking_knowledge", "policy": "redacted"},
            "seed": 42,
            "retrieval_config": "bm25",
        },
        "tasks": [{"id": "task_001", "required_documents": ["private-gold-document"]}],
        "simulations": [
            {
                "id": "tau3-sim-001",
                "task_id": "task_001",
                "timestamp": "2026-08-20T00:00:00Z",
                "start_time": "2026-08-20T00:00:00Z",
                "end_time": "2026-08-20T00:00:01.250Z",
                "duration": 1.25,
                "termination_reason": (
                    "infrastructure_error" if infrastructure_error else "agent_stop"
                ),
                "agent_cost": 0.0125,
                "user_cost": 0.002,
                "reward_info": reward_info,
                "messages": [
                    {
                        "role": "assistant",
                        "content": "done",
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                        "tool_calls": [
                            {"name": "apply_for_credit_card", "arguments": {"x": 1}}
                        ],
                    },
                    {
                        "role": "user",
                        "content": "thanks",
                        "usage": {"prompt_tokens": 9, "completion_tokens": 3},
                    },
                ],
                "trial": 0,
                "seed": 42,
                "info": None,
            }
        ],
    }


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_outcome_jsonl(
    project_root: Path,
    *,
    pool: str = "pilot",
    snapshot_id: str = "S_A0",
    evaluator_id: str = "bank-evaluator",
    evaluated_system_id: str = "agent-under-test",
    with_evidence: bool = True,
) -> Path:
    evidence_path = project_root / "evidence" / "R_COMMUNITY_001.json"
    write_json(evidence_path, {"outcome": "verified", "terminal_state": "ok"})
    payload = {
        "schema_version": "1.0",
        "run_id": "R_COMMUNITY_001",
        "attempt_id": "A_COMMUNITY_001",
        "task_id": "task_001",
        "pool": pool,
        "snapshot_id": snapshot_id,
        "candidate_id": None,
        "trial_index": 1,
        "model_id": "community/model",
        "runtime_version": "community-harness@1.0",
        "initial_state_digest": DIGEST_C,
        "terminal_state_digest": canonical_digest({"terminal_state": "ok"}),
        "success": True,
        "critical_violations": [],
        "input_tokens": 11,
        "output_tokens": 7,
        "latency_ms": 250,
        "cost": "0.001",
        "evaluator": {
            "evaluator_id": evaluator_id,
            "evaluated_system_id": evaluated_system_id,
            "authority": "independent",
            "version": "1.0",
            "config_digest": DIGEST_A,
        },
        "created_at": "2026-08-20T00:00:01Z",
    }
    if with_evidence:
        payload["evidence"] = {
            "artifact_uri": "artifact:evidence/R_COMMUNITY_001.json",
            "artifact_digest": file_digest(evidence_path),
        }
    output = project_root / "community-results.jsonl"
    output.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return output


def pilot_config(project_root: Path) -> DshTau3PilotConfig:
    patch = project_root / "pilot.patch.yml"
    patch.write_text("- id: headless-runner\n  disabled: true\n", encoding="utf-8")
    redaction = project_root / "configs/trace_redaction.yaml"
    redaction.parent.mkdir(parents=True, exist_ok=True)
    redaction.write_text("schema_version: '1.0'\n", encoding="utf-8")
    harness = project_root / "harness/system_prompt.md"
    harness.parent.mkdir(parents=True, exist_ok=True)
    harness.write_text("Use verified evidence.\n", encoding="utf-8")
    return DshTau3PilotConfig(
        dsh_executable=project_root / "dsh",
        dsh_home=project_root / "dsh-home",
        patch_path=patch,
        session_root=project_root / "native-sessions",
        profile="headless",
        provider="deepseek-official",
        model="deepseek-v4-flash",
        experiment_namespace="EXP_PILOT",
        pricing=PilotPricingConfig(
            schema_version="1.0",
            provider="deepseek-official",
            model="deepseek-v4-flash",
            currency="USD",
            unit="per_million_tokens",
            input_cache_miss=Decimal("0.14"),
            input_cache_hit=Decimal("0.0028"),
            output=Decimal("0.28"),
            source_url="https://api-docs.deepseek.com/quick_start/pricing/",
            checked_at="2026-08-20T00:00:00Z",
        ),
    )


def test_tau3_adapter_command_is_pinned_and_does_not_contain_secrets(tmp_path: Path) -> None:
    adapter = Tau3Adapter(tmp_path, checkout=tmp_path / "tau3")
    assert isinstance(adapter, BenchmarkAdapter)
    request = BenchmarkRunRequest(
        task_ids=["task_001", "task_002"],
        trials=3,
        agent_model="deepseek/deepseek-chat",
        user_model="deepseek/deepseek-chat",
        run_name="pilot-a0",
    )

    command = adapter.build_command(request)

    assert command[:6] == [
        "uv",
        "run",
        "--with",
        "socksio==1.0.0",
        "tau2",
        "run",
    ]
    assert command[command.index("--domain") + 1] == "banking_knowledge"
    assert command[command.index("--retrieval-config") + 1] == "bm25"
    assert command[command.index("--num-trials") + 1] == "3"
    assert command[command.index("--max-retries") + 1] == "1"
    assert command[command.index("--retry-delay") + 1] == "1"
    assert "task_001" in command and "task_002" in command
    assert all("API_KEY" not in part and not part.startswith("sk-") for part in command)

    resumed = adapter.build_command(request.model_copy(update={"resume": True}))
    assert "--auto-resume" in resumed


def test_tau3_adapter_normalizes_pinned_naive_timestamp_as_utc() -> None:
    parsed = Tau3Adapter._datetime("2026-08-20T12:34:56.123456")

    assert parsed.isoformat() == "2026-08-20T12:34:56.123456+00:00"


def test_dsh_tau3_command_selects_custom_agent_and_rejects_parallelism(
    tmp_path: Path,
) -> None:
    adapter = DshTau3Adapter(
        tmp_path,
        checkout=tmp_path / "tau3",
        pilot=pilot_config(tmp_path),
    )
    request = BenchmarkRunRequest(
        task_ids=["task_001"],
        trials=1,
        agent_model="deepseek-official/deepseek-v4-flash",
        user_model="deepseek/deepseek-chat",
        run_name="pilot-a0",
    )

    command = adapter.build_command(request)

    assert command[:6] == [
        "uv",
        "run",
        "--with",
        "socksio==1.0.0",
        "python",
        str(tmp_path / "examples/tau3-banking/run.py"),
    ]
    assert command[command.index("--agent") + 1] == "agentloopgate_dsh"
    assert command[command.index("--max-concurrency") + 1] == "1"
    assert command[command.index("--max-retries") + 1] == "1"
    assert command[command.index("--retry-delay") + 1] == "1"
    with pytest.raises(RuntimeError, match="max_concurrency=1"):
        adapter.build_command(request.model_copy(update={"max_concurrency": 2}))


def test_dsh_tau3_child_env_bypasses_proxy_and_binds_versioned_attempt_ledgers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "tau3"
    config = replace(
        pilot_config(tmp_path),
        network_route_policy="direct_no_proxy",
        global_task_attempt_limit=2,
    )
    adapter = DshTau3Adapter(tmp_path, checkout=checkout, pilot=config)
    request = BenchmarkRunRequest(
        task_ids=["task_001"],
        trials=1,
        agent_model="deepseek-official/deepseek-v4-flash",
        user_model="deepseek/deepseek-v4-flash",
        run_name="r4-fixture",
        model_usage_ledger=tmp_path / "runs/agent.jsonl",
        user_model_usage_ledger=tmp_path / "runs/user.jsonl",
        task_attempt_ledger=tmp_path / "runs/task.jsonl",
    )
    result = checkout / "data/simulations/r4-fixture/results.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:1")
    monkeypatch.setattr(
        adapter,
        "doctor",
        lambda: SimpleNamespace(ready=True, remediation="No action required."),
    )
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agentloopgate.adapters.dsh_tau3.subprocess.run", fake_run)

    assert adapter.run(request) == result
    assert "HTTP_PROXY" not in captured
    assert "all_proxy" not in captured
    assert captured["AGENTLOOPGATE_GLOBAL_TASK_ATTEMPT_LIMIT"] == "2"
    assert captured["AGENTLOOPGATE_REPLY_NORMALIZATION_POLICY"] == (
        "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
    )
    assert captured["AGENTLOOPGATE_DSH_TURN_TIMEOUT_SECONDS"] == "360"
    assert captured["AGENTLOOPGATE_DSH_STREAM_IDLE_TIMEOUT_MS"] == "300000"
    assert captured["AGENTLOOPGATE_EMPTY_FINAL_REPAIR_POLICY"] == (
        "bounded_same_session_final_only_v1"
    )
    assert captured["AGENTLOOPGATE_EMPTY_FINAL_REPAIR_LIMIT"] == "1"
    assert captured["AGENTLOOPGATE_MODEL_USAGE_LEDGER"].endswith("runs/agent.jsonl")
    assert captured["AGENTLOOPGATE_USER_MODEL_USAGE_LEDGER"].endswith(
        "runs/user.jsonl"
    )
    assert captured["AGENTLOOPGATE_TASK_ATTEMPT_LEDGER"].endswith("runs/task.jsonl")
    assert captured["AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION"] == "1.0"
    assert captured["AGENTLOOPGATE_MODEL_USAGE_LEDGER_SCHEMA_VERSION"] == "1.1"


def test_dsh_tau3_evidence_join_preserves_both_trace_authorities(tmp_path: Path) -> None:
    payload = tau3_result()
    payload["info"]["agent_info"]["llm"] = "deepseek-official/deepseek-v4-flash"
    payload["simulations"][0]["messages"][0]["usage"]["cache_read_tokens"] = 7
    payload["simulations"][0]["messages"][0]["generation_time_seconds"] = 0.35
    payload["simulations"][0]["messages"].insert(
        0,
        {
            "role": "assistant",
            "content": "Hi! How can I help you today?",
            "turn_idx": 0,
            "usage": None,
            "tool_calls": None,
            "raw_data": None,
            "generation_time_seconds": None,
        },
    )
    tau_context = context(model_id="deepseek-official/deepseek-v4-flash")
    config = pilot_config(tmp_path)
    session_id = DshTau3TurnClient.session_id(
        config.experiment_namespace,
        "task_001",
        42,
    )
    payload["simulations"][0]["messages"][1]["raw_data"] = {
        "agentloopgate_protocol": "dsh-tau3/1.1",
        "dsh_session_id_hash": canonical_digest({"session_id": session_id})
    }
    raw = write_json(tmp_path / "upstream/results.json", payload)
    tau_result = Tau3Adapter(tmp_path, checkout=tmp_path / "tau3").ingest(
        raw,
        tau_context,
    )
    bridge = BridgeService(tmp_path)
    ingested = bridge.handle(
        BridgeRequest(
            protocol_version="1.0",
            request_id="TEST_DSH_INGEST",
            method="events.ingest",
            payload={
                "batch_id": "TEST_DSH_BATCH",
                "session_id": session_id,
                "persistence_kind": "jsonl",
                "ingest_mode": "reference",
                "events": [
                    {
                        "seq": 0,
                        "timestamp": "2026-08-20T00:00:00Z",
                        "event_type": "session/start",
                        "data": {"credential": "must-be-redacted"},
                    },
                    {
                        "seq": 1,
                        "timestamp": "2026-08-20T00:00:01Z",
                        "event_type": "turn/end",
                        "data": {"reason": "completed"},
                    },
                ],
            },
        )
    )
    assert ingested.ok
    synchronized = bridge.handle(
        BridgeRequest(
            protocol_version="1.0",
            request_id="TEST_DSH_SYNC",
            method="trace.sync",
            payload={
                "session_id": session_id,
                "source_revision": "deepseek-harness@pinned",
                "persistence_kind": "jsonl",
                "ingest_mode": "reference",
            },
        )
    )
    assert synchronized.ok

    linked = DshTau3EvidenceLinker(tmp_path, pilot=config).link(raw, tau_result)

    assert len(linked.evidence_joins) == 1
    dsh_record = linked.dsh_records[0]
    join = linked.evidence_joins[0]
    assert dsh_record.source is RunSource.DSH
    assert dsh_record.runtime_host is RuntimeHost.DEEPSEEK_HARNESS
    assert dsh_record.success is tau_result.records[0].success
    assert dsh_record.input_tokens == 107
    assert dsh_record.latency_ms == 350
    assert join.dsh_source_trace_ref != join.tau_source_trace_ref
    assert join.tau_run_id == tau_result.records[0].run_id
    assert join.dsh_run_id == dsh_record.run_id
    assert (tmp_path / f"runs/evidence_joins/{join.join_id}.json").is_file()
    bridge_artifacts = (tmp_path / "runs/dsh/inbox").rglob("*.json")
    assert all(
        "must-be-redacted" not in path.read_text(encoding="utf-8")
        for path in bridge_artifacts
    )


def test_dsh_latency_rejects_unprovenanced_generated_assistant_message() -> None:
    with pytest.raises(OutcomeImportError, match="provenance_missing"):
        DshTau3EvidenceLinker._agent_latency_ms(
            [
                {
                    "role": "assistant",
                    "turn_idx": 1,
                    "generation_time_seconds": 0.25,
                }
            ]
        )


@pytest.mark.parametrize("version", ["dsh-tau3/1.0", "dsh-tau3/1.1"])
def test_dsh_latency_accepts_registered_protocol_versions(version: str) -> None:
    assert DshTau3EvidenceLinker._agent_latency_ms(
        [
            {
                "role": "assistant",
                "turn_idx": 1,
                "generation_time_seconds": 0.25,
                "raw_data": {"agentloopgate_protocol": version},
            }
        ]
    ) == 250


def test_dsh_latency_distinguishes_unsupported_protocol_version() -> None:
    with pytest.raises(OutcomeImportError, match="protocol_version_unsupported"):
        DshTau3EvidenceLinker._agent_latency_ms(
            [
                {
                    "role": "assistant",
                    "turn_idx": 1,
                    "generation_time_seconds": 0.25,
                    "raw_data": {"agentloopgate_protocol": "dsh-tau3/9.9"},
                }
            ]
        )


def test_tau3_outcome_first_ingest_maps_evidence_and_agent_metrics(tmp_path: Path) -> None:
    raw = write_json(tmp_path / "upstream" / "results.json", tau3_result())
    adapter = Tau3Adapter(tmp_path, checkout=tmp_path / "tau3")

    imported = adapter.ingest(raw, context())

    assert imported.valid_denominator == 1
    assert len(imported.records) == 1
    record = imported.records[0]
    assert record.success is True
    assert record.input_tokens == 100
    assert record.output_tokens == 20
    assert record.latency_ms == 1250
    assert str(record.cost) == "0.0125"
    assert imported.diagnostics[0].action_checks[0].matched is False
    assert imported.diagnostics[0].reward_basis == ["DB"]
    assert adapter.verify(imported.source_trace_ref).value == "verified"
    assert (tmp_path / f"runs/normalized/{record.run_id}.json").is_file()


def test_tau3_infrastructure_error_is_retained_but_excluded_from_denominator(
    tmp_path: Path,
) -> None:
    result = tau3_result(infrastructure_error=True)
    result["simulations"][0]["agent_cost"] = None
    raw = write_json(
        tmp_path / "upstream" / "results.json",
        result,
    )

    imported = Tau3Adapter(tmp_path, checkout=tmp_path / "tau3").ingest(raw, context())

    assert imported.valid_denominator == 0
    assert imported.records[0].run_validity is RunValidity.INFRA_INVALID
    assert imported.records[0].success is None
    assert imported.records[0].cost is None


def test_tau3_ingest_rejects_wrong_commit_and_missing_formal_cost(tmp_path: Path) -> None:
    wrong_commit = tau3_result()
    wrong_commit["info"]["git_commit"] = "main"
    with pytest.raises(OutcomeImportError, match="commit"):
        Tau3Adapter(tmp_path, checkout=tmp_path / "tau3").ingest(
            write_json(tmp_path / "wrong.json", wrong_commit),
            context(),
        )

    no_cost = tau3_result()
    no_cost["simulations"][0]["agent_cost"] = None
    with pytest.raises(OutcomeImportError, match="agent_cost"):
        Tau3Adapter(tmp_path, checkout=tmp_path / "tau3").ingest(
            write_json(tmp_path / "no-cost.json", no_cost),
            context(),
        )


def test_jsonl_outcome_import_requires_independent_matching_evidence(tmp_path: Path) -> None:
    adapter = JsonlOutcomeAdapter(tmp_path)
    valid = write_outcome_jsonl(tmp_path)

    community_context = context(model_id="community/model")
    imported = adapter.ingest(valid, community_context)

    assert imported.records[0].success is True
    assert imported.valid_denominator == 1
    assert adapter.verify(imported.source_trace_ref).value == "verified"

    cases = [
        ({"evaluator_id": "agent-under-test"}, "self-evaluation"),
        ({"pool": "selection"}, "pool"),
        ({"snapshot_id": "S_OTHER"}, "snapshot"),
        ({"with_evidence": False}, "evidence"),
    ]
    for index, (overrides, expected) in enumerate(cases):
        case_root = tmp_path / f"case-{index}"
        values = {
            "evaluator_id": "bank-evaluator",
            "pool": "pilot",
            "snapshot_id": "S_A0",
            "with_evidence": True,
            **overrides,
        }
        outcome = write_outcome_jsonl(case_root, **values)
        with pytest.raises(OutcomeImportError, match=expected):
            JsonlOutcomeAdapter(case_root).ingest(outcome, community_context)


def test_tau3_duplicate_or_missing_expected_runs_are_rejected(tmp_path: Path) -> None:
    payload = tau3_result()
    payload["simulations"].append(deepcopy(payload["simulations"][0]))
    with pytest.raises(OutcomeImportError, match="duplicate"):
        Tau3Adapter(tmp_path, checkout=tmp_path / "tau3").ingest(
            write_json(tmp_path / "duplicate.json", payload),
            context(),
        )


def test_tau3_catalog_builds_deterministic_six_pool_plan(tmp_path: Path) -> None:
    tasks: list[dict] = []
    specs = [
        (55, None),
        (22, "apply_for_credit_card"),
        (12, "transfer_to_human_agents"),
        (6, "submit_referral"),
        (1, "change_user_email"),
        (1, "submit_transaction"),
    ]
    index = 1
    for count, action_name in specs:
        for _ in range(count):
            actions = []
            if action_name:
                actions = [{"name": action_name}, {"name": "log_tool_call"}]
            tasks.append(
                {
                    "id": f"task_{index:03d}",
                    "required_documents": [f"doc-{index}", f"rule-{index}"],
                    "evaluation_criteria": {"actions": actions},
                }
            )
            index += 1
    source = write_json(tmp_path / "tasks.json", tasks)
    catalog = Tau3TaskCatalog.from_path(source, verify_official_digest=False)

    first = catalog.build_split_plan()
    second = catalog.build_split_plan()

    assert first == second
    assert {pool: len(manifest.tasks) for pool, manifest in first.manifests.items()} == {
        Pool.PILOT: 7,
        Pool.UPDATE_SOURCE: 25,
        Pool.UPDATE_CHECK: 10,
        Pool.SELECTION: 15,
        Pool.RELEASE_ID: 20,
        Pool.RELEASE_OOD: 20,
    }
    ood_families = {
        task.workflow_family for task in first.manifests[Pool.RELEASE_OOD].tasks
    }
    assert ood_families == {"human_transfer", "referral", "high_risk_account_action"}
    other_families = {
        task.workflow_family
        for pool, manifest in first.manifests.items()
        if pool is not Pool.RELEASE_OOD
        for task in manifest.tasks
    }
    assert ood_families.isdisjoint(other_families)
    assert len(first.replay_task_ids) == 10
    assert set(first.replay_task_ids).issubset(
        {task.task_id for task in first.manifests[Pool.UPDATE_SOURCE].tasks}
    )
