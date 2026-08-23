"""Promotion gates and candidate selectors."""

from agentloopgate.gates.engine import GateEngine
from agentloopgate.gates.models import (
    BaselineSelectionInput,
    CandidateSelectionInput,
    DualSelection,
    GateAssessment,
    GateOutcome,
    SelectionPolicy,
)
from agentloopgate.gates.selection import DualSelector, SelectionError

__all__ = [
    "BaselineSelectionInput",
    "CandidateSelectionInput",
    "DualSelection",
    "DualSelector",
    "GateAssessment",
    "GateEngine",
    "GateOutcome",
    "SelectionPolicy",
    "SelectionError",
]
