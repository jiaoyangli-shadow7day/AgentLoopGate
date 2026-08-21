#!/usr/bin/env python3
"""Fail closed on secret and direct-PII patterns in Git-public files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

SECRET_RULES = {
    "provider_secret": re.compile(rb"(?i)\bsk-[A-Za-z0-9]{20,}\b"),
    "credential_assignment": re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key)"
        rb"\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"
    ),
    "private_key": re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
}

PII_RULES = {
    "personal_home_path": re.compile(
        rb"(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|"
        rb"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+)"
    ),
    "email_address": re.compile(
        rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    ),
    "mainland_china_mobile": re.compile(rb"(?<![0-9])1[3-9][0-9]{9}(?![0-9])"),
}

ALLOWED_EMAILS = {b"local@agentloopgate.invalid"}


def public_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = root / relative
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return sorted(paths)


def audit(root: Path) -> dict[str, object]:
    findings: Counter[str] = Counter()
    scanned = 0
    binary_skipped = 0
    for path in public_files(root):
        data = path.read_bytes()
        if b"\0" in data:
            binary_skipped += 1
            continue
        scanned += 1
        for name, pattern in SECRET_RULES.items():
            findings[name] += len(pattern.findall(data))
        for name, pattern in PII_RULES.items():
            matches = pattern.findall(data)
            if name == "email_address":
                matches = [match for match in matches if match.lower() not in ALLOWED_EMAILS]
            findings[name] += len(matches)
    nonzero = {name: count for name, count in sorted(findings.items()) if count}
    return {
        "schema_version": "1.0",
        "scope": "git_cached_and_untracked_nonignored_files",
        "files_scanned": scanned,
        "binary_files_skipped": binary_skipped,
        "secret_rule_count": len(SECRET_RULES),
        "pii_rule_count": len(PII_RULES),
        "finding_counts": nonzero,
        "paths_and_values_withheld": True,
        "status": "failed" if nonzero else "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.project.resolve()
    result = audit(root)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 3 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
