from __future__ import annotations

import io
import json
from pathlib import Path

from agentloopgate.bridge import (
    BridgeRequest,
    BridgeService,
    export_bridge_schema,
    serve_stream,
)
from agentloopgate.contracts import canonical_json_bytes


def request(request_id: str, method: str, payload: dict | None = None) -> BridgeRequest:
    return BridgeRequest(
        protocol_version="1.0",
        request_id=request_id,
        method=method,
        payload=payload or {},
    )


def minimal_project(root: Path) -> None:
    (root / "configs").mkdir(parents=True)
    (root / "configs/objective_contract.yaml").write_text(
        Path("configs/objective_contract.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def test_bridge_health_and_contract_validate_are_stable_and_idempotent(tmp_path: Path) -> None:
    minimal_project(tmp_path)
    service = BridgeService(tmp_path)

    health = service.handle(request("REQ_001", "health"))
    contract = service.handle(request("REQ_002", "contract.validate"))
    repeated = service.handle(request("REQ_002", "contract.validate"))

    assert health.ok is True
    assert health.result["core"] == "ready"
    assert contract.ok is True
    assert contract.result["valid"] is True
    assert repeated == contract
    assert len(list((tmp_path / "runs/bridge/requests").glob("*.json"))) == 2

    conflict = service.handle(
        request("REQ_002", "contract.validate", {"unexpected": True})
    )
    assert conflict.ok is False
    assert conflict.error.code == "request_id_conflict"


def test_event_ingest_trace_sync_and_verify_do_not_store_raw_session_id(
    tmp_path: Path,
) -> None:
    minimal_project(tmp_path)
    service = BridgeService(tmp_path)
    raw_session = "private-session-id-001"
    event_payload = {
        "batch_id": "BATCH_001",
        "session_id": raw_session,
        "persistence_kind": "jsonl",
        "events": [
            {
                "seq": 0,
                "timestamp": "2026-08-20T00:00:00Z",
                "event_type": "session.start",
                "data": {"model": "deepseek-chat", "authorization": "secret-value"},
            },
            {
                "seq": 1,
                "timestamp": "2026-08-20T00:00:01Z",
                "event_type": "tool.result",
                "data": {"status": "ok"},
            },
        ],
    }

    ingested = service.handle(request("REQ_INGEST", "events.ingest", event_payload))
    repeated = service.handle(request("REQ_INGEST", "events.ingest", event_payload))
    synced = service.handle(
        request(
            "REQ_SYNC",
            "trace.sync",
            {
                "session_id": raw_session,
                "source_revision": "deepseek-session-revision-1",
                "persistence_kind": "jsonl",
                "ingest_mode": "mirror",
            },
        )
    )
    verified = service.handle(
        request(
            "REQ_VERIFY",
            "trace.verify",
            {"source_trace_id": synced.result["source_trace_id"]},
        )
    )

    assert ingested.ok is True and ingested.result["accepted"] == 2
    assert repeated == ingested
    assert synced.ok is True and synced.result["evidence_status"] == "verified"
    assert verified.result["evidence_status"] == "verified"
    stored = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "runs").rglob("*")
        if path.is_file()
    )
    assert raw_session not in stored
    assert "secret-value" not in stored
    assert "[REDACTED]" in stored


def test_decision_explain_is_redacted_and_forbidden_methods_fail_closed(tmp_path: Path) -> None:
    minimal_project(tmp_path)
    decision_dir = tmp_path / "reports/EXP_001"
    decision_dir.mkdir(parents=True)
    decision_dir.joinpath("decision.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "decision_id": "D_001",
                "candidate_id": "C_001",
                "baseline_snapshot_id": "S_A0",
                "decision": "HOLD",
                "gates": [
                    {
                        "name": "ood_noninferiority",
                        "status": "fail",
                        "evidence_ref": "reports/gates/ood.json",
                    }
                ],
                "summary": "HOLD: OOD noninferiority failed",
                "human_approval": None,
                "created_at": "2026-08-20T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    service = BridgeService(tmp_path)

    explained = service.handle(
        request("REQ_EXPLAIN", "decision.explain", {"decision_id": "D_001"})
    )
    assert explained.ok is True
    assert explained.result == {
        "candidate_id": "C_001",
        "decision": "HOLD",
        "decision_id": "D_001",
        "failed_gates": ["ood_noninferiority"],
        "summary": "HOLD: OOD noninferiority failed",
    }

    for index, method in enumerate(("snapshot.promote", "final.read", "shell.exec")):
        denied = service.handle(request(f"REQ_DENY_{index}", method))
        assert denied.ok is False
        assert denied.error.code == "method_forbidden"
    unknown = service.handle(request("REQ_UNKNOWN", "anything.else"))
    assert unknown.ok is False
    assert unknown.error.code == "method_unknown"


def test_trace_sequence_gap_is_explicitly_incomplete(tmp_path: Path) -> None:
    minimal_project(tmp_path)
    service = BridgeService(tmp_path)
    raw_session = "gap-session"
    ingested = service.handle(
        request(
            "REQ_GAP_INGEST",
            "events.ingest",
            {
                "batch_id": "BATCH_GAP",
                "session_id": raw_session,
                "persistence_kind": "sqlite",
                "ingest_mode": "reference",
                "events": [
                    {
                        "seq": 0,
                        "timestamp": "2026-08-20T00:00:00Z",
                        "event_type": "turn/start",
                        "data": {"event_digest": "first"},
                    },
                    {
                        "seq": 2,
                        "timestamp": "2026-08-20T00:00:02Z",
                        "event_type": "turn/end",
                        "data": {"event_digest": "third"},
                    },
                ],
            },
        )
    )
    synced = service.handle(
        request(
            "REQ_GAP_SYNC",
            "trace.sync",
            {
                "session_id": raw_session,
                "source_revision": "deepseek-harness@gap-fixture",
                "persistence_kind": "sqlite",
                "ingest_mode": "reference",
            },
        )
    )

    assert ingested.ok is True
    assert synced.ok is True
    assert synced.result["cursor_complete"] is False
    assert synced.result["evidence_status"] == "incomplete"


def test_stream_limits_request_size_and_stdout_is_only_json(tmp_path: Path) -> None:
    minimal_project(tmp_path)
    valid = canonical_json_bytes(request("REQ_STREAM", "health").model_dump(mode="json")) + b"\n"
    oversized = b"{" + b"x" * (1024 * 1024) + b"}\n"
    source = io.BytesIO(valid + oversized)
    destination = io.BytesIO()

    serve_stream(BridgeService(tmp_path), source, destination)

    lines = destination.getvalue().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ok"] is True
    assert json.loads(lines[1])["error"]["code"] == "request_too_large"


def test_schema_and_types_are_generated_from_bridge_models(tmp_path: Path) -> None:
    artifacts = export_bridge_schema(tmp_path)
    first_schema = artifacts.schema_json.read_bytes()
    first_types = artifacts.typescript.read_bytes()
    repeated = export_bridge_schema(tmp_path)

    assert repeated == artifacts
    assert artifacts.schema_json.read_bytes() == first_schema
    assert artifacts.typescript.read_bytes() == first_types
    schema = json.loads(first_schema)
    assert "BridgeRequest" in schema["$defs"]
    assert "BridgeResponse" in schema["$defs"]
    generated_types = first_types.decode()
    assert "export interface BridgeRequest" in generated_types
    assert "export interface BridgeActor" in generated_types
    assert "actor?: BridgeActor" in generated_types
    assert "export type JsonValue" in generated_types
