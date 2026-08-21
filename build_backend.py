"""PEP 517 backend that installs project files for editable development builds.

CPython 3.12.13 on macOS ignores ``.pth`` files carrying the filesystem hidden flag. Since a
default ``.venv`` inherits that flag, a conventional editable install can leave console scripts
unable to import the project. Building the regular wheel for the PEP 660 hook keeps ``uv sync``
and the installed CLI deterministic across working directories.
"""

from __future__ import annotations

from typing import Any

from flit_core import buildapi


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
    return buildapi.build_sdist(sdist_directory, config_settings)


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

