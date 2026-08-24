from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _module(name: str):
    path = Path(__file__).parents[2] / f"scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _module("verify_publication_candidate")


def test_repository_is_ready_for_owner_publication_review() -> None:
    root = Path(__file__).parents[2]
    result = verifier.verify_publication_candidate(root)

    assert result["status"] == "ready_for_owner_publication_review"
    assert result["publication_authorized"] is False
    assert result["publication_action_performed"] is False
    assert result["public_package_file_count"] == 18
    assert result["remaining_blockers"] == ["owner_publication_authorization"]
