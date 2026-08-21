"""Deterministic JSONL host-trace adapter used by no-key fixtures."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.schemas import (
    EvidenceReceipt,
    EvidenceStatus,
    IngestMode,
    RunRecord,
    RunSource,
    RuntimeHost,
    SourceTraceRef,
)
from agentloopgate.traces.base import (
    EvidenceIncompleteError,
    EvidenceIntegrityError,
    RuntimeSource,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REDACTED_KEYS = frozenset({"api_key", "authorization", "credential", "secret", "token"})
_REDACTION_POLICY = {
    "version": "fixture-v1",
    "redacted_keys": sorted(_REDACTED_KEYS | {"session_id"}),
}


class FixtureTraceAdapter:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def attach(self, source: RuntimeSource) -> SourceTraceRef:
        if source.runtime_host is not RuntimeHost.FIXTURE:
            raise ValueError("FixtureTraceAdapter only accepts the fixture runtime host")
        source_path = source.path.resolve()
        source_relative = self._relative_to_project(source_path)
        events = self._read_events(source_path)
        seq_start, seq_end, cursor_complete = self._sequence_state(events)
        session_id = self._single_session_id(events)
        source_revision = file_digest(source_path)
        identity_digest = canonical_digest(
            {
                "source_revision": source_revision,
                "runtime_host": source.runtime_host,
                "persistence_kind": source.persistence_kind,
                "ingest_mode": source.ingest_mode,
            }
        )
        suffix = identity_digest.removeprefix("sha256:")[:12].upper()
        source_trace_id = f"STR_{suffix}"
        binding_id = f"TB_{suffix}"
        existing_ref_path = self._ref_path(source_trace_id)
        existing_ref = (
            SourceTraceRef.model_validate_json(existing_ref_path.read_text(encoding="utf-8"))
            if existing_ref_path.is_file()
            else None
        )
        mirror_relative: str | None = None
        mirror_digest: str | None = None
        if source.ingest_mode is IngestMode.MIRROR:
            mirror_relative = f"runs/mirror/{source_trace_id}.jsonl"
            mirror = self._redact_events(events, session_id=session_id)
            mirror_path = self._resolve_project_path(mirror_relative)
            self._write_text_once(mirror_path, self._events_text(mirror))
            mirror_digest = file_digest(mirror_path)

        evidence_status = (
            EvidenceStatus.VERIFIED if cursor_complete else EvidenceStatus.INCOMPLETE
        )
        ref = SourceTraceRef(
            schema_version="1.0",
            source_trace_id=source_trace_id,
            runtime_host=source.runtime_host,
            source_locator=f"binding:{binding_id}",
            session_id_hash=canonical_digest(session_id),
            event_seq_start=seq_start if cursor_complete else 0,
            event_seq_end=seq_end,
            event_count=len(events),
            source_revision=source_revision,
            persistence_kind=source.persistence_kind,
            ingest_mode=source.ingest_mode,
            mirror_path=mirror_relative,
            mirror_digest=mirror_digest,
            cursor_complete=cursor_complete,
            evidence_status=evidence_status,
            created_at=existing_ref.created_at if existing_ref else datetime.now(UTC),
        )
        binding = {
            "schema_version": "1.0",
            "binding_id": binding_id,
            "source_path": source_relative,
            "source_trace_id": source_trace_id,
            "source_ref_digest": canonical_digest(ref),
        }
        self._write_json_once(self._binding_path(binding_id), binding)
        self._write_json_once(self._ref_path(source_trace_id), ref.model_dump(mode="json"))
        return ref

    def sync(self, ref: SourceTraceRef) -> EvidenceReceipt:
        events = self._verified_events(ref)
        receipt_id = self._receipt_id(ref)
        existing_receipt_path = self._receipt_path(receipt_id)
        existing_receipt = (
            EvidenceReceipt.model_validate_json(
                existing_receipt_path.read_text(encoding="utf-8")
            )
            if existing_receipt_path.is_file()
            else None
        )
        record = self._build_record(ref, receipt_id=receipt_id, events=events)
        receipt = EvidenceReceipt(
            schema_version="1.0",
            receipt_id=receipt_id,
            source_trace_id=ref.source_trace_id,
            run_id=record.run_id,
            event_seq_start=ref.event_seq_start,
            event_seq_end=ref.event_seq_end,
            event_count=ref.event_count,
            redaction_policy_digest=canonical_digest(_REDACTION_POLICY),
            normalized_record_digest=canonical_digest(record),
            collected_at=(
                existing_receipt.collected_at if existing_receipt else datetime.now(UTC)
            ),
            error_count=0,
        )
        self._write_json_once(
            self.normalized_path(record.run_id),
            record.model_dump(mode="json"),
        )
        self._write_json_once(
            self._receipt_path(receipt.receipt_id),
            receipt.model_dump(mode="json"),
        )
        return receipt

    def verify(self, ref: SourceTraceRef) -> EvidenceStatus:
        if not ref.cursor_complete or ref.evidence_status is EvidenceStatus.INCOMPLETE:
            return EvidenceStatus.INCOMPLETE
        try:
            self._verify_or_raise(ref)
        except EvidenceIntegrityError:
            return EvidenceStatus.UNAVAILABLE
        return EvidenceStatus.VERIFIED

    def normalize(self, receipt: EvidenceReceipt) -> list[RunRecord]:
        self._assert_registered_receipt(receipt)
        ref = self._load_ref(receipt.source_trace_id)
        if receipt.source_trace_id != ref.source_trace_id:
            raise EvidenceIntegrityError("receipt source trace does not match its registered ref")
        events = self._verified_events(ref)
        record = self._build_record(ref, receipt_id=receipt.receipt_id, events=events)
        if canonical_digest(record) != receipt.normalized_record_digest:
            raise EvidenceIntegrityError("normalized record digest mismatch")
        self._write_json_once(
            self.normalized_path(record.run_id),
            record.model_dump(mode="json"),
        )
        return [record]

    def normalized_path(self, run_id: str) -> Path:
        return self._resolve_project_path(f"runs/normalized/{self._safe_id(run_id)}.json")

    def mirror_path(self, ref: SourceTraceRef) -> Path:
        if ref.mirror_path is None:
            raise EvidenceIntegrityError("trace ref does not contain a mirror")
        return self._resolve_project_path(ref.mirror_path)

    def _verified_events(self, ref: SourceTraceRef) -> list[dict[str, Any]]:
        self._verify_or_raise(ref)
        binding = self._load_binding(ref)
        source_path = self._resolve_project_path(binding["source_path"])
        if source_path.is_file():
            return self._read_events(source_path)
        return self._read_events(self.mirror_path(ref))

    def _verify_or_raise(self, ref: SourceTraceRef) -> None:
        if not ref.cursor_complete or ref.evidence_status is EvidenceStatus.INCOMPLETE:
            raise EvidenceIncompleteError("trace sequence contains a gap")
        if ref.evidence_status is not EvidenceStatus.VERIFIED:
            raise EvidenceIntegrityError("trace ref is not marked verified")
        binding = self._load_binding(ref)
        if binding.get("source_ref_digest") != canonical_digest(ref):
            raise EvidenceIntegrityError("source trace ref digest mismatch")
        source_path = self._resolve_project_path(binding["source_path"])
        if source_path.exists():
            if file_digest(source_path) != ref.source_revision:
                raise EvidenceIntegrityError("host trace digest mismatch")
            self._assert_event_identity(ref, self._read_events(source_path))
        elif ref.ingest_mode is IngestMode.REFERENCE:
            raise EvidenceIntegrityError("referenced host trace is unavailable")

        if ref.ingest_mode is IngestMode.MIRROR:
            mirror_path = self.mirror_path(ref)
            if not mirror_path.is_file() or file_digest(mirror_path) != ref.mirror_digest:
                raise EvidenceIntegrityError("mirror digest mismatch")
            self._assert_event_identity(ref, self._read_events(mirror_path), check_session=False)

    def _assert_event_identity(
        self,
        ref: SourceTraceRef,
        events: list[dict[str, Any]],
        *,
        check_session: bool = True,
    ) -> None:
        seq_start, seq_end, complete = self._sequence_state(events)
        if (
            not complete
            or seq_start != ref.event_seq_start
            or seq_end != ref.event_seq_end
            or len(events) != ref.event_count
        ):
            raise EvidenceIntegrityError("event sequence identity mismatch")
        session_digest = (
            canonical_digest(self._single_session_id(events)) if check_session else None
        )
        if check_session and session_digest != ref.session_id_hash:
            raise EvidenceIntegrityError("session identity digest mismatch")

    def _build_record(
        self,
        ref: SourceTraceRef,
        *,
        receipt_id: str,
        events: list[dict[str, Any]],
    ) -> RunRecord:
        started = self._single_event(events, "run.started")
        finished = self._single_event(events, "run.finished")
        start_data = self._event_data(started)
        finish_data = self._event_data(finished)
        return RunRecord(
            schema_version="1.0",
            run_id=start_data["run_id"],
            attempt_id=start_data["attempt_id"],
            task_id=start_data["task_id"],
            pool=start_data["pool"],
            snapshot_id=start_data["snapshot_id"],
            candidate_id=start_data.get("candidate_id"),
            source=RunSource.FIXTURE,
            runtime_host=ref.runtime_host,
            runtime_version=start_data["runtime_version"],
            model_id=start_data["model_id"],
            benchmark_commit=start_data["benchmark_commit"],
            objective_digest=start_data["objective_digest"],
            split_digest=start_data["split_digest"],
            initial_state_digest=start_data["initial_state_digest"],
            terminal_state_digest=finish_data["terminal_state_digest"],
            trial_index=start_data["trial_index"],
            run_validity=finish_data["run_validity"],
            success=finish_data["success"],
            critical_violations=finish_data["critical_violations"],
            input_tokens=finish_data["input_tokens"],
            output_tokens=finish_data["output_tokens"],
            latency_ms=finish_data["latency_ms"],
            cost=finish_data["cost"],
            source_trace_ref=ref.source_trace_id,
            evidence_receipt_ref=receipt_id,
            created_at=finished["timestamp"],
        )

    def _load_ref(self, source_trace_id: str) -> SourceTraceRef:
        path = self._ref_path(source_trace_id)
        try:
            return SourceTraceRef.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EvidenceIntegrityError("registered source trace ref is unavailable") from exc

    def _load_binding(self, ref: SourceTraceRef) -> dict[str, Any]:
        prefix = "binding:"
        if not ref.source_locator.startswith(prefix):
            raise EvidenceIntegrityError("unsupported fixture source locator")
        binding_id = self._safe_id(ref.source_locator.removeprefix(prefix))
        try:
            binding = json.loads(self._binding_path(binding_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceIntegrityError("trace binding is unavailable") from exc
        if binding.get("binding_id") != binding_id:
            raise EvidenceIntegrityError("trace binding identity mismatch")
        return binding

    def _assert_registered_receipt(self, receipt: EvidenceReceipt) -> None:
        path = self._receipt_path(receipt.receipt_id)
        try:
            registered = EvidenceReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EvidenceIntegrityError("registered evidence receipt is unavailable") from exc
        if canonical_digest(registered) != canonical_digest(receipt):
            raise EvidenceIntegrityError("evidence receipt digest mismatch")

    def _binding_path(self, binding_id: str) -> Path:
        return self._resolve_project_path(
            f"runs/evidence/bindings/{self._safe_id(binding_id)}.json"
        )

    def _ref_path(self, source_trace_id: str) -> Path:
        return self._resolve_project_path(
            f"runs/evidence/source_refs/{self._safe_id(source_trace_id)}.json"
        )

    def _receipt_path(self, receipt_id: str) -> Path:
        return self._resolve_project_path(
            f"runs/evidence/receipts/{self._safe_id(receipt_id)}.json"
        )

    def _receipt_id(self, ref: SourceTraceRef) -> str:
        suffix = canonical_digest(
            {"source_trace_id": ref.source_trace_id, "source_revision": ref.source_revision}
        ).removeprefix("sha256:")[:12]
        return f"ER_{suffix.upper()}"

    def _relative_to_project(self, path: Path) -> str:
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError as exc:
            raise ValueError("trace source must be inside the project root") from exc

    def _resolve_project_path(self, relative: str) -> Path:
        path = (self.project_root / relative).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise EvidenceIntegrityError("trace path escapes the project root") from exc
        return path

    @staticmethod
    def _safe_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise EvidenceIntegrityError("artifact id contains unsafe path characters")
        return value

    @staticmethod
    def _read_events(path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict) or not isinstance(event.get("seq"), int):
                    raise EvidenceIntegrityError(f"invalid event at line {line_number}")
                events.append(event)
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceIntegrityError(f"host trace is not valid JSONL: {path}") from exc
        if not events:
            raise EvidenceIntegrityError("host trace contains no events")
        return events

    @staticmethod
    def _sequence_state(events: list[dict[str, Any]]) -> tuple[int, int, bool]:
        sequences = [event["seq"] for event in events]
        if sequences != sorted(set(sequences)):
            raise EvidenceIntegrityError("event sequences must be strictly increasing")
        start, end = sequences[0], sequences[-1]
        complete = start == 0 and sequences == list(range(start, end + 1))
        return start, end, complete

    @staticmethod
    def _single_session_id(events: list[dict[str, Any]]) -> str:
        sessions = {event.get("session_id") for event in events}
        if len(sessions) != 1 or not isinstance(next(iter(sessions)), str):
            raise EvidenceIntegrityError("host trace must contain exactly one session id")
        return next(iter(sessions))

    @staticmethod
    def _single_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
        matches = [event for event in events if event.get("type") == event_type]
        if len(matches) != 1:
            raise EvidenceIntegrityError(f"trace must contain exactly one {event_type} event")
        return matches[0]

    @staticmethod
    def _event_data(event: dict[str, Any]) -> dict[str, Any]:
        data = event.get("data")
        if not isinstance(data, dict):
            raise EvidenceIntegrityError("trace event data must be an object")
        return data

    @classmethod
    def _redact_events(
        cls,
        events: list[dict[str, Any]],
        *,
        session_id: str,
    ) -> list[dict[str, Any]]:
        def redact(value: Any) -> Any:
            if isinstance(value, dict):
                result: dict[str, Any] = {}
                for key, item in value.items():
                    if key == "session_id":
                        result["session_id_hash"] = canonical_digest(session_id)
                    elif key.lower() in _REDACTED_KEYS:
                        result[key] = "[REDACTED]"
                    else:
                        result[key] = redact(item)
                return result
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        return [redact(event) for event in events]

    @staticmethod
    def _events_text(events: list[dict[str, Any]]) -> str:
        return "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for event in events
        )

    @staticmethod
    def _write_json_once(path: Path, payload: Any) -> None:
        FixtureTraceAdapter._write_text_once(
            path,
            canonical_json_bytes(payload).decode("utf-8") + "\n",
        )

    @staticmethod
    def _write_text_once(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise EvidenceIntegrityError(f"append-only artifact already differs: {path}")
            return
        path.write_text(content, encoding="utf-8")
