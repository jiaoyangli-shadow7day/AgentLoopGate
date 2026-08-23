from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from agentloopgate.contracts import file_digest
from agentloopgate.runtime import (
    Tau3EvaluatorOverlay,
    apply_evaluator_overlay,
    computed_evaluator_overlay_digest,
    load_evaluator_overlay,
    verify_evaluator_overlay_sources,
)


def test_frozen_task053_overlay_is_content_addressed() -> None:
    overlay = load_evaluator_overlay(
        Path("configs/evaluator_overlays/banking_task_053_user_call_v1.json")
    )

    assert overlay.affected_task_ids == ["task_053"]
    assert overlay.insertions[0].action.requestor == "user"
    assert overlay.insertions[0].action.name == "call_discoverable_user_tool"
    assert computed_evaluator_overlay_digest(overlay) == overlay.overlay_digest


def test_overlay_verifies_source_and_inserts_without_mutating_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_path = (
        tmp_path
        / "data/tau2/domains/banking_knowledge/tasks/task_001.json"
    )
    task_path.parent.mkdir(parents=True)
    task_path.write_text('{"id":"task_001"}\n', encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "overlay_id": "OVERLAY_FIXTURE",
        "benchmark_commit": "fixture-commit",
        "incident_artifact": "artifacts/incident.json",
        "incident_digest": "sha256:" + "a" * 64,
        "affected_task_ids": ["task_001"],
        "insertions": [
            {
                "task_id": "task_001",
                "source_task_file_digest": file_digest(task_path),
                "after_action_id": "A_1",
                "action": {
                    "action_id": "A_2",
                    "requestor": "user",
                    "name": "call_discoverable_user_tool",
                    "arguments": {"discoverable_tool_name": "fixture_tool"},
                },
            }
        ],
        "overlay_digest": "sha256:" + "0" * 64,
    }
    draft = Tau3EvaluatorOverlay.model_validate(payload)
    overlay = draft.model_copy(
        update={"overlay_digest": computed_evaluator_overlay_digest(draft)}
    )
    verify_evaluator_overlay_sources(overlay, checkout=tmp_path)

    class FakeTask:
        def __init__(self) -> None:
            self.id = "task_001"
            self.evaluation_criteria = SimpleNamespace(
                actions=[SimpleNamespace(action_id="A_1")]
            )

        def model_copy(self, *, deep: bool) -> FakeTask:
            assert deep is True
            return copy.deepcopy(self)

    class FakeAction:
        @classmethod
        def model_validate(cls, value):
            return SimpleNamespace(**value)

    tau2 = ModuleType("tau2")
    data_model = ModuleType("tau2.data_model")
    tasks_module = ModuleType("tau2.data_model.tasks")
    tasks_module.Action = FakeAction
    monkeypatch.setitem(sys.modules, "tau2", tau2)
    monkeypatch.setitem(sys.modules, "tau2.data_model", data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.tasks", tasks_module)

    original = FakeTask()
    corrected = apply_evaluator_overlay([original], overlay)

    assert [item.action_id for item in original.evaluation_criteria.actions] == ["A_1"]
    assert [item.action_id for item in corrected[0].evaluation_criteria.actions] == [
        "A_1",
        "A_2",
    ]

    task_path.write_text('{"id":"task_001","drift":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="source task digest mismatch"):
        verify_evaluator_overlay_sources(overlay, checkout=tmp_path)


def test_overlay_rejects_tampered_digest(tmp_path: Path) -> None:
    source = Path("configs/evaluator_overlays/banking_task_053_user_call_v1.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["insertions"][0]["after_action_id"] = "unreviewed-anchor"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="overlay digest mismatch"):
        load_evaluator_overlay(path)
