#!/usr/bin/env python3
"""Verify the repository is a safe publication candidate without publishing it."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_public_r2_package import verify_public_release  # noqa: E402

REQUIRED_COMMUNITY_FILES = {
    "README.md",
    "SPEC.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CITATION.cff",
    "CHANGELOG.md",
}
REQUIRED_RESEARCH_FILES = {
    "docs/open-source-release.md",
    "docs/paper/english-reader-review.md",
    "docs/release-readiness.md",
    "docs/publication-runbook.md",
    "docs/research/banking-r15-results.md",
    "docs/research/public-result-package.md",
    "artifacts/research/banking_r15/pre_run_preregistration.json",
    "artifacts/research/banking_r15/ablations/integrity_gate.json",
    "artifacts/research/banking_r15/ablations/plugin_coexistence_overhead.json",
    "output/pdf/agentloopgate-evidence-governed-evolution.pdf",
    "output/pdf/agentloopgate-evidence-governed-evolution-zh.pdf",
    "paper/agentloopgate-arxiv/main.tex",
}
DISALLOWED_TRACKED_ROOTS = {"runs", "snapshots", "candidates", "reports"}
EXPECTED_MANIFEST = "sha256:79e9a8dd31009f969cdd79021bbcc857c827dc1d5a6808a28fd05937e4f364c8"


class PublicationCandidateError(ValueError):
    """The current tree cannot safely be submitted for publication approval."""


def verify_publication_candidate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    missing = sorted(
        relative
        for relative in REQUIRED_COMMUNITY_FILES | REQUIRED_RESEARCH_FILES
        if not (root / relative).is_file()
    )
    if missing:
        raise PublicationCandidateError(f"required publication files missing: {missing}")

    package = verify_public_release(root / "artifacts/research/banking_r15/release_v2")
    if package["manifest_digest"] != EXPECTED_MANIFEST:
        raise PublicationCandidateError("R15 v1.1 package manifest is not the frozen candidate")
    if package["publication_authorized"] is not False:
        raise PublicationCandidateError("result package claims publication authorization")

    tracked = _git_lines(root, "ls-files")
    disallowed = sorted(path for path in tracked if Path(path).parts[0] in DISALLOWED_TRACKED_ROOTS)
    if disallowed:
        raise PublicationCandidateError(
            f"private runtime-evidence root is tracked: {disallowed[:5]}"
        )

    readme = (root / "README.md").read_text(encoding="utf-8")
    results = (root / "docs/research/banking-r15-results.md").read_text(encoding="utf-8")
    runbook = (root / "docs/publication-runbook.md").read_text(encoding="utf-8")
    for label, text, needles in (
        (
            "README",
            readme,
            ("EXP_BANKING_R15", "release_v2", "publication_authorized"),
        ),
        (
            "R15 results",
            results,
            (EXPECTED_MANIFEST, "3.9086647880000000116", "Release was not run"),
        ),
        (
            "publication runbook",
            runbook,
            ("Owner", "PRIVATE", "GitHub Release", "Promote"),
        ),
    ):
        absent = [needle for needle in needles if needle not in text]
        if absent:
            raise PublicationCandidateError(f"{label} omits required disclosure: {absent}")

    return {
        "schema_version": "1.0",
        "status": "ready_for_owner_publication_review",
        "publication_authorized": False,
        "publication_action_performed": False,
        "owner_action_required": True,
        "repository_visibility_check": "external_required_at_authorization",
        "git_revision": _git_lines(root, "rev-parse", "HEAD")[0],
        "experiment_id": package["experiment_id"],
        "private_outcome_digest": package["private_outcome_digest"],
        "public_package_manifest_digest": package["manifest_digest"],
        "public_package_file_count": package["file_count"],
        "secret_pii_scan": package["secret_pii_scan"],
        "tracked_private_runtime_root_count": 0,
        "remaining_blockers": ["owner_publication_authorization"],
    }


def _git_lines(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise PublicationCandidateError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return [line for line in completed.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        result = verify_publication_candidate(args.project)
    except PublicationCandidateError as exc:
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
