"""Bounded stdio JSONL transport and generated bridge contract artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from agentloopgate.contracts import canonical_json_bytes

from .models import BridgeContract, BridgeError, BridgeRequest, BridgeResponse
from .service import BridgeService

MAX_REQUEST_BYTES = 1024 * 1024


@dataclass(frozen=True)
class BridgeArtifacts:
    schema_json: Path
    typescript: Path


def serve_stream(service: BridgeService, source: BinaryIO, destination: BinaryIO) -> None:
    """Serve JSONL without writing logs or diagnostics to the protocol stream."""
    while True:
        line = source.readline(MAX_REQUEST_BYTES + 2)
        if not line:
            return
        if len(line.rstrip(b"\r\n")) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
            while line and not line.endswith(b"\n"):
                line = source.readline(MAX_REQUEST_BYTES + 2)
            _emit(
                destination,
                _failure(
                    "INVALID_REQUEST",
                    "request_too_large",
                    "bridge request exceeds the 1 MiB limit",
                    "Split the event batch into at most 100 smaller events.",
                ),
            )
            continue
        try:
            request = BridgeRequest.model_validate_json(line)
        except ValidationError as exc:
            _emit(
                destination,
                _failure(
                    "INVALID_REQUEST",
                    "request_invalid",
                    _validation_message(exc),
                    "Send one valid BridgeRequest JSON object per line.",
                ),
            )
            continue
        _emit(destination, service.handle(request))


def export_bridge_schema(output_dir: Path) -> BridgeArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    schema_json = output_dir / "bridge.schema.json"
    typescript = output_dir / "bridge.ts"
    schema_json.write_bytes(canonical_json_bytes(BridgeContract.model_json_schema()) + b"\n")
    typescript.write_text(_TYPESCRIPT, encoding="utf-8")
    return BridgeArtifacts(schema_json=schema_json, typescript=typescript)


def _emit(destination: BinaryIO, response: BridgeResponse) -> None:
    destination.write(canonical_json_bytes(response) + b"\n")
    destination.flush()


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


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors(include_url=False)[0]
    location = ".".join(str(item) for item in first["loc"]) or "request"
    return f"{location}: {first['msg']}"


_TYPESCRIPT = """// Generated from AgentLoopGate bridge protocol v1.0. Do not edit.\n\
export type JsonScalar = string | number | boolean | null;\n\
export type JsonValue = JsonScalar | JsonValue[] | { [key: string]: JsonValue };\n\
export type JsonRecord = { [key: string]: JsonValue };\n\
\n\
export interface BridgeActor {\n\
  type: \"dsh_plugin\";\n\
  session_id_hash?: string;\n\
}\n\
\n\
export interface BridgeRequest {\n\
  protocol_version: \"1.0\";\n\
  request_id: string;\n\
  method: string;\n\
  payload: JsonRecord;\n\
  actor?: BridgeActor;\n\
}\n\
\n\
export interface BridgeError {\n\
  code: string;\n\
  message: string;\n\
  remediation: string;\n\
}\n\
\n\
export interface BridgeResponse {\n\
  protocol_version: \"1.0\";\n\
  request_id: string;\n\
  ok: boolean;\n\
  result: JsonRecord | null;\n\
  error: BridgeError | null;\n\
}\n"""
