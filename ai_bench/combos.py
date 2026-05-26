from __future__ import annotations
from typing import Any

# A single planned execution unit.
PlannedCombo = tuple[str, str, str]  # (backend, agent, model_id)


def planned_combos(
    *,
    models: list[dict[str, Any]],
    agents: list[str],
    backends: list[str],
    agent_registry: dict[str, dict[str, Any]],
) -> list[PlannedCombo]:
    """Return (backend, agent, model_id) triples the benchmark CLI would execute.

    Filters out:
    - agents not in agent_registry (unknown)
    - (agent, backend) pairs where backend not in agent["supports_backends"]
    - models missing an alias key for the backend
    Model availability (is it downloaded?) is NOT checked here — that requires
    live backend queries and is handled separately by preflight_selection.
    """
    combos: list[PlannedCombo] = []
    for backend in backends:
        for agent in agents:
            info = agent_registry.get(agent)
            if info is None:
                continue
            if backend not in info.get("supports_backends", []):
                continue
            for m in models:
                if not isinstance(m, dict):
                    continue
                if backend not in m:
                    continue
                combos.append((backend, agent, m["id"]))
    return combos


def planned_step_count(
    combos: list[PlannedCombo],
    *,
    iterations: int,
    warmup: int,
) -> int:
    """Total iterations the benchmark CLI would emit progress events for."""
    return len(combos) * (iterations + warmup)
