"""Runtime-neutral trace adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agentloopgate.schemas import (
    EvidenceReceipt,
    EvidenceStatus,
    IngestMode,
    PersistenceKind,
    RunRecord,
    RuntimeHost,
    SourceTraceRef,
)


class TraceError(RuntimeError):
    """Base error for trace ingestion and verification."""


class EvidenceIntegrityError(TraceError):
    """Evidence no longer matches its immutable digest or binding."""


class EvidenceIncompleteError(TraceError):
    """Evidence has a sequence gap and cannot enter a formal gate."""


@dataclass(frozen=True, slots=True)
class RuntimeSource:
    path: Path
    runtime_host: RuntimeHost
    persistence_kind: PersistenceKind
    ingest_mode: IngestMode = IngestMode.REFERENCE


@runtime_checkable
class RuntimeTraceAdapter(Protocol):
    def attach(self, source: RuntimeSource) -> SourceTraceRef: ...

    def sync(self, ref: SourceTraceRef) -> EvidenceReceipt: ...

    def verify(self, ref: SourceTraceRef) -> EvidenceStatus: ...

    def normalize(self, receipt: EvidenceReceipt) -> list[RunRecord]: ...


def require_verified_for_gate(ref: SourceTraceRef) -> None:
    if ref.evidence_status is EvidenceStatus.INCOMPLETE or not ref.cursor_complete:
        raise EvidenceIncompleteError("trace evidence is incomplete and cannot enter a formal gate")
    if ref.evidence_status is not EvidenceStatus.VERIFIED:
        raise EvidenceIntegrityError("trace evidence is not verified")

