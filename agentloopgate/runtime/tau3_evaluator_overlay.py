"""Content-addressed evaluator/task corrections for the pinned τ³ runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.schemas import ArtifactId, Digest
from agentloopgate.schemas.models import NonEmpty, StrictModel


class Tau3OverlayAction(StrictModel):
    """One explicit reference action inserted without editing the upstream checkout."""

    action_id: NonEmpty
    requestor: Literal["assistant", "user"]
    name: NonEmpty
    arguments: dict[str, Any]
    info: str | None = None
    compare_args: list[NonEmpty] | None = None


class Tau3TaskActionInsertion(StrictModel):
    task_id: ArtifactId
    source_task_file_digest: Digest
    after_action_id: NonEmpty
    action: Tau3OverlayAction


class Tau3EvaluatorOverlay(StrictModel):
    """Frozen correction whose provenance and affected tasks are explicit."""

    schema_version: Literal["1.0"]
    overlay_id: ArtifactId
    benchmark_commit: NonEmpty
    incident_artifact: NonEmpty
    incident_digest: Digest
    affected_task_ids: list[ArtifactId] = Field(min_length=1)
    insertions: list[Tau3TaskActionInsertion] = Field(min_length=1)
    overlay_digest: Digest

    @model_validator(mode="after")
    def scope_is_exact_and_unique(self) -> Tau3EvaluatorOverlay:
        if len(self.affected_task_ids) != len(set(self.affected_task_ids)):
            raise ValueError("evaluator overlay affected task ids must be unique")
        insertion_tasks = [item.task_id for item in self.insertions]
        if set(insertion_tasks) != set(self.affected_task_ids):
            raise ValueError("evaluator overlay scope must exactly match its insertions")
        action_ids = [item.action.action_id for item in self.insertions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("evaluator overlay action ids must be unique")
        return self


def evaluator_overlay_digest_payload(overlay: Tau3EvaluatorOverlay) -> dict[str, Any]:
    payload = overlay.model_dump(mode="json", exclude={"overlay_digest"})
    for key in set(payload) - overlay.model_fields_set:
        payload.pop(key, None)
    for insertion, serialized in zip(
        overlay.insertions,
        payload["insertions"],
        strict=True,
    ):
        action = serialized["action"]
        for key in set(action) - insertion.action.model_fields_set:
            action.pop(key, None)
    return payload


def computed_evaluator_overlay_digest(overlay: Tau3EvaluatorOverlay) -> str:
    return canonical_digest(evaluator_overlay_digest_payload(overlay))


def verify_evaluator_overlay(overlay: Tau3EvaluatorOverlay) -> None:
    actual = computed_evaluator_overlay_digest(overlay)
    if actual != overlay.overlay_digest:
        raise ValueError(
            "evaluator overlay digest mismatch: "
            f"expected {overlay.overlay_digest}, got {actual}"
        )


def load_evaluator_overlay(path: Path) -> Tau3EvaluatorOverlay:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read evaluator overlay: {path}") from exc
    overlay = Tau3EvaluatorOverlay.model_validate(raw)
    verify_evaluator_overlay(overlay)
    return overlay


def verify_evaluator_overlay_sources(
    overlay: Tau3EvaluatorOverlay,
    *,
    checkout: Path,
) -> None:
    tasks_root = (
        checkout.resolve()
        / "data"
        / "tau2"
        / "domains"
        / "banking_knowledge"
        / "tasks"
    )
    for insertion in overlay.insertions:
        task_file = tasks_root / f"{insertion.task_id}.json"
        if not task_file.is_file():
            raise ValueError(f"evaluator overlay source task is missing: {insertion.task_id}")
        if file_digest(task_file) != insertion.source_task_file_digest:
            raise ValueError(
                "evaluator overlay source task digest mismatch: "
                f"{insertion.task_id}"
            )


def apply_evaluator_overlay(tasks: list[Any], overlay: Tau3EvaluatorOverlay) -> list[Any]:
    """Apply the verified action insertions to fresh τ³ Task model instances."""

    by_id = {task.id: task for task in tasks}
    if not set(overlay.affected_task_ids).issubset(by_id):
        missing = sorted(set(overlay.affected_task_ids) - set(by_id))
        raise ValueError("evaluator overlay tasks are unavailable: " + ", ".join(missing))
    corrected = list(tasks)
    positions = {task.id: index for index, task in enumerate(corrected)}
    for insertion in overlay.insertions:
        task = by_id[insertion.task_id].model_copy(deep=True)
        criteria = task.evaluation_criteria
        if criteria is None or criteria.actions is None:
            raise ValueError("evaluator overlay target has no reference actions")
        if any(item.action_id == insertion.action.action_id for item in criteria.actions):
            raise ValueError("evaluator overlay action already exists")
        after = [
            index
            for index, item in enumerate(criteria.actions)
            if item.action_id == insertion.after_action_id
        ]
        if len(after) != 1:
            raise ValueError("evaluator overlay anchor must occur exactly once")
        from tau2.data_model.tasks import Action

        criteria.actions.insert(
            after[0] + 1,
            Action.model_validate(insertion.action.model_dump(mode="python")),
        )
        corrected[positions[insertion.task_id]] = task
        by_id[insertion.task_id] = task
    return corrected


def install_evaluator_overlay_from_environment() -> Tau3EvaluatorOverlay | None:
    """Wrap the pinned τ³ task loader before its CLI resolves any task."""

    raw_path = os.environ.get("AGENTLOOPGATE_TAU3_EVALUATOR_OVERLAY", "").strip()
    if not raw_path:
        return None
    checkout_raw = os.environ.get("AGENTLOOPGATE_TAU3_CHECKOUT", "").strip()
    if not checkout_raw:
        raise RuntimeError("evaluator overlay requires AGENTLOOPGATE_TAU3_CHECKOUT")
    path = Path(raw_path).resolve()
    checkout = Path(checkout_raw).resolve()
    overlay = load_evaluator_overlay(path)
    verify_evaluator_overlay_sources(overlay, checkout=checkout)

    from tau2.registry import registry

    original = registry.get_tasks_loader("banking_knowledge")
    if getattr(original, "_agentloopgate_overlay_digest", None) == overlay.overlay_digest:
        return overlay

    def corrected_loader(task_split_name: str | None = None) -> list[Any]:
        return apply_evaluator_overlay(
            original(task_split_name=task_split_name),
            overlay,
        )

    corrected_loader._agentloopgate_overlay_digest = overlay.overlay_digest  # type: ignore[attr-defined]
    # The registry has no public replacement API in pinned tau2-bench v1.0.1.
    # This process-local replacement is isolated to the runner and leaves the
    # upstream checkout byte-for-byte unchanged.
    registry._tasks["banking_knowledge"] = corrected_loader
    return overlay
