"""Trace evidence public API."""

from agentloopgate.adapters.fixture import FixtureTraceAdapter
from agentloopgate.traces.base import (
    EvidenceIncompleteError,
    EvidenceIntegrityError,
    RuntimeSource,
    RuntimeTraceAdapter,
    TraceError,
    require_verified_for_gate,
)

__all__ = [
    "EvidenceIncompleteError",
    "EvidenceIntegrityError",
    "FixtureTraceAdapter",
    "RuntimeSource",
    "RuntimeTraceAdapter",
    "TraceError",
    "require_verified_for_gate",
]

