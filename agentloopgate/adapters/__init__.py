"""Runtime and benchmark adapters."""

from agentloopgate.adapters.base import (
    AdapterHealth,
    BenchmarkAdapter,
    BenchmarkIngestResult,
    BenchmarkRunContext,
    BenchmarkRunRequest,
    BenchmarkUnavailableError,
    OutcomeDiagnostics,
    OutcomeImportError,
)
from agentloopgate.adapters.dsh_tau3 import (
    AGENT_NAME,
    DSH_COMMIT,
    DSH_VERSION,
    DshTau3Adapter,
    DshTau3EvidenceLinker,
    DshTau3PilotConfig,
    DshTau3PilotResult,
    PilotPricingConfig,
    load_pilot_pricing,
)
from agentloopgate.adapters.jsonl import JsonlOutcomeAdapter
from agentloopgate.adapters.tau3 import (
    TAU3_COMMIT,
    TAU3_VERSION,
    Tau3Adapter,
    Tau3SplitPlan,
    Tau3TaskCatalog,
)

__all__ = [
    "AdapterHealth",
    "BenchmarkAdapter",
    "BenchmarkIngestResult",
    "BenchmarkRunContext",
    "BenchmarkRunRequest",
    "BenchmarkUnavailableError",
    "DSH_COMMIT",
    "DSH_VERSION",
    "DshTau3Adapter",
    "DshTau3EvidenceLinker",
    "DshTau3PilotConfig",
    "DshTau3PilotResult",
    "PilotPricingConfig",
    "AGENT_NAME",
    "JsonlOutcomeAdapter",
    "load_pilot_pricing",
    "OutcomeDiagnostics",
    "OutcomeImportError",
    "TAU3_COMMIT",
    "TAU3_VERSION",
    "Tau3Adapter",
    "Tau3SplitPlan",
    "Tau3TaskCatalog",
]
