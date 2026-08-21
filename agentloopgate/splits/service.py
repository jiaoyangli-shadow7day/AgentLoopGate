"""Split freezing, integrity verification, and role-based pool access."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from agentloopgate.contracts import canonical_digest
from agentloopgate.schemas import Pool
from agentloopgate.splits.models import (
    AccessKind,
    ActorRole,
    PoolManifest,
    SplitConfig,
    SplitStatus,
)

EXPECTED_POOL_COUNTS: dict[Pool, int] = {
    Pool.PILOT: 7,
    Pool.UPDATE_SOURCE: 25,
    Pool.UPDATE_CHECK: 10,
    Pool.SELECTION: 15,
    Pool.RELEASE_ID: 20,
    Pool.RELEASE_OOD: 20,
}


class SplitIntegrityError(ValueError):
    """Split manifests are incomplete, overlapping, or have drifted."""


class PoolAccessDenied(PermissionError):
    exit_code = 3


class SplitAccessPolicy:
    def require(self, role: ActorRole, pool: Pool, access: AccessKind) -> None:
        if self.is_allowed(role, pool, access):
            return
        raise PoolAccessDenied(
            f"role {role.value} cannot read {access.value} from pool {pool.value}"
        )

    @staticmethod
    def is_allowed(role: ActorRole, pool: Pool, access: AccessKind) -> bool:
        if role is ActorRole.OWNER:
            return True
        if role is ActorRole.UPDATER:
            if pool in {Pool.PILOT, Pool.UPDATE_SOURCE}:
                return True
            return pool is Pool.UPDATE_CHECK and access is AccessKind.AGGREGATE
        if role is ActorRole.UPDATE_EVALUATOR:
            return pool in {Pool.PILOT, Pool.UPDATE_SOURCE, Pool.UPDATE_CHECK}
        if role is ActorRole.SELECTOR:
            return access is AccessKind.AGGREGATE and pool in {
                Pool.UPDATE_CHECK,
                Pool.SELECTION,
            }
        if role is ActorRole.RELEASE_EVALUATOR:
            return pool in {Pool.SELECTION, Pool.RELEASE_ID, Pool.RELEASE_OOD}
        if role is ActorRole.REPORTER:
            return access is AccessKind.AGGREGATE
        return False


class SplitService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path.resolve()
        self.project_root = self.config_path.parent.parent.resolve()

    def load(self) -> SplitConfig:
        try:
            raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise SplitIntegrityError("split config must be a YAML object")
            return SplitConfig.model_validate(raw)
        except OSError as exc:
            raise SplitIntegrityError(f"cannot read split config: {self.config_path}") from exc
        except ValueError as exc:
            if isinstance(exc, SplitIntegrityError):
                raise
            raise SplitIntegrityError(f"invalid split config: {exc}") from exc

    def freeze(self, *, frozen_at: datetime) -> SplitConfig:
        config = self.load()
        if config.status is SplitStatus.FROZEN:
            return self.verify()
        manifests = self._load_and_validate(config)
        pool_specs = {
            pool: spec.model_copy(update={"manifest_digest": canonical_digest(manifests[pool])})
            for pool, spec in config.pools.items()
        }
        pending = config.model_copy(
            update={
                "status": SplitStatus.FROZEN,
                "frozen_at": frozen_at,
                "split_digest": None,
                "pools": pool_specs,
            }
        )
        frozen = pending.model_copy(update={"split_digest": self._config_digest(pending)})
        self._write_config(frozen)
        return frozen

    def verify(self) -> SplitConfig:
        config = self.load()
        if (
            config.status is not SplitStatus.FROZEN
            or config.frozen_at is None
            or config.split_digest is None
        ):
            raise SplitIntegrityError("split config is not frozen")
        manifests = self._load_and_validate(config)
        for pool, spec in config.pools.items():
            actual = canonical_digest(manifests[pool])
            if spec.manifest_digest != actual:
                raise SplitIntegrityError(
                    f"manifest digest mismatch for {pool.value}: "
                    f"expected {spec.manifest_digest}, got {actual}"
                )
        actual_config_digest = self._config_digest(config)
        if actual_config_digest != config.split_digest:
            raise SplitIntegrityError(
                "split config digest mismatch: "
                f"expected {config.split_digest}, got {actual_config_digest}"
            )
        return config

    def _load_and_validate(self, config: SplitConfig) -> dict[Pool, PoolManifest]:
        if config.benchmark.commit == "PIN_BEFORE_PILOT":
            raise SplitIntegrityError("benchmark commit must be pinned before split freeze")
        if set(config.pools) != set(EXPECTED_POOL_COUNTS):
            raise SplitIntegrityError("split config must declare exactly the six v1 pools")

        manifests: dict[Pool, PoolManifest] = {}
        task_owner: dict[str, Pool] = {}
        for pool, expected_count in EXPECTED_POOL_COUNTS.items():
            spec = config.pools[pool]
            if spec.expected_count != expected_count:
                raise SplitIntegrityError(
                    f"{pool.value} expected_count must remain {expected_count}"
                )
            manifest = self._load_manifest(spec.manifest)
            if manifest.pool is not pool:
                raise SplitIntegrityError(f"manifest pool mismatch for {pool.value}")
            if manifest.benchmark_commit != config.benchmark.commit:
                raise SplitIntegrityError(f"benchmark commit mismatch for {pool.value}")
            if len(manifest.tasks) != expected_count:
                raise SplitIntegrityError(
                    f"{pool.value} must contain {expected_count} tasks, got {len(manifest.tasks)}"
                )
            for task in manifest.tasks:
                previous = task_owner.get(task.task_id)
                if previous is not None:
                    raise SplitIntegrityError(
                        f"task {task.task_id} appears in more than one pool: "
                        f"{previous.value}, {pool.value}"
                    )
                task_owner[task.task_id] = pool
            manifests[pool] = manifest

        replay = config.replay_task_ids
        if len(replay) != 10 or len(set(replay)) != 10:
            raise SplitIntegrityError("replay_task_ids must contain exactly 10 unique tasks")
        update_source_ids = {
            task.task_id for task in manifests[Pool.UPDATE_SOURCE].tasks
        }
        if not set(replay).issubset(update_source_ids):
            raise SplitIntegrityError("every replay task must come from update_source")

        ood_families = {
            task.workflow_family for task in manifests[Pool.RELEASE_OOD].tasks
        }
        if not 2 <= len(ood_families) <= 3:
            raise SplitIntegrityError("release_ood must reserve 2-3 complete workflow families")
        other_families = {
            task.workflow_family
            for pool, manifest in manifests.items()
            if pool is not Pool.RELEASE_OOD
            for task in manifest.tasks
        }
        overlap = ood_families & other_families
        if overlap:
            raise SplitIntegrityError(
                f"release_ood workflow families are not fully reserved: {sorted(overlap)}"
            )
        return manifests

    def _load_manifest(self, relative_path: str) -> PoolManifest:
        path = self._resolve_project_path(relative_path)
        try:
            raw = json_load(path)
            return PoolManifest.model_validate(raw)
        except OSError as exc:
            raise SplitIntegrityError(f"cannot read pool manifest: {relative_path}") from exc
        except ValueError as exc:
            raise SplitIntegrityError(f"invalid pool manifest {relative_path}: {exc}") from exc

    def _resolve_project_path(self, relative_path: str) -> Path:
        candidate = (self.project_root / relative_path).resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise SplitIntegrityError("pool manifest path escapes the project root") from exc
        return candidate

    @staticmethod
    def _config_digest(config: SplitConfig) -> str:
        return canonical_digest(config.model_dump(mode="json", exclude={"split_digest"}))

    def _write_config(self, config: SplitConfig) -> None:
        payload: dict[str, Any] = config.model_dump(mode="json")
        temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temporary.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        temporary.replace(self.config_path)


def json_load(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))

