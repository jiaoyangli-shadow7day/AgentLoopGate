"""Narrow protocols that keep deterministic analysis modules acyclic."""

from __future__ import annotations

from typing import Protocol

from agentloopgate.gates import CandidateSelectionInput, DualSelection


class SelectionView(Protocol):
    inputs: list[CandidateSelectionInput]
    selection: DualSelection
    selection_digest: str
