from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agentloopgate.contracts import canonical_digest
from agentloopgate.experiment.ledger import ExperimentAttemptEvent


def _module(name: str):
    path = Path(__file__).parents[2] / f"scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _module("build_public_r2_package")
verifier = _module("verify_public_r2_package")


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


def test_freeze_identity_selects_the_experiment_specific_ledger(
    tmp_path: Path,
) -> None:
    freeze_payload = {
        "schema_version": "1.0",
        "experiment_id": "EXP_BANKING_R11",
        "source_revision": "tree:sha256:" + "1" * 64,
        "execution_protocol": {"digest": "sha256:" + "2" * 64},
        "study": {"digest": "sha256:" + "3" * 64},
        "evaluation_baseline": {"snapshot_id": "R11_A2"},
    }
    freeze_path = tmp_path / "r11-freeze.json"
    freeze_path.write_text(
        json.dumps(
            {
                **freeze_payload,
                "freeze_manifest_digest": canonical_digest(freeze_payload),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(builder.PublicPackageBlocked, match="outcome is unavailable"):
        builder.build_public_release(
            tmp_path,
            config=Path("missing-r11.yaml"),
            freeze_path=freeze_path,
            output=Path("artifacts/r11-release"),
        )

    assert not (tmp_path / "artifacts/r11-release").exists()
    r11_events = sorted(
        (tmp_path / "runs/experiments/EXP_BANKING_R11/attempt_ledger").glob(
            "ATT_*/*.json"
        )
    )
    assert len(r11_events) == 2
    assert not (tmp_path / "runs/experiments/EXP_BANKING_R2").exists()


def test_registered_pre_core_ablation_paths_preserve_frozen_identity(
    tmp_path: Path,
) -> None:
    paths = builder._ablation_paths(
        tmp_path,
        tmp_path / "artifacts/research/banking_r2",
        {
            "pre_core_ablations": {
                "evidence_integrity_gate": {
                    "path": "artifacts/research/banking_r2/ablations/integrity_gate_a4.json"
                },
                "plugin_trace_coexistence_and_overhead": {
                    "path": (
                        "artifacts/research/banking_r2/ablations/"
                        "plugin_coexistence_overhead_a4.json"
                    )
                },
            }
        },
    )

    assert paths["integrity_gate"] == (
        tmp_path / "artifacts/research/banking_r2/ablations/integrity_gate_a4.json"
    )
    assert paths["plugin_coexistence_overhead"] == (
        tmp_path
        / "artifacts/research/banking_r2/ablations/plugin_coexistence_overhead_a4.json"
    )


def test_independent_verifier_accepts_selection_hold_package(tmp_path: Path) -> None:
    selection = _artifact(
        {"schema_version": "1.0", "selection": {"agentloopgate_decision": "HOLD"}},
        "selection_digest",
    )
    outcome_payload = {
        "schema_version": "1.0",
        "outcome_kind": "selection_hold",
        "experiment_id": "EXP_BANKING_R11",
        "baseline_snapshot_id": "R11_A2",
        "final_decision": "HOLD",
        "release_batch_count": 0,
        "model_calls_after_selection": 0,
        "lineage_digest": "sha256:" + "1" * 64,
        "selection_digest": selection["selection_digest"],
        "report_digest": "sha256:" + "2" * 64,
    }
    outcome = _artifact(outcome_payload, "outcome_digest")
    ablation = {
        name: _artifact({"schema_version": "1.0", "ablation_id": name}, "artifact_digest")
        for name in ("integrity_gate", "plugin_coexistence_overhead")
    }
    payloads = {
        "selection_hold_outcome.json": builder.canonical_json_bytes(outcome) + b"\n",
        "selection.json": builder.canonical_json_bytes(selection) + b"\n",
        "lineage_summary.json": json.dumps(
            {"private_lineage_digest": outcome["lineage_digest"]}
        ).encode(),
        "failure_accounting.json": json.dumps(
            {"unresolved_attempt_count": 0, "model_usage": {"unresolved_call_count": 0}}
        ).encode(),
        "cost_summary.json": json.dumps(
            {"local_compute_monetary_cost_status": "unmetered_unknown"}
        ).encode(),
        "reproduction.json": b"{}\n",
        "ablations/integrity_gate.json": builder.canonical_json_bytes(
            ablation["integrity_gate"]
        )
        + b"\n",
        "ablations/plugin_coexistence_overhead.json": builder.canonical_json_bytes(
            ablation["plugin_coexistence_overhead"]
        )
        + b"\n",
        "reports/selection_hold.json": b"{}\n",
        "reports/selection_hold.md": b"# HOLD\n",
    }
    payloads["README.md"] = (
        f"# HOLD\n\nOutcome: `{outcome['outcome_digest']}`\n"
    ).encode()
    derivations = {path: "unit fixture" for path in payloads}
    metadata = {
        **_metadata(),
        "experiment_id": "EXP_BANKING_R11",
        "terminal_kind": "selection_hold",
        "private_outcome_digest": outcome["outcome_digest"],
        "baseline_snapshot_id": "R11_A2",
        "final_decision": "HOLD",
        "lineage_digest": outcome["lineage_digest"],
        "selection_digest": selection["selection_digest"],
        "report_digest": outcome["report_digest"],
    }
    output = tmp_path / "selection-hold"
    builder._seal_payloads(output, payloads=payloads, derivations=derivations, metadata=metadata)

    verified = verifier.verify_public_release(output)
    assert verified["status"] == "verified"
    assert verified["experiment_id"] == "EXP_BANKING_R11"


def _artifact(payload: dict[str, object], digest_field: str) -> dict[str, object]:
    return {**payload, digest_field: canonical_digest(payload)}


def test_independent_public_verifier_accepts_and_detects_tampering(
    tmp_path: Path,
) -> None:
    roles = _artifact(
        {"schema_version": "1.0", "role_alias": False},
        "role_assignment_digest",
    )
    statistics = _artifact(
        {
            "schema_version": "1.0",
            "comparisons": [{"comparison_id": str(index)} for index in range(6)],
        },
        "statistics_digest",
    )
    ablations = {
        name: _artifact(
            {"schema_version": "1.0", "ablation_id": name}, "artifact_digest"
        )
        for name in (
            "selector",
            "diagnosis_direction",
            "integrity_gate",
            "plugin_coexistence_overhead",
        )
    }
    decisions = {
        selector: _artifact(
            {
                "schema_version": "1.0",
                "selector": selector,
                "outcome": {"record": {"decision": "HOLD"}},
            },
            "decision_digest",
        )
        for selector in ("native", "agentloopgate")
    }
    outcome = _artifact(
        {
            "schema_version": "1.1",
            "experiment_id": "EXP_BANKING_R2",
            "baseline_snapshot_id": "R2_A4",
            "native_decision": "HOLD",
            "final_decision": "HOLD",
            "logical_core_trial_count": 560,
            "unique_executed_core_trial_count": 560,
            "reused_role_trial_count": 0,
            "lineage_digest": "sha256:" + "1" * 64,
            "role_assignment_digest": roles["role_assignment_digest"],
            "statistics_digest": statistics["statistics_digest"],
            "selector_ablation_digest": ablations["selector"]["artifact_digest"],
            "diagnosis_ablation_digest": ablations["diagnosis_direction"][
                "artifact_digest"
            ],
            "report_digest": "sha256:" + "2" * 64,
        },
        "outcome_digest",
    )
    payloads: dict[str, bytes] = {
        "README.md": (
            f"# Fixture\n\nOutcome: `{outcome['outcome_digest']}`\n"
        ).encode(),
        "outcome.json": builder.canonical_json_bytes(outcome) + b"\n",
        "role_assignment.json": builder.canonical_json_bytes(roles) + b"\n",
        "statistics.json": builder.canonical_json_bytes(statistics) + b"\n",
        "lineage_summary.json": json.dumps(
            {"private_lineage_digest": outcome["lineage_digest"]}
        ).encode(),
        "failure_accounting.json": json.dumps(
            {
                "unresolved_attempt_count": 0,
                "model_usage": {"unresolved_call_count": 0},
            }
        ).encode(),
        "cost_summary.json": json.dumps(
            {
                "all_batches_exact": True,
                "exact_total_usd": "1.00",
                "local_compute_monetary_cost_status": "unmetered_unknown",
                "github_actions_compute_monetary_cost_status": (
                    "unavailable_unknown"
                ),
            }
        ).encode(),
        "reproduction.json": b"{}\n",
    }
    for selector, decision in decisions.items():
        payloads[f"decisions/{selector}.json"] = (
            builder.canonical_json_bytes(decision) + b"\n"
        )
    for name, artifact in ablations.items():
        payloads[f"ablations/{name}.json"] = (
            builder.canonical_json_bytes(artifact) + b"\n"
        )
    for report in (
        "decision.json",
        "decision.md",
        "01_candidate_curve.svg",
        "02_failure_funnel.svg",
        "03_pool_comparison.svg",
        "04_gate_waterfall.svg",
    ):
        payloads[f"reports/{report}"] = f"fixture {report}\n".encode()
    derivations = {path: "unit fixture" for path in payloads}
    metadata = {
        **_metadata(),
        "private_outcome_digest": outcome["outcome_digest"],
        "baseline_snapshot_id": outcome["baseline_snapshot_id"],
        "native_decision": outcome["native_decision"],
        "final_decision": outcome["final_decision"],
        "logical_core_trial_count": outcome["logical_core_trial_count"],
        "unique_executed_core_trial_count": outcome[
            "unique_executed_core_trial_count"
        ],
        "reused_role_trial_count": outcome["reused_role_trial_count"],
        "lineage_digest": outcome["lineage_digest"],
        "statistics_digest": outcome["statistics_digest"],
        "report_digest": outcome["report_digest"],
    }
    output = tmp_path / "release"
    builder._seal_payloads(
        output, payloads=payloads, derivations=derivations, metadata=metadata
    )

    result = verifier.verify_public_release(output)
    assert result["status"] == "verified"
    assert result["file_count"] == 21

    (output / "reports/decision.md").write_text("tampered\n")
    with pytest.raises(verifier.PublicPackageVerificationError, match="hash mismatch"):
        verifier.verify_public_release(output)
