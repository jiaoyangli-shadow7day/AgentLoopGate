from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentloopgate.cli import app
from agentloopgate.schemas import Pool
from agentloopgate.splits import (
    AccessKind,
    ActorRole,
    PoolAccessDenied,
    SplitAccessPolicy,
    SplitIntegrityError,
    SplitService,
)

COUNTS = {
    Pool.PILOT: 7,
    Pool.UPDATE_SOURCE: 25,
    Pool.UPDATE_CHECK: 10,
    Pool.SELECTION: 15,
    Pool.RELEASE_ID: 20,
    Pool.RELEASE_OOD: 20,
}
runner = CliRunner()


def build_split_project(root: Path, *, duplicate: bool = False) -> Path:
    data_dir = root / "data" / "splits"
    config_dir = root / "configs"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    task_ids: dict[Pool, list[str]] = {}

    for pool, count in COUNTS.items():
        ids = [f"{pool.value}_{index:03d}" for index in range(1, count + 1)]
        if duplicate and pool is Pool.UPDATE_CHECK:
            ids[0] = task_ids[Pool.UPDATE_SOURCE][0]
        task_ids[pool] = ids
        tasks = []
        for index, task_id in enumerate(ids):
            workflow_family = (
                "ood_family_a" if index < 10 else "ood_family_b"
            ) if pool is Pool.RELEASE_OOD else f"id_family_{index % 4}"
            tasks.append(
                {
                    "task_id": task_id,
                    "workflow_family": workflow_family,
                    "high_risk": index % 5 == 0,
                    "document_count": index % 3 + 1,
                    "tool_complexity": index % 4 + 1,
                }
            )
        (data_dir / f"{pool.value}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "pool": pool.value,
                    "benchmark_commit": "fixture-commit",
                    "tasks": tasks,
                }
            ),
            encoding="utf-8",
        )

    config = {
        "schema_version": "1.0",
        "benchmark": {"name": "tau3-bench", "commit": "fixture-commit"},
        "status": "draft",
        "frozen_at": None,
        "split_digest": None,
        "pools": {
            pool.value: {
                "manifest": f"data/splits/{pool.value}.json",
                "expected_count": count,
                "manifest_digest": None,
            }
            for pool, count in COUNTS.items()
        },
        "replay_task_ids": task_ids[Pool.UPDATE_SOURCE][:10],
    }
    config_path = config_dir / "splits.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def test_freeze_and_verify_six_physically_disjoint_pools(tmp_path: Path) -> None:
    config_path = build_split_project(tmp_path)
    service = SplitService(config_path)

    frozen = service.freeze(frozen_at=datetime(2026, 8, 20, tzinfo=UTC))

    assert frozen.status == "frozen"
    assert frozen.split_digest is not None
    assert sum(item.expected_count for item in frozen.pools.values()) == 97
    assert all(item.manifest_digest for item in frozen.pools.values())
    assert service.verify().split_digest == frozen.split_digest


def test_split_freeze_rejects_cross_pool_duplicates(tmp_path: Path) -> None:
    config_path = build_split_project(tmp_path, duplicate=True)

    with pytest.raises(SplitIntegrityError, match="more than one pool"):
        SplitService(config_path).freeze(
            frozen_at=datetime(2026, 8, 20, tzinfo=UTC)
        )


def test_frozen_manifest_drift_is_detected(tmp_path: Path) -> None:
    config_path = build_split_project(tmp_path)
    service = SplitService(config_path)
    service.freeze(frozen_at=datetime(2026, 8, 20, tzinfo=UTC))
    manifest = tmp_path / "data" / "splits" / "release_id.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["tasks"][0]["document_count"] += 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SplitIntegrityError, match="digest mismatch"):
        service.verify()


def test_updater_acl_blocks_selection_and_release_data() -> None:
    policy = SplitAccessPolicy()

    policy.require(ActorRole.UPDATER, Pool.UPDATE_SOURCE, AccessKind.TRACE)
    policy.require(ActorRole.UPDATER, Pool.UPDATE_CHECK, AccessKind.AGGREGATE)

    for pool in (Pool.SELECTION, Pool.RELEASE_ID, Pool.RELEASE_OOD):
        with pytest.raises(PoolAccessDenied) as error:
            policy.require(ActorRole.UPDATER, pool, AccessKind.TASKS)
        assert error.value.exit_code == 3

    with pytest.raises(PoolAccessDenied):
        policy.require(ActorRole.UPDATER, Pool.UPDATE_CHECK, AccessKind.TRACE)


def test_split_cli_freeze_then_verify(tmp_path: Path) -> None:
    config_path = build_split_project(tmp_path)

    frozen = runner.invoke(
        app,
        ["split", "freeze", "--config", str(config_path), "--json"],
    )
    verified = runner.invoke(
        app,
        ["split", "verify", "--config", str(config_path), "--json"],
    )

    assert frozen.exit_code == 0
    assert json.loads(frozen.stdout)["task_count"] == 97
    assert verified.exit_code == 0
    assert json.loads(verified.stdout)["status"] == "verified"
