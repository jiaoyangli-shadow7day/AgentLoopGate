#!/usr/bin/env python3
"""Verify a sanitized formal-result package without private experiment data."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from agentloopgate.contracts import canonical_digest, file_digest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_public_tree import ALLOWED_EMAILS, PII_RULES, SECRET_RULES  # noqa: E402

REQUIRED_FILES = {
    "README.md",
    "outcome.json",
    "lineage_summary.json",
    "role_assignment.json",
    "statistics.json",
    "failure_accounting.json",
    "cost_summary.json",
    "reproduction.json",
    "decisions/native.json",
    "decisions/agentloopgate.json",
    "ablations/selector.json",
    "ablations/diagnosis_direction.json",
    "ablations/integrity_gate.json",
    "ablations/plugin_coexistence_overhead.json",
    "reports/decision.json",
    "reports/decision.md",
    "reports/01_candidate_curve.svg",
    "reports/02_failure_funnel.svg",
    "reports/03_pool_comparison.svg",
    "reports/04_gate_waterfall.svg",
}


class PublicPackageVerificationError(ValueError):
    """The public package is incomplete, unsafe, or internally inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicPackageVerificationError(f"cannot read package JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise PublicPackageVerificationError(f"package JSON is not an object: {path.name}")
    return value


def _safe_relative(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise PublicPackageVerificationError("Manifest contains an unsafe file path")


def _semantic_digest(
    value: dict[str, Any], field: str, *, expected: str | None = None
) -> str:
    digest = value.get(field)
    if not isinstance(digest, str):
        raise PublicPackageVerificationError(f"package artifact has no {field}")
    payload = dict(value)
    payload.pop(field)
    if canonical_digest(payload) != digest:
        raise PublicPackageVerificationError(f"package artifact {field} is invalid")
    if expected is not None and digest != expected:
        raise PublicPackageVerificationError(f"package artifact {field} conflicts")
    return digest


def _scan(files: dict[str, bytes]) -> dict[str, Any]:
    findings: Counter[str] = Counter()
    for data in files.values():
        if b"\0" in data:
            findings["binary_payload"] += 1
            continue
        for name, pattern in SECRET_RULES.items():
            findings[name] += len(pattern.findall(data))
        for name, pattern in PII_RULES.items():
            matches = pattern.findall(data)
            if name == "email_address":
                matches = [match for match in matches if match.lower() not in ALLOWED_EMAILS]
            findings[name] += len(matches)
    nonzero = {name: count for name, count in sorted(findings.items()) if count}
    if nonzero:
        raise PublicPackageVerificationError(
            "package failed Secret/direct-PII verification: "
            + ", ".join(f"{name}={count}" for name, count in nonzero.items())
        )
    return {
        "status": "passed",
        "files_scanned": len(files),
        "secret_rule_count": len(SECRET_RULES),
        "pii_rule_count": len(PII_RULES),
        "finding_counts": {},
    }


def verify_public_release(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    if directory.is_symlink() or not directory.is_dir():
        raise PublicPackageVerificationError("public package directory is unavailable")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise PublicPackageVerificationError("Manifest cannot be a symlink")
    manifest = _load_json(manifest_path)
    manifest_digest = _semantic_digest(manifest, "manifest_digest")
    if manifest.get("package_kind") != "sanitized_derived_view":
        raise PublicPackageVerificationError("unexpected public package kind")
    if manifest.get("publication_authorized") is not False:
        raise PublicPackageVerificationError(
            "package must not claim publication authorization"
        )
    if manifest.get("scientific_protocol_deviations") != []:
        raise PublicPackageVerificationError("package reports a scientific deviation")

    declared = manifest.get("files")
    if not isinstance(declared, list):
        raise PublicPackageVerificationError("Manifest file inventory is unavailable")
    entries: dict[str, dict[str, Any]] = {}
    for raw in declared:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise PublicPackageVerificationError("Manifest file entry is invalid")
        relative = raw["path"]
        _safe_relative(relative)
        if relative in entries:
            raise PublicPackageVerificationError("Manifest contains a duplicate path")
        entries[relative] = raw
    if set(entries) != REQUIRED_FILES:
        missing = sorted(REQUIRED_FILES - set(entries))
        extra = sorted(set(entries) - REQUIRED_FILES)
        raise PublicPackageVerificationError(
            f"package file contract mismatch: missing={missing}, extra={extra}"
        )

    actual_paths: dict[str, Path] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise PublicPackageVerificationError("package cannot contain symlinks")
        if path.is_file() and path != manifest_path:
            actual_paths[path.relative_to(directory).as_posix()] = path
    if set(actual_paths) != set(entries):
        raise PublicPackageVerificationError("package files differ from Manifest inventory")

    raw_files: dict[str, bytes] = {}
    for relative, path in actual_paths.items():
        entry = entries[relative]
        if entry.get("sha256") != file_digest(path):
            raise PublicPackageVerificationError(f"package file hash mismatch: {relative}")
        if entry.get("privacy_classification") != "sanitized_aggregate":
            raise PublicPackageVerificationError(
                f"package privacy classification mismatch: {relative}"
            )
        if not isinstance(entry.get("derivation"), str) or not entry["derivation"]:
            raise PublicPackageVerificationError(
                f"package derivation is missing: {relative}"
            )
        raw_files[relative] = path.read_bytes()
    scan = _scan(raw_files)

    outcome = _load_json(directory / "outcome.json")
    outcome_digest = _semantic_digest(
        outcome, "outcome_digest", expected=manifest.get("private_outcome_digest")
    )
    if outcome.get("experiment_id") != manifest.get("experiment_id"):
        raise PublicPackageVerificationError("Outcome experiment identity conflicts")
    if outcome.get("baseline_snapshot_id") != manifest.get("baseline_snapshot_id"):
        raise PublicPackageVerificationError("Outcome baseline identity conflicts")
    for field in (
        "logical_core_trial_count",
        "unique_executed_core_trial_count",
        "reused_role_trial_count",
        "lineage_digest",
        "statistics_digest",
        "report_digest",
    ):
        if outcome.get(field) != manifest.get(field):
            raise PublicPackageVerificationError(f"Outcome {field} conflicts")
    if outcome.get("native_decision") != manifest.get("native_decision"):
        raise PublicPackageVerificationError("native Decision conflicts")
    if outcome.get("final_decision") != manifest.get("final_decision"):
        raise PublicPackageVerificationError("governed Decision conflicts")

    roles = _load_json(directory / "role_assignment.json")
    _semantic_digest(
        roles,
        "role_assignment_digest",
        expected=outcome.get("role_assignment_digest"),
    )
    statistics = _load_json(directory / "statistics.json")
    _semantic_digest(
        statistics,
        "statistics_digest",
        expected=outcome.get("statistics_digest"),
    )
    if len(statistics.get("comparisons", [])) != 6:
        raise PublicPackageVerificationError(
            "publication statistics must contain six comparisons"
        )

    decisions: dict[str, dict[str, Any]] = {}
    for selector in ("native", "agentloopgate"):
        decision = _load_json(directory / "decisions" / f"{selector}.json")
        _semantic_digest(decision, "decision_digest")
        decisions[selector] = decision
    native_value = _decision_value(decisions["native"])
    governed_value = _decision_value(decisions["agentloopgate"])
    if native_value != outcome.get("native_decision"):
        raise PublicPackageVerificationError("native Decision value conflicts")
    if governed_value != outcome.get("final_decision"):
        raise PublicPackageVerificationError("governed Decision value conflicts")

    expected_ablations = {
        "selector": outcome.get("selector_ablation_digest"),
        "diagnosis_direction": outcome.get("diagnosis_ablation_digest"),
        "integrity_gate": None,
        "plugin_coexistence_overhead": None,
    }
    for name, expected in expected_ablations.items():
        artifact = _load_json(directory / "ablations" / f"{name}.json")
        _semantic_digest(artifact, "artifact_digest", expected=expected)

    lineage = _load_json(directory / "lineage_summary.json")
    if lineage.get("private_lineage_digest") != outcome.get("lineage_digest"):
        raise PublicPackageVerificationError("Lineage summary conflicts")

    failure = _load_json(directory / "failure_accounting.json")
    unresolved_attempts = failure.get("unresolved_attempt_count")
    model_usage = failure.get("model_usage")
    if unresolved_attempts != 0 or not isinstance(model_usage, dict):
        raise PublicPackageVerificationError("Attempt accounting is incomplete")
    unresolved_calls = model_usage.get("unresolved_call_count")
    if unresolved_calls and outcome.get("final_decision") != "HOLD":
        raise PublicPackageVerificationError(
            "unresolved model calls require final HOLD"
        )

    costs = _load_json(directory / "cost_summary.json")
    if costs.get("local_compute_monetary_cost_status") != "unmetered_unknown":
        raise PublicPackageVerificationError("local compute cost status is invalid")
    if (
        costs.get("github_actions_compute_monetary_cost_status")
        != "unavailable_unknown"
    ):
        raise PublicPackageVerificationError("GitHub Actions cost status is invalid")
    if costs.get("all_batches_exact") is True and costs.get("exact_total_usd") is None:
        raise PublicPackageVerificationError("exact batch costs require exact total")
    if costs.get("all_batches_exact") is False and costs.get("exact_total_usd") is not None:
        raise PublicPackageVerificationError("partial batch costs cannot claim exact total")

    readme = (directory / "README.md").read_text(encoding="utf-8")
    if outcome_digest not in readme:
        raise PublicPackageVerificationError("README does not bind private Outcome")
    if manifest_digest in readme:
        raise PublicPackageVerificationError("README creates a Manifest digest cycle")

    return {
        "status": "verified",
        "experiment_id": manifest.get("experiment_id"),
        "manifest_digest": manifest_digest,
        "private_outcome_digest": outcome_digest,
        "file_count": len(entries) + 1,
        "secret_pii_scan": scan,
        "publication_authorized": False,
    }


def _decision_value(decision: dict[str, Any]) -> Any:
    try:
        return decision["outcome"]["record"]["decision"]
    except (KeyError, TypeError) as exc:
        raise PublicPackageVerificationError("Decision value is unavailable") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package", type=Path, default=Path("artifacts/research/banking_r2/release")
    )
    args = parser.parse_args()
    try:
        result = verify_public_release(args.package)
    except PublicPackageVerificationError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 5
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
