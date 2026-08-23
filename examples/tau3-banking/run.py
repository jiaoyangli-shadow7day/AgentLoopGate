"""Register the AgentLoopGate agent, then delegate to the pinned τ³ CLI."""

from agent import create_agentloopgate_dsh_agent
from tau2.cli import main
from tau2.registry import registry

from agentloopgate.runtime import (
    install_evaluator_overlay_from_environment,
    install_tau3_evidence_hooks,
)

install_tau3_evidence_hooks()
install_evaluator_overlay_from_environment()

registry.register_agent_factory(
    create_agentloopgate_dsh_agent,
    "agentloopgate_dsh",
)


if __name__ == "__main__":
    main()
