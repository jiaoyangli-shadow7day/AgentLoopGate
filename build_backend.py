"""PEP 517 backend that installs project files for editable development builds.

CPython 3.12.13 on macOS ignores ``.pth`` files carrying the filesystem hidden flag. Since a
default ``.venv`` inherits that flag, a conventional editable install can leave console scripts
unable to import the project. Building the regular wheel for the PEP 660 hook keeps ``uv sync``
and the installed CLI deterministic across working directories.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flit_core import buildapi
from flit_core.common import Module, make_metadata
from flit_core.config import read_flit_config
from flit_core.sdist import SdistBuilder


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return buildapi.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return buildapi.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """Build from the declared package without scanning ignored runtime evidence.

    Flit 3.12 expands its default recursive ``**/__pycache__`` exclusion from
    the repository root before it selects package files. AgentLoopGate keeps
    append-only runtime evidence under ignored ``runs/`` paths, so that scan
    becomes unbounded as evidence grows even though those bytes can never enter
    the source distribution. Constructing the same minimal Flit builder with an
    exact extra-file allowlist keeps packaging independent of runtime volume.
    """

    del config_settings
    pyproject = Path(__file__).resolve().with_name("pyproject.toml")
    config = read_flit_config(pyproject)
    if config.sdist_include_patterns != ["build_backend.py"]:
        raise RuntimeError(
            "AgentLoopGate sdist requires the exact build_backend.py allowlist"
        )
    unexpected_excludes = set(config.sdist_exclude_patterns) - {
        "**/__pycache__",
        "**.pyc",
    }
    if unexpected_excludes:
        raise RuntimeError(
            "AgentLoopGate sdist does not accept project-wide exclusion globs"
        )
    module = Module(config.module, pyproject.parent)
    metadata = make_metadata(module, config)
    builder = SdistBuilder(
        module,
        metadata,
        pyproject.parent,
        config.reqs_by_extra,
        config.entrypoints,
        [pyproject.name, *config.referenced_files, "build_backend.py"],
        config.data_directory,
        include_patterns=(),
        exclude_patterns=(),
    )
    return builder.build(Path(sdist_directory)).name


def get_requires_for_build_wheel(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    return buildapi.get_requires_for_build_wheel(config_settings)


def get_requires_for_build_editable(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    return buildapi.get_requires_for_build_wheel(config_settings)


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    return buildapi.prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    return buildapi.prepare_metadata_for_build_wheel(metadata_directory, config_settings)
