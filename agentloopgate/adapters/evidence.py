"""Append-only persistence shared by benchmark result adapters."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentloopgate.adapters.base import OutcomeDiagnostics, OutcomeImportError
from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.schemas import (
    EvidenceReceipt,
    EvidenceStatus,
    IngestMode,
    PersistenceKind,
    RunRecord,
    RuntimeHost,
    SourceTraceRef,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REDACTION_POLICY_DIGEST = canonical_digest(
    {"version": "benchmark-evidence-v1", "policy": "source-reference-no-secret-copy"}
)


class BenchmarkEvidenceStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def attach(
        self,
        source_path: Path,
        *,
        runtime_host: RuntimeHost,
        persistence_kind: PersistenceKind,
        event_count: int,
        session_identity: object,
        created_at: datetime,
    ) -> SourceTraceRef:
        if event_count < 1:
            raise OutcomeImportError("benchmark result contains no simulation events")
        source_path = source_path.resolve()
        relative = self.relative_path(source_path)
        revision = file_digest(source_path)
        identity = canonical_digest(
            {
                "source_revision": revision,
                "runtime_host": runtime_host,
                "event_count": event_count,
                "session_identity": session_identity,
            }
        )
        suffix = identity.removeprefix("sha256:")[:16].upper()
        ref = SourceTraceRef(
            schema_version="1.0",
            source_trace_id=f"STR_{suffix}",
            runtime_host=runtime_host,
            source_locator=f"artifact:{relative}",
            session_id_hash=canonical_digest(session_identity),
            event_seq_start=0,
            event_seq_end=event_count - 1,
            event_count=event_count,
            source_revision=revision,
            persistence_kind=persistence_kind,
            ingest_mode=IngestMode.REFERENCE,
            mirror_path=None,
            mirror_digest=None,
            cursor_complete=True,
            evidence_status=EvidenceStatus.VERIFIED,
            created_at=created_at,
        )
        self.write_json_once(
            self.path_for("trace_refs", ref.source_trace_id),
            ref.model_dump(mode="json"),
        )
        return ref

    def persist_run(
        self,
        *,
        ref: SourceTraceRef,
        event_index: int,
        record_factory: Any,
        diagnostic_factory: Any,
        collected_at: datetime,
    ) -> tuple[RunRecord, EvidenceReceipt, OutcomeDiagnostics]:
        if not 0 <= event_index < ref.event_count:
            raise OutcomeImportError("evidence event index is outside the source trace")
        provisional_id = canonical_digest(
            {"source_trace_id": ref.source_trace_id, "event_index": event_index}
        ).removeprefix("sha256:")[:16].upper()
        receipt_id = f"ER_{provisional_id}"
        record: RunRecord = record_factory(receipt_id)
        diagnostic: OutcomeDiagnostics = diagnostic_factory(receipt_id)
        receipt = EvidenceReceipt(
            schema_version="1.0",
            receipt_id=receipt_id,
            source_trace_id=ref.source_trace_id,
            run_id=record.run_id,
            event_seq_start=event_index,
            event_seq_end=event_index,
            event_count=1,
            redaction_policy_digest=_REDACTION_POLICY_DIGEST,
            normalized_record_digest=canonical_digest(record),
            collected_at=collected_at,
            error_count=0,
        )
        self.write_json_once(
            self.path_for("normalized", record.run_id),
            record.model_dump(mode="json"),
        )
        self.write_json_once(
            self.path_for("diagnostics", record.run_id),
            diagnostic.model_dump(mode="json"),
        )
        self.write_json_once(
            self.path_for("receipts", receipt.receipt_id),
            receipt.model_dump(mode="json"),
        )
        return record, receipt, diagnostic

    def verify(self, ref: SourceTraceRef) -> EvidenceStatus:
        try:
            registered = SourceTraceRef.model_validate_json(
                self.path_for("trace_refs", ref.source_trace_id).read_text(encoding="utf-8")
            )
            if canonical_digest(registered) != canonical_digest(ref):
                return EvidenceStatus.UNAVAILABLE
            prefix = "artifact:"
            if not ref.source_locator.startswith(prefix):
                return EvidenceStatus.UNAVAILABLE
            source = self.resolve_artifact_uri(ref.source_locator)
            if not source.is_file() or file_digest(source) != ref.source_revision:
                return EvidenceStatus.UNAVAILABLE
        except (OSError, ValueError):
            return EvidenceStatus.UNAVAILABLE
        return EvidenceStatus.VERIFIED

    def path_for(self, family: str, artifact_id: str) -> Path:
        safe_id = self.safe_id(artifact_id)
        return self.project_root / "runs" / family / f"{safe_id}.json"

    def relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError as exc:
            raise OutcomeImportError(
                "benchmark evidence must be located inside the project root"
            ) from exc

    def resolve_artifact_uri(self, uri: str) -> Path:
        prefix = "artifact:"
        if not uri.startswith(prefix):
            raise OutcomeImportError("evidence artifact_uri must use the artifact: scheme")
        relative = uri.removeprefix(prefix)
        if not relative or Path(relative).is_absolute():
            raise OutcomeImportError("evidence artifact_uri must be project-relative")
        candidate = (self.project_root / relative).resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise OutcomeImportError("evidence artifact_uri escapes the project root") from exc
        return candidate

    @staticmethod
    def safe_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise OutcomeImportError(f"unsafe artifact id: {value!r}")
        return value

    @staticmethod
    def write_json_once(path: Path, payload: object) -> None:
        encoded = canonical_json_bytes(payload) + b"\n"
        if path.exists():
            try:
                existing = canonical_json_bytes(
                    json.loads(path.read_text(encoding="utf-8"))
                ) + b"\n"
            except (OSError, json.JSONDecodeError) as exc:
                raise OutcomeImportError(f"existing artifact is unreadable: {path}") from exc
            if existing != encoded:
                raise OutcomeImportError(f"append-only artifact conflict: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)

