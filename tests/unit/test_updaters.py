from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from agentloopgate.candidates import CandidateRegistry
from agentloopgate.contracts import file_digest
from agentloopgate.mutation import CandidateChecker, freeze_trust_kernel
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    append_model_call_event,
    make_model_call_event,
)
from agentloopgate.schemas import CandidateStatus, FailureBundle, SnapshotManifest
from agentloopgate.updaters import (
    AHE_COMMIT,
    AheAdapter,
    AheExternalRunner,
    AheRunOutput,
    AheRunRequest,
    AheSandbox,
    HarnessAssetManifest,
    MutationPolicy,
    UpdaterAdapter,
    UpdaterHealth,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def test_ahe_usage_accounting_never_turns_unknown_cost_into_zero(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ahe_model_usage.jsonl"
    for state, call_id, status, cost in (
        (AttemptState.STARTED, "MC_KNOWN", CostStatus.PENDING, None),
        (AttemptState.COMPLETED, "MC_KNOWN", CostStatus.EXACT, Decimal("0.002")),
        (AttemptState.STARTED, "MC_UNKNOWN", CostStatus.PENDING, None),
        (AttemptState.FAILED, "MC_UNKNOWN", CostStatus.UNAVAILABLE, None),
    ):
        append_model_call_event(
            path,
            make_model_call_event(
                call_id=call_id,
                state=state,
                session_id_hash=DIGEST_A,
                model="deepseek-v4-flash",
                input_tokens=10 if cost is not None else None,
                cache_read_tokens=2 if cost is not None else None,
                output_tokens=3 if cost is not None else None,
                cost_usd=cost,
                cost_status=status,
                error_type="FixtureError" if state is AttemptState.FAILED else None,
            ),
        )

    accounting = AheExternalRunner._usage_accounting(path)

    assert accounting[:5] == (10, 2, 3, 2, 0)
    assert accounting[5] is CostStatus.PARTIAL
    assert accounting[6] == Decimal("0.002")


def asset_manifest() -> HarnessAssetManifest:
    return HarnessAssetManifest.model_validate(
        {
            "schema_version": "1.0",
            "assets": [
                {
                    "asset_id": "prompt",
                    "family": "prompt_instruction",
                    "path_patterns": ["harness/system_prompt.md"],
                    "risk_tier": "L",
                    "allowed_operations": ["propose", "patch", "evaluate", "rollback"],
                    "rollback_unit": "prompt-unit",
                }
            ],
        }
    )


def mutation_policy() -> MutationPolicy:
    return MutationPolicy.model_validate(
        {
            "schema_version": "1.0",
            "max_files": 4,
            "max_changed_lines": 160,
            "auto_executable_risks": ["L", "M"],
            "hold_risks": ["H"],
            "protected_paths": ["SPEC.md", "configs/**", "agentloopgate/**"],
            "trust_kernel_paths": ["SPEC.md"],
            "forbidden_content_patterns": [
                "(?i)required_documents",
                "(?i)gold(en)?",
                "sk-[A-Za-z0-9]{20,}",
            ],
        }
    )


def failure_bundle() -> FailureBundle:
    return FailureBundle.model_validate(
        {
            "schema_version": "1.0",
            "failure_bundle_id": "FB_001",
            "snapshot_id": "S_A0",
            "source_pool": "update_source",
            "failure_type": "policy_application_error",
            "affected_run_ids": ["R_001"],
            "evidence_refs": ["runs/diagnostics/R_001.json"],
            "redacted_summary": "A prerequisite was missed.",
            "target_asset_families": ["prompt_instruction"],
            "expected_behavior_change": "Check prerequisites before acting.",
            "must_not_change": ["objective", "grader", "split", "final_access"],
            "budget": {"max_files": 4, "max_changed_lines": 160},
        }
    )


def project(root: Path) -> SnapshotManifest:
    (root / "harness").mkdir(parents=True)
    prompt = root / "harness/system_prompt.md"
    prompt.write_text("old\n", encoding="utf-8")
    (root / "SPEC.md").write_text("spec\n", encoding="utf-8")
    snapshot = SnapshotManifest.model_validate(
        {
            "schema_version": "1.0",
            "snapshot_id": "S_A0",
            "parent_snapshot_id": None,
            "candidate_id": None,
            "model_id": "deepseek-chat",
            "objective_digest": DIGEST_A,
            "split_digest": DIGEST_B,
            "asset_manifest_digest": DIGEST_C,
            "code_revision": "fixture",
            "harness_files": {"harness/system_prompt.md": file_digest(prompt)},
            "runtime": {"host": "python_cli", "version": "fixture"},
            "created_at": "2026-08-20T00:00:00Z",
        }
    )
    frozen = root / "snapshots/S_A0/files/harness/system_prompt.md"
    frozen.parent.mkdir(parents=True)
    frozen.write_text("old\n", encoding="utf-8")
    return snapshot


class FakeAheRunner:
    def __init__(self) -> None:
        self.calls = 0

    def doctor(self) -> UpdaterHealth:
        return UpdaterHealth(
            status="ready",
            name="ahe",
            expected_commit=AHE_COMMIT,
            actual_commit=AHE_COMMIT,
            version="0.1.0",
            credentials_configured=True,
            sandbox_available=True,
            remediation="No action required.",
        )

    def run(self, request: AheRunRequest) -> AheRunOutput:
        self.calls += 1
        assert request.allowed_paths == ["harness/system_prompt.md"]
        assert "R_001" in request.query
        assert "required_documents" not in request.query
        prompt = request.experiment_root / "workspace/harness/system_prompt.md"
        prompt.write_text("old\ncheck prerequisites\n", encoding="utf-8")
        evolve = request.experiment_root / "runs/iteration_001/evolve"
        evolve.mkdir(parents=True, exist_ok=True)
        trace = evolve / "evolve_trace.json"
        trace.write_text("[]\n", encoding="utf-8")
        summary = evolve / "evolve_summary.md"
        summary.write_text("one targeted change\n", encoding="utf-8")
        return AheRunOutput(
            exit_code=0,
            stdout="completed",
            stderr="",
            trace_path=trace,
            summary_path=summary,
            input_tokens=25,
            output_tokens=10,
            cost="0.002",
        )


def test_ahe_adapter_stages_only_allowlisted_assets_and_registers_diff(tmp_path: Path) -> None:
    snapshot = project(tmp_path)
    policy = mutation_policy()
    checker = CandidateChecker(
        tmp_path,
        asset_manifest(),
        policy,
        freeze_trust_kernel(tmp_path, policy),
    )
    registry = CandidateRegistry(tmp_path, checker)
    adapter = AheAdapter(tmp_path, registry=registry, runner=FakeAheRunner())

    assert isinstance(adapter, UpdaterAdapter)
    records = adapter.propose(
        parent_snapshot=snapshot,
        failure_bundle=failure_bundle(),
        asset_manifest=asset_manifest(),
        mutation_policy=policy,
        count=1,
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert len(records) == 1
    record = records[0]
    assert record.status is CandidateStatus.CHECKED
    assert record.updater.name == "ahe"
    assert AHE_COMMIT in record.updater.version
    assert record.changed_files == ["harness/system_prompt.md"]
    assert (tmp_path / record.patch_path).is_file()
    raw_dir = tmp_path / f"runs/updaters/ahe/{record.candidate_id}"
    assert (raw_dir / "evolve_trace.json").is_file()
    assert (raw_dir / "run_metadata.json").is_file()

    repeated = adapter.propose(
        parent_snapshot=snapshot,
        failure_bundle=failure_bundle(),
        asset_manifest=asset_manifest(),
        mutation_policy=policy,
        count=1,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert repeated[0] == record


def test_ahe_preserves_real_candidate_check_rejection_and_resumes(
    tmp_path: Path,
) -> None:
    snapshot = project(tmp_path)
    policy = mutation_policy()
    checker = CandidateChecker(
        tmp_path,
        asset_manifest(),
        policy,
        freeze_trust_kernel(tmp_path, policy),
    )
    registry = CandidateRegistry(tmp_path, checker)
    runner = FakeAheRunner()
    adapter = AheAdapter(tmp_path, registry=registry, runner=runner)

    original_run = runner.run

    def rejected_run(request: AheRunRequest) -> AheRunOutput:
        output = original_run(request)
        prompt = request.experiment_root / "workspace/harness/system_prompt.md"
        prompt.write_text("old\nrequired_documents are gold\n", encoding="utf-8")
        return output

    runner.run = rejected_run  # type: ignore[method-assign]
    first = adapter.propose(
        parent_snapshot=snapshot,
        failure_bundle=failure_bundle(),
        asset_manifest=asset_manifest(),
        mutation_policy=policy,
        count=1,
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    second = adapter.propose(
        parent_snapshot=snapshot,
        failure_bundle=failure_bundle(),
        asset_manifest=asset_manifest(),
        mutation_policy=policy,
        count=1,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    assert first == second == []
    assert runner.calls == 1
    rejection = next((tmp_path / "runs/updaters/ahe/rejected").glob("*/rejection.json"))
    assert "REJECT_LEAKAGE" in rejection.read_text(encoding="utf-8")


@pytest.mark.skipif(not Path("/usr/bin/sandbox-exec").is_file(), reason="macOS only")
def test_ahe_sandbox_allows_staging_writes_and_denies_outside(tmp_path: Path) -> None:
    staging = (tmp_path / "staging").resolve()
    staging.mkdir()
    protected = (tmp_path / "project").resolve()
    protected.mkdir()
    private = protected / "selection.json"
    private.write_text("held out\n", encoding="utf-8")
    runtime = protected / ".cache/ahe"
    runtime.mkdir(parents=True)
    dependency = runtime / "pyproject.toml"
    dependency.write_text("runtime\n", encoding="utf-8")
    denied = (tmp_path / "outside.txt").resolve()
    profile = AheSandbox(
        staging,
        protected_root=protected,
        runtime_roots=(runtime,),
    ).profile()

    allowed_run = subprocess.run(
        ["sandbox-exec", "-p", profile, "/usr/bin/touch", str(staging / "allowed.txt")],
        capture_output=True,
        text=True,
    )
    denied_run = subprocess.run(
        ["sandbox-exec", "-p", profile, "/usr/bin/touch", str(denied)],
        capture_output=True,
        text=True,
    )
    denied_read = subprocess.run(
        ["sandbox-exec", "-p", profile, "/usr/bin/head", "-c", "1", str(private)],
        capture_output=True,
        text=True,
    )
    allowed_runtime_read = subprocess.run(
        [
            "sandbox-exec",
            "-p",
            profile,
            "/usr/bin/head",
            "-c",
            "1",
            str(dependency),
        ],
        capture_output=True,
        text=True,
    )

    assert allowed_run.returncode == 0
    assert denied_run.returncode != 0
    assert denied_read.returncode != 0
    assert allowed_runtime_read.returncode == 0
    assert not denied.exists()
