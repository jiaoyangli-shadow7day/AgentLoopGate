"""Runtime binding for portable declarative tool-routing assets."""

from __future__ import annotations

from typing import Any

import yaml


class CapabilityBindingError(ValueError):
    """A routing asset is not bound to the host's current capability registry."""


def validate_runtime_capability_binding(
    content: str,
    runtime_capabilities: set[str],
) -> None:
    try:
        routing = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise CapabilityBindingError("tool routing asset is not valid YAML") from exc
    binding = routing.get("capability_binding") if isinstance(routing, dict) else None
    if binding != {
        "source": "runtime_tool_schema",
        "reject_unknown_route_targets": True,
    }:
        raise CapabilityBindingError(
            "tool routing is not bound to the runtime tool schema"
        )
    targets = _routing_targets(routing)
    unknown = sorted(targets - runtime_capabilities)
    if unknown:
        raise CapabilityBindingError(
            "tool routing references capabilities absent from this task: "
            + ", ".join(unknown)
        )


def _routing_targets(value: Any) -> set[str]:
    targets: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "capability" and isinstance(item, str):
                targets.add(item)
            elif key == "capability_ref" and isinstance(item, str):
                prefix = "runtime://tool/"
                if not item.startswith(prefix) or not item.removeprefix(prefix):
                    raise CapabilityBindingError(
                        "capability_ref must use runtime://tool/<name>"
                    )
                targets.add(item.removeprefix(prefix))
            else:
                targets.update(_routing_targets(item))
    elif isinstance(value, list):
        for item in value:
            targets.update(_routing_targets(item))
    return targets
