"""Fail-closed bridge service exposed to DeepSeek Harness plugins."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
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
_SAFE_EVENT_TYPES = frozenset({
    "agent-preset/selected", "agent/inbox/spliced", "approval/asked", "approval/decided",
    "approval/policy", "assistant/chunk", "assistant/message", "command/done", "command/run",
    "compaction/end", "compaction/prune", "compaction/start", "compaction/summary",
    "feedback/record", "goal/change", "hook/invoked", "hook/result", "llm/retry",
    "llm/retry-started", "permission/preset", "plan/mode", "request/context", "request/header",
    "sandbox/mode", "schedule/change", "session/end-seed", "session/title",
    "session/title-llm-request", "step/end", "step/start", "subagent/descriptor",
    "team/member", "team/message/delivered", "team/message/queued", "team/task", "todo/write",
    "tool-workflow/agent-end", "tool-workflow/agent-start", "tool-workflow/run-end",
    "tool-workflow/run-start", "tool/call", "tool/code-dispatch", "tool/code-dispatch-start",
    "tool/result", "turn/end", "turn/start", "user/message", "web/deepseek-search-llm-request",
    "session.start", "session/start", "tool.result",
})
_SAFE_DATA_KEYS = frozenset({
    "event_digest", "value_digest", "content", "model", "status", "reason", "type", "kind",
    "name", "data", "message", "messages", "usage", "input_tokens", "output_tokens",
    "prompt_tokens", "completion_tokens", "duration_ms", "latency_ms", "arguments", "result",
})
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
        try:
            runtime_path = self.project_root / "configs/runtime_dsh.yaml"
            runtime = (
                yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
                if runtime_path.exists() else {}
            )
            if not isinstance(runtime, dict) or not isinstance(runtime.get("trace", {}), dict):
                raise ValueError("invalid runtime trace configuration")
            policy_path = runtime.get("trace", {}).get(
                "redact_policy", "configs/trace_redaction.yaml"
            )
            if not isinstance(policy_path, str):
                raise ValueError("invalid trace redaction path")
            config_path = (self.project_root / policy_path).resolve()
            if not config_path.is_relative_to(self.project_root):
                raise ValueError("trace redaction path escapes the project root")
            policy = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if (not isinstance(policy, dict) or policy.get("schema_version") != "1.0"
                or policy.get("replacement") != "[REDACTED]"
                or not isinstance(policy.get("sensitive_keys"), list)
                or not all(isinstance(key, str) and key for key in policy["sensitive_keys"])
                or type(policy.get("max_text_bytes")) is not int
                or policy["max_text_bytes"] < 1):
                raise ValueError("invalid trace redaction policy")
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("trace redaction policy is unavailable or invalid") from exc
        session_hash = canonical_digest({"session_id": payload.session_id})
        safe_events = [
            event.model_copy(update={
                "data": _redact(event.data, policy),
                "event_type": (
                    event.event_type if event.event_type in _SAFE_EVENT_TYPES else "other"
                ),
            })
            for event in payload.events
        ]
        stored = StoredEventBatch(
            batch_id=payload.batch_id,
            session_id_hash=session_hash,
            persistence_kind=payload.persistence_kind,
            ingest_mode=payload.ingest_mode,
            redaction_policy_digest=canonical_digest(policy),
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
        policy_digests = {batch.redaction_policy_digest for batch in batches}
        if None in policy_digests or len(policy_digests) != 1:
            raise ValueError("session batches lack a consistent redaction policy")
        policy_digest = next(iter(policy_digests))

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
            f"DSH2_{session_hash[7:23]}_{revision_hash[7:15]}_{cursor_hash[7:23]}_"
            f"{policy_digest[7:23]}"
        )
        self._write_once(
            self.project_root / "runs/dsh/trace_policies" / f"{source_trace_id}.json",
            {"redaction_policy_digest": policy_digest},
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
        if trace_ref.source_trace_id != payload.source_trace_id:
            raise ValueError("source trace identity mismatch")
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
            events = [json.loads(line) for line in lines]
            sequence = [int(event["seq"]) for event in events]
            by_sequence = dict(zip(sequence, events, strict=True))
        else:
            batches = self._load_batches(trace_ref.session_id_hash)
            by_sequence = {}
            for batch in batches:
                for event in batch.events:
                    if trace_ref.event_seq_start <= event.seq <= trace_ref.event_seq_end:
                        encoded = event.model_dump(mode="json")
                        if event.seq in by_sequence and by_sequence[event.seq] != encoded:
                            raise ValueError("conflicting events share a sequence number")
                        by_sequence[event.seq] = encoded
            sequence = sorted(by_sequence)
        revision_hash = canonical_digest({"source_revision": trace_ref.source_revision})
        cursor_hash = canonical_digest(by_sequence)
        suffix = (
            f"{trace_ref.session_id_hash[7:23]}_{revision_hash[7:15]}_"
            f"{cursor_hash[7:23]}"
        )
        if trace_ref.source_trace_id.startswith("DSH2_"):
            policy_path = self.project_root / "runs/dsh/trace_policies" / (
                f"{trace_ref.source_trace_id}.json"
            )
            policy_record = json.loads(policy_path.read_text(encoding="utf-8"))
            if not isinstance(policy_record, dict):
                raise ValueError("invalid trace redaction policy record")
            policy_digest = policy_record.get("redaction_policy_digest")
            if not isinstance(policy_digest, str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", policy_digest
            ):
                raise ValueError("invalid trace redaction policy digest")
            if trace_ref.ingest_mode is IngestMode.REFERENCE and any(
                batch.redaction_policy_digest != policy_digest
                for batch in batches
                if any(trace_ref.event_seq_start <= event.seq <= trace_ref.event_seq_end
                       for event in batch.events)
            ):
                raise ValueError("source batch redaction policy mismatch")
            expected_id = f"DSH2_{suffix}_{policy_digest[7:23]}"
        else:
            expected_id = f"DSH_{suffix}"
        if expected_id != trace_ref.source_trace_id:
            raise ValueError("source trace content or policy digest mismatch")
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


def _redact(value: Any, policy: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        configured_keys = {key.casefold() for key in policy["sensitive_keys"]}
        safe_names = {
            str(key) for key in value
            if str(key) in _SAFE_DATA_KEYS or str(key).casefold() in configured_keys
            or _SENSITIVE_KEY.fullmatch(str(key))
        }
        result = {}
        anonymous = 0
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            if name in safe_names:
                output_key = name
            else:
                while f"[FIELD_{anonymous}]" in safe_names:
                    anonymous += 1
                output_key = f"[FIELD_{anonymous}]"
                anonymous += 1
            result[output_key] = (
                "[REDACTED]"
                if _SENSITIVE_KEY.fullmatch(name) or name.casefold() in configured_keys
                else item
                if name in {"event_digest", "value_digest"}
                and isinstance(item, str)
                and re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", item)
                else _redact(item, policy)
            )
        return result
    if isinstance(value, list):
        return [_redact(item, policy) for item in value]
    if isinstance(value, (str, int, float)):
        return "[REDACTED]"
    return value
