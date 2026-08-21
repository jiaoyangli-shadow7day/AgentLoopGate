from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agentloopgate.contracts import canonical_digest
from agentloopgate.experiment.ledger import ExperimentAttemptEvent


def _module():
    path = Path(__file__).parents[2] / "scripts/build_public_r2_package.py"
    spec = importlib.util.spec_from_file_location("build_public_r2_package", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _module()


def _metadata() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "package_kind": "sanitized_derived_view",
        "experiment_id": "EXP_BANKING_R2",
        "private_outcome_digest": "sha256:" + "a" * 64,
        "scientific_protocol_deviations": [],
        "publication_authorized": False,
    }


def test_sealed_package_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    payloads = {
        "README.md": b"# Safe aggregate\n",
        "outcome.json": b'{"decision":"HOLD"}\n',
    }
    derivations = {path: "unit fixture" for path in payloads}
    output = tmp_path / "release"

    first, reused = builder._seal_payloads(
        output, payloads=payloads, derivations=derivations, metadata=_metadata()
    )
    second, second_reused = builder._seal_payloads(
        output, payloads=payloads, derivations=derivations, metadata=_metadata()
    )

    assert not reused
    assert second_reused
    assert first == second
    manifest = json.loads((output / "manifest.json").read_text())
    digest = manifest.pop("manifest_digest")
    assert digest == canonical_digest(manifest)
    assert {item["path"] for item in manifest["files"]} == set(payloads)
    assert manifest["publication_authorized"] is False


def test_existing_package_conflict_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "release"
    payloads = {"README.md": b"first\n"}
    derivations = {"README.md": "unit fixture"}
    builder._seal_payloads(
        output, payloads=payloads, derivations=derivations, metadata=_metadata()
    )

    with pytest.raises(builder.PublicPackageConflict):
        builder._seal_payloads(
            output,
            payloads={"README.md": b"different\n"},
            derivations=derivations,
            metadata=_metadata(),
        )
    assert (output / "README.md").read_bytes() == b"first\n"


def test_secret_pattern_blocks_package_before_output(tmp_path: Path) -> None:
    output = tmp_path / "release"
    with pytest.raises(builder.SensitiveContentError):
        builder._seal_payloads(
            output,
            payloads={"unsafe.json": b'{"value":"' + b"sk-" + b"A" * 22 + b'"}\n'},
            derivations={"unsafe.json": "unit fixture"},
            metadata=_metadata(),
        )
    assert not output.exists()


def test_direct_pii_pattern_blocks_package_before_output(tmp_path: Path) -> None:
    output = tmp_path / "release"
    private_path = b"/" + b"Users" + b"/person/project"
    with pytest.raises(builder.SensitiveContentError):
        builder._seal_payloads(
            output,
            payloads={"unsafe.json": b'{"path":"' + private_path + b'"}\n'},
            derivations={"unsafe.json": "unit fixture"},
            metadata=_metadata(),
        )
    assert not output.exists()


def test_missing_outcome_records_failed_attempt_without_creating_package(
    tmp_path: Path,
) -> None:
    freeze_payload = {
        "schema_version": "1.0",
        "experiment_id": "EXP_BANKING_R2",
        "source_revision": "tree:sha256:" + "1" * 64,
        "execution_protocol": {"digest": "sha256:" + "2" * 64},
        "study": {"digest": "sha256:" + "3" * 64},
        "evaluation_baseline": {"snapshot_id": "R2_A4"},
    }
    freeze = {
        **freeze_payload,
        "freeze_manifest_digest": canonical_digest(freeze_payload),
    }
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")

    with pytest.raises(
        builder.PublicPackageBlocked, match="outcome is unavailable"
    ) as captured:
        builder.build_public_release(
            tmp_path,
            config=Path("missing.yaml"),
            freeze_path=freeze_path,
            output=Path("artifacts/release"),
        )

    assert not (tmp_path / "artifacts/release").exists()
    event_paths = sorted(
        (
            tmp_path
            / "runs/experiments/EXP_BANKING_R2/attempt_ledger"
        ).glob("ATT_*/*.json")
    )
    events = [
        ExperimentAttemptEvent.model_validate_json(path.read_text())
        for path in event_paths
    ]
    events.sort(key=lambda event: event.recorded_at)
    assert [event.state.value for event in events] == ["started", "failed"]
    assert len({event.attempt_id for event in events}) == 1
    assert captured.value.attempt_id == events[-1].attempt_id
    assert events[-1].cost_status.value == "not_applicable"
    assert events[-1].known_cost_usd == 0
    assert events[-1].exit_code == 4
