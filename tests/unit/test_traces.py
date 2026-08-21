from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentloopgate.schemas import EvidenceStatus, IngestMode, PersistenceKind, RuntimeHost
from agentloopgate.traces import (
    EvidenceIncompleteError,
    EvidenceIntegrityError,
    FixtureTraceAdapter,
    RuntimeSource,
    RuntimeTraceAdapter,
    require_verified_for_gate,
)

HOST_TRACE = Path("tests/fixtures/trace/host_trace.jsonl")


def copy_host_trace(project_root: Path) -> Path:
    destination = project_root / "host" / "trace.jsonl"
    destination.parent.mkdir(parents=True)
    shutil.copyfile(HOST_TRACE, destination)
    return destination


def source(path: Path, *, mode: IngestMode) -> RuntimeSource:
    return RuntimeSource(
        path=path,
        runtime_host=RuntimeHost.FIXTURE,
        persistence_kind=PersistenceKind.JSONL,
        ingest_mode=mode,
    )


def test_fixture_adapter_implements_protocol_and_rebuilds_from_h0(tmp_path: Path) -> None:
    adapter = FixtureTraceAdapter(tmp_path)
    assert isinstance(adapter, RuntimeTraceAdapter)
    host_trace = copy_host_trace(tmp_path)

    ref = adapter.attach(source(host_trace, mode=IngestMode.REFERENCE))
    assert ref.evidence_status is EvidenceStatus.VERIFIED
    assert ref.source_locator.startswith("binding:")
    assert adapter.verify(ref) is EvidenceStatus.VERIFIED

    receipt = adapter.sync(ref)
    normalized_path = adapter.normalized_path(receipt.run_id)
    assert normalized_path.is_file()
    normalized_path.unlink()

    records = adapter.normalize(receipt)
    assert len(records) == 1
    assert records[0].run_id == "R_001"
    assert records[0].source_trace_ref == ref.source_trace_id
    assert normalized_path.is_file()

    repeated_ref = adapter.attach(source(host_trace, mode=IngestMode.REFERENCE))
    repeated_receipt = adapter.sync(repeated_ref)
    assert repeated_ref == ref
    assert repeated_receipt == receipt


def test_reference_mode_detects_host_trace_tampering(tmp_path: Path) -> None:
    adapter = FixtureTraceAdapter(tmp_path)
    host_trace = copy_host_trace(tmp_path)
    ref = adapter.attach(source(host_trace, mode=IngestMode.REFERENCE))

    host_trace.write_text(host_trace.read_text() + "\n", encoding="utf-8")

    assert adapter.verify(ref) is EvidenceStatus.UNAVAILABLE
    with pytest.raises(EvidenceIntegrityError, match="digest"):
        adapter.sync(ref)


def test_mirror_rebuilds_when_h0_is_unavailable_and_detects_mirror_tampering(
    tmp_path: Path,
) -> None:
    adapter = FixtureTraceAdapter(tmp_path)
    host_trace = copy_host_trace(tmp_path)
    ref = adapter.attach(source(host_trace, mode=IngestMode.MIRROR))
    receipt = adapter.sync(ref)

    mirror_path = adapter.mirror_path(ref)
    assert "fixture-session-001" not in mirror_path.read_text(encoding="utf-8")

    adapter.normalized_path(receipt.run_id).unlink()
    host_trace.unlink()
    rebuilt = adapter.normalize(receipt)
    assert rebuilt[0].run_id == "R_001"

    mirror_path.write_text(mirror_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert adapter.verify(ref) is EvidenceStatus.UNAVAILABLE
    with pytest.raises(EvidenceIntegrityError, match="mirror"):
        adapter.normalize(receipt)


def test_sequence_gap_is_incomplete_and_cannot_enter_gate(tmp_path: Path) -> None:
    adapter = FixtureTraceAdapter(tmp_path)
    host_trace = copy_host_trace(tmp_path)
    events = [json.loads(line) for line in host_trace.read_text().splitlines() if line.strip()]
    host_trace.write_text(
        "\n".join(json.dumps(event) for event in (events[0], events[2])) + "\n",
        encoding="utf-8",
    )

    ref = adapter.attach(source(host_trace, mode=IngestMode.REFERENCE))

    assert ref.evidence_status is EvidenceStatus.INCOMPLETE
    assert adapter.verify(ref) is EvidenceStatus.INCOMPLETE
    with pytest.raises(EvidenceIncompleteError):
        adapter.sync(ref)
    with pytest.raises(EvidenceIncompleteError):
        require_verified_for_gate(ref)


def test_trace_missing_leading_sequence_is_incomplete(tmp_path: Path) -> None:
    adapter = FixtureTraceAdapter(tmp_path)
    host_trace = copy_host_trace(tmp_path)
    events = [json.loads(line) for line in host_trace.read_text().splitlines() if line.strip()]
    shifted = [{**event, "seq": event["seq"] + 1} for event in events]
    host_trace.write_text(
        "\n".join(json.dumps(event) for event in shifted) + "\n",
        encoding="utf-8",
    )

    ref = adapter.attach(source(host_trace, mode=IngestMode.REFERENCE))

    assert ref.event_seq_start == 0
    assert ref.evidence_status is EvidenceStatus.INCOMPLETE
