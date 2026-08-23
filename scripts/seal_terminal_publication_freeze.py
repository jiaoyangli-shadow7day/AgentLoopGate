#!/usr/bin/env python3
"""Seal a content-addressed publication freeze from an already verified terminal.

This is a strictly no-model command.  It refuses to create bytes unless the
formal orchestrator can deeply verify an existing full or Selection-HOLD
terminal for the supplied frozen experiment.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

from agentloopgate.contracts import canonical_digest, canonical_json_bytes
from agentloopgate.experiment.service import load_formal_config


class PublicationFreezeBlocked(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicationFreezeBlocked(f"required object is invalid: {path}")
    return value


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicationFreezeBlocked(f"required mapping is invalid: {path}")
    return value


def _digest_field(path: Path, field: str) -> dict[str, Any]:
    value = _yaml(path)
    if not isinstance(value.get(field), str):
        raise PublicationFreezeBlocked(f"required digest missing: {path}")
    return {"path": path.as_posix(), "digest": value[field]}


def seal(root: Path, config_path: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    config_path = (root / config_path).resolve()
    config = load_formal_config(config_path)
    experiment_root = root / "runs/experiments" / config.experiment_id
    full = experiment_root / "outcome.json"
    hold = experiment_root / "selection_hold_outcome.json"
    if full.exists() == hold.exists():
        raise PublicationFreezeBlocked("exactly one verified terminal outcome is required")
    builder_path = Path(__file__).with_name("build_public_r2_package.py")
    spec = importlib.util.spec_from_file_location("publication_builder", builder_path)
    if spec is None or spec.loader is None:
        raise PublicationFreezeBlocked("cannot load terminal verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    terminal_kind, terminal = module._terminal_outcome(  # noqa: SLF001
        root,
        config_path,
        experiment_id=config.experiment_id,
        private_root=Path("runs/experiments") / config.experiment_id,
    )
    protocol = _digest_field(root / str(config.execution_protocol_config), "protocol_digest")
    study = _digest_field(root / str(config.study_plan_config), "study_digest")
    objective = _digest_field(root / "configs/objective_contract.yaml", "contract_digest")
    split = _digest_field(root / "configs/splits.yaml", "split_digest")
    pricing_path = root / str(config.pricing_config)
    pricing = {
        "path": pricing_path.relative_to(root).as_posix(),
        "digest": canonical_digest(_yaml(pricing_path)),
    }
    assets_path = root / "configs/harness_assets.yaml"
    assets = {
        "path": assets_path.relative_to(root).as_posix(),
        "digest": canonical_digest(_yaml(assets_path)),
    }
    prereg = _json(root / str(config.research_artifact_root) / "pre_run_preregistration.json")
    frozen_identity = prereg.get("frozen_identity")
    if not isinstance(frozen_identity, dict) or not isinstance(
        frozen_identity.get("source_revision"), str
    ):
        raise PublicationFreezeBlocked("R11 preregistration source identity is unavailable")
    payload = {
        "schema_version": "1.0",
        "experiment_id": config.experiment_id,
        "terminal_kind": terminal_kind,
        "terminal_outcome_digest": terminal.outcome_digest,
        "source_revision": frozen_identity["source_revision"],
        "evaluation_baseline": {"snapshot_id": terminal.baseline_snapshot_id},
        "objective": objective,
        "split": split,
        "pricing": pricing,
        "asset_manifest": assets,
        "execution_protocol": protocol,
        "study": study,
        "benchmark_runtime": {
            "commit": _yaml(root / str(config.execution_protocol_config))["benchmark_commit"]
        },
        "p0_immutability": {"status": "historical_evidence_preserved"},
    }
    payload["freeze_manifest_digest"] = canonical_digest(payload)
    encoded = canonical_json_bytes(payload) + b"\n"
    if output.exists() and output.read_bytes() != encoded:
        raise PublicationFreezeBlocked("existing publication freeze conflicts")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = seal(args.project, args.config, args.output)
    except (PublicationFreezeBlocked, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "message": str(exc), "model_calls": 0}))
        return 4
    print(
        json.dumps(
            {
                "status": "sealed",
                "freeze_manifest_digest": result["freeze_manifest_digest"],
                "model_calls": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
