"""Fail-closed bridge service exposed to DeepSeek Harness plugins."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agentloopgate.candidates import CandidateRegistry
from agentloopgate.contracts import (
    canonical_digest,
    canonical_json_bytes,
    computed_contract_digest,
    file_digest,
    load_contract,
    verify_contract_digest,
)
from agentloopgate.mutation import (
    CandidateChecker,
    freeze_trust_kernel,
    load_asset_manifest,
    load_mutation_policy,
)
from agentloopgate.schemas import (
    DecisionRecord,
    EvidenceStatus,
    IngestMode,
    RuntimeHost,
    SourceTraceRef,
)

from .models import (
    BridgeError,
    BridgeRequest,
    BridgeResponse,
    CandidateCheckPayload,
    DecisionExplainPayload,
    EmptyPayload,
    EventBatchPayload,
    StoredBridgeRequest,
    StoredEventBatch,
    TraceSyncPayload,
    TraceVerifyPayload,
)

_SENSITIVE_KEY = re.compile(
    r"^(?:api[_-]?key|authorization|credential|credentials|secret|access[_-]?token|"
    r"refresh[_-]?token|session[_-]?id)$",
    re.IGNORECASE,
)
_FORBIDDEN_METHODS = {
    "final.read",
    "gate.modify",
    "shell.exec",
    "snapshot.promote",
    "snapshot.rollback",
    "split.modify",
}


class BridgeService:
    """Dispatch a deliberately small, non-privileged bridge method set."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "health": self._health,
            "contract.validate": self._contract_validate,
            "candidate.check": self._candidate_check,
            "decision.explain": self._decision_explain,
            "events.ingest": self._events_ingest,
            "trace.sync": self._trace_sync,
            "trace.verify": self._trace_verify,
        }

    @property
    def supported_methods(self) -> list[str]:
        return sorted(self._handlers)

    def sync_trace(self, payload: TraceSyncPayload) -> dict[str, Any]:
        """Synchronize an ingested DSH binding without protocol-cache side effects."""
        return self._trace_sync(payload.model_dump(mode="json"))

    def verify_trace(self, source_trace_id: str) -> dict[str, Any]:
        """Verify a DSH trace reference without writing a bridge request receipt."""
        return self._trace_verify({"source_trace_id": source_trace_id})

    def handle(self, request: BridgeRequest) -> BridgeResponse:
        request_digest = canonical_digest(request)
        cached = self._load_cached(request.request_id)
        if cached is not None:
            if cached.request_digest == request_digest:
                return cached.response
            return self._failure(
                request.request_id,
                "request_id_conflict",
                "request_id was already used for a different request",
                "Retry with a new request_id.",
            )

        if request.method in _FORBIDDEN_METHODS or request.method.startswith("propose."):
            response = self._failure(
                request.request_id,
                "method_forbidden",
                f"method is outside the bridge authority: {request.method}",
                "Use the human-controlled AgentLoopGate CLI for privileged operations.",
            )
        elif request.method not in self._handlers:
            response = self._failure(
                request.request_id,
                "method_unknown",
                f"unsupported bridge method: {request.method}",
                f"Use one of: {', '.join(self.supported_methods)}.",
            )
        else:
            try:
                result = self._handlers[request.method](request.payload)
                response = BridgeResponse(request_id=request.request_id, ok=True, result=result)
            except ValidationError as exc:
                response = self._failure(
                    request.request_id,
                    "payload_invalid",
                    self._validation_message(exc),
                    "Send a payload that conforms to the exported bridge schema.",
                )
            except (OSError, ValueError) as exc:
                response = self._failure(
                    request.request_id,
                    "operation_failed",
                    str(exc),
                    "Inspect the referenced local artifact and retry with a new request_id.",
                )

        self._store_cached(request.request_id, request_digest, response)
        return response

    def _health(self, raw: dict[str, Any]) -> dict[str, Any]:
        EmptyPayload.model_validate(raw)
        return {
            "core": "ready",
            "protocol_version": "1.0",
            "supported_methods": self.supported_methods,
            "propose_enabled": False,
        }

    def _contract_validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        EmptyPayload.model_validate(raw)
        contract = load_contract(self.project_root / "configs/objective_contract.yaml")
        if contract.frozen_at is not None or contract.contract_digest is not None:
            verify_contract_digest(contract)
        return {
            "valid": True,
            "project": contract.project,
            "frozen": contract.frozen_at is not None,
            "computed_digest": computed_contract_digest(contract),
        }

    def _candidate_check(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = CandidateCheckPayload.model_validate(raw)
        manifest = load_asset_manifest(self.project_root / "configs/harness_assets.yaml")
        policy = load_mutation_policy(self.project_root / "configs/mutation_policy.yaml")
        checker = CandidateChecker(
            self.project_root,
            manifest,
            policy,
            freeze_trust_kernel(self.project_root, policy),
        )
        record = CandidateRegistry(self.project_root, checker).load(payload.candidate_id)
        result = checker.check(self.project_root / record.patch_path)
        return {
            "candidate_id": record.candidate_id,
            "candidate_status": record.status.value,
            "disposition": result.disposition.value,
            "code": result.code.value,
            "message": result.message,
            "patch_digest": result.patch_digest,
            "risk_tier": result.risk_tier.value if result.risk_tier else None,
            "auto_executable": result.auto_executable,
        }

    def _decision_explain(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = DecisionExplainPayload.model_validate(raw)
        matches: list[DecisionRecord] = []
        for path in sorted((self.project_root / "reports").glob("*/decision.json")):
            try:
                record = DecisionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError):
                continue
            if record.decision_id == payload.decision_id:
                matches.append(record)
        if len(matches) != 1:
            raise ValueError(
                f"decision {payload.decision_id} was not found uniquely in local reports"
            )
        record = matches[0]
        return {
            "decision_id": record.decision_id,
            "candidate_id": record.candidate_id,
            "decision": record.decision.value,
            "failed_gates": [
                gate.name.value for gate in record.gates if gate.status.value == "fail"
            ],
            "summary": record.summary,
        }

    def _events_ingest(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = EventBatchPayload.model_validate(raw)
        session_hash = canonical_digest({"session_id": payload.session_id})
        safe_events = [
            event.model_copy(update={"data": _redact(event.data)}) for event in payload.events
        ]
        stored = StoredEventBatch(
            batch_id=payload.batch_id,
            session_id_hash=session_hash,
            persistence_kind=payload.persistence_kind,
            ingest_mode=payload.ingest_mode,
            events=safe_events,
        )
        batch_path = self._session_dir(session_hash) / f"{payload.batch_id}.json"
        self._write_once(batch_path, stored.model_dump(mode="json"))
        return {
            "accepted": len(safe_events),
            "batch_id": payload.batch_id,
            "session_id_hash": session_hash,
            "event_seq_start": min(event.seq for event in safe_events),
            "event_seq_end": max(event.seq for event in safe_events),
        }

    def _trace_sync(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = TraceSyncPayload.model_validate(raw)
        session_hash = canonical_digest({"session_id": payload.session_id})
        batches = self._load_batches(session_hash)
        if not batches:
            raise ValueError("no ingested events exist for this session binding")
        if any(batch.persistence_kind is not payload.persistence_kind for batch in batches):
            raise ValueError("persistence_kind does not match the ingested event batches")
        if any(batch.ingest_mode is not payload.ingest_mode for batch in batches):
            raise ValueError("ingest_mode does not match the ingested event batches")

        by_sequence: dict[int, dict[str, Any]] = {}
        for batch in batches:
            for event in batch.events:
                encoded = event.model_dump(mode="json")
                existing = by_sequence.get(event.seq)
                if existing is not None and existing != encoded:
                    raise ValueError(f"conflicting events share sequence number {event.seq}")
                by_sequence[event.seq] = encoded
        sequence = sorted(by_sequence)
        actual_start, end = sequence[0], sequence[-1]
        # DeepSeek Session sequence numbers begin at zero. A contiguous suffix
        # is still incomplete when earlier canonical events were never seen;
        # the reference range starts at the missing expected cursor so the
        # incomplete span is represented honestly by SourceTraceRef.
        complete = actual_start == 0 and sequence == list(range(actual_start, end + 1))
        start = actual_start if complete else 0
        evidence_status = EvidenceStatus.VERIFIED if complete else EvidenceStatus.INCOMPLETE
        revision_hash = canonical_digest({"source_revision": payload.source_revision})
        cursor_hash = canonical_digest(by_sequence)
        source_trace_id = (
            f"DSH_{session_hash[7:23]}_{revision_hash[7:15]}_{cursor_hash[7:23]}"
        )
        ref_path = self.project_root / "runs/trace_refs" / f"{source_trace_id}.json"
        existing_ref = (
            SourceTraceRef.model_validate_json(ref_path.read_text(encoding="utf-8"))
            if ref_path.exists()
            else None
        )
        mirror_path: Path | None = None
        mirror_digest: str | None = None
        if payload.ingest_mode is IngestMode.MIRROR:
            mirror_path = self.project_root / "runs/dsh/mirrors" / f"{source_trace_id}.jsonl"
            mirror_bytes = b"".join(
                canonical_json_bytes(by_sequence[number]) + b"\n" for number in sequence
            )
            self._write_once_bytes(mirror_path, mirror_bytes)
            mirror_digest = file_digest(mirror_path)
        trace_ref = SourceTraceRef(
            schema_version="1.0",
            source_trace_id=source_trace_id,
            runtime_host=RuntimeHost.DEEPSEEK_HARNESS,
            source_locator=f"dsh-session:{session_hash}",
            session_id_hash=session_hash,
            event_seq_start=start,
            event_seq_end=end,
            event_count=len(sequence),
            source_revision=payload.source_revision,
            persistence_kind=payload.persistence_kind,
            ingest_mode=payload.ingest_mode,
            mirror_path=(
                mirror_path.relative_to(self.project_root).as_posix()
                if mirror_path is not None
                else None
            ),
            mirror_digest=mirror_digest,
            cursor_complete=complete,
            evidence_status=evidence_status,
            created_at=existing_ref.created_at if existing_ref else datetime.now(UTC),
        )
        self._write_once(ref_path, trace_ref.model_dump(mode="json"))
        return self._trace_result(trace_ref)

    def _trace_verify(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = TraceVerifyPayload.model_validate(raw)
        path = self.project_root / "runs/trace_refs" / f"{payload.source_trace_id}.json"
        trace_ref = SourceTraceRef.model_validate_json(path.read_text(encoding="utf-8"))
        if trace_ref.runtime_host is not RuntimeHost.DEEPSEEK_HARNESS:
            raise ValueError("source trace does not belong to the DeepSeek Harness bridge")
        if trace_ref.ingest_mode is IngestMode.MIRROR:
            if not trace_ref.mirror_path:
                raise ValueError("mirror source trace is missing its artifact path")
            mirror = (self.project_root / trace_ref.mirror_path).resolve()
            if not mirror.is_relative_to(self.project_root):
                raise ValueError("mirror path escapes the project root")
            if file_digest(mirror) != trace_ref.mirror_digest:
                raise ValueError("source trace mirror digest mismatch")
            lines = [line for line in mirror.read_bytes().splitlines() if line]
            sequence = [int(json.loads(line)["seq"]) for line in lines]
        else:
            batches = self._load_batches(trace_ref.session_id_hash)
            sequence = sorted(
                {
                    event.seq
                    for batch in batches
                    for event in batch.events
                    if trace_ref.event_seq_start <= event.seq <= trace_ref.event_seq_end
                }
            )
        complete = (
            len(sequence) == trace_ref.event_count
            and sequence == list(range(trace_ref.event_seq_start, trace_ref.event_seq_end + 1))
        )
        status = EvidenceStatus.VERIFIED if complete else EvidenceStatus.INCOMPLETE
        result = self._trace_result(trace_ref)
        result["evidence_status"] = status.value
        result["digest_verified"] = trace_ref.ingest_mode is IngestMode.MIRROR
        result["reference_verified"] = trace_ref.ingest_mode is IngestMode.REFERENCE
        return result

    def _session_dir(self, session_hash: str) -> Path:
        return self.project_root / "runs/dsh/inbox" / session_hash.removeprefix("sha256:")

    def _load_batches(self, session_hash: str) -> list[StoredEventBatch]:
        batches: list[StoredEventBatch] = []
        for path in sorted(self._session_dir(session_hash).glob("*.json")):
            batches.append(StoredEventBatch.model_validate_json(path.read_text(encoding="utf-8")))
        return batches

    def _load_cached(self, request_id: str) -> StoredBridgeRequest | None:
        path = self.project_root / "runs/bridge/requests" / f"{request_id}.json"
        if not path.exists():
            return None
        return StoredBridgeRequest.model_validate_json(path.read_text(encoding="utf-8"))

    def _store_cached(
        self,
        request_id: str,
        request_digest: str,
        response: BridgeResponse,
    ) -> None:
        stored = StoredBridgeRequest(request_digest=request_digest, response=response)
        self._write_once(
            self.project_root / "runs/bridge/requests" / f"{request_id}.json",
            stored.model_dump(mode="json"),
        )

    @staticmethod
    def _trace_result(trace_ref: SourceTraceRef) -> dict[str, Any]:
        return {
            "source_trace_id": trace_ref.source_trace_id,
            "session_id_hash": trace_ref.session_id_hash,
            "event_count": trace_ref.event_count,
            "cursor_complete": trace_ref.cursor_complete,
            "evidence_status": trace_ref.evidence_status.value,
            "mirror_digest": trace_ref.mirror_digest,
        }

    @staticmethod
    def _failure(
        request_id: str,
        code: str,
        message: str,
        remediation: str,
    ) -> BridgeResponse:
        return BridgeResponse(
            request_id=request_id,
            ok=False,
            error=BridgeError(code=code, message=message, remediation=remediation),
        )

    @staticmethod
    def _validation_message(exc: ValidationError) -> str:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first["loc"]) or "payload"
        return f"{location}: {first['msg']}"

    @staticmethod
    def _write_once(path: Path, payload: object) -> None:
        BridgeService._write_once_bytes(path, canonical_json_bytes(payload) + b"\n")

    @staticmethod
    def _write_once_bytes(path: Path, encoded: bytes) -> None:
        if path.exists():
            if path.read_bytes() != encoded:
                raise ValueError(f"immutable bridge artifact conflict: {path.name}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.fullmatch(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
