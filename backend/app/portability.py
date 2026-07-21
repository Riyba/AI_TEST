"""Shared helpers for exporting/importing agents, custom tools, and
workflows as portable JSON bundles (see routers/agents.py, routers/tools.py,
routers/workflows.py).

Import never overwrites or reuses an existing row — on a name collision the
importer picks a fresh, unique name (same non-destructive spirit as
``clone_workflow``'s "{name} (copy)"). Any rename is threaded through the
rest of the bundle so an imported workflow/agent stays internally
consistent and immediately runnable.
"""

from __future__ import annotations

import copy
from typing import Any, Literal


def unique_name(base: str, existing: set[str], style: Literal["human", "snake"]) -> str:
    """Return ``base`` if it's not in ``existing``, otherwise a suffixed
    variant that is. ``style`` controls the suffix shape:

    - "human": ``"Foo"`` -> ``"Foo (imported)"`` -> ``"Foo (imported 2)"`` ...
    - "snake": ``"foo"`` -> ``"foo_imported"`` -> ``"foo_imported2"`` ...
      (keeps the custom-tool name pattern ``^[a-z][a-z0-9_]*$`` valid).
    """
    if base not in existing:
        return base
    n = 1
    while True:
        n += 1
        candidate = f"{base} (imported)" if n == 2 else f"{base} (imported {n})"
        if style == "snake":
            candidate = f"{base}_imported" if n == 2 else f"{base}_imported{n}"
        if candidate not in existing:
            return candidate


def custom_tool_names_used(tool_names: list[str], all_custom: set[str]) -> set[str]:
    """Filter an agent's/node's tool names down to the custom (non-builtin)
    ones that need to be bundled for the export to be self-contained."""
    return {name for name in tool_names if name in all_custom}


def remap_graph(
    graph: dict[str, Any],
    id_map: dict[int, int],
    tool_name_map: dict[str, str],
) -> dict[str, Any]:
    """Deep-copy ``graph`` rewriting agent/team references per ``id_map`` and
    tool-node ``tool`` names per ``tool_name_map``. Ids/names with no entry in
    the map are left as-is (e.g. builtin tool names, or an id_map miss which
    graph validation will catch downstream)."""
    out = copy.deepcopy(graph)
    for node in out.get("nodes", []):
        agent_id = node.get("agent_id")
        if agent_id is not None:
            node["agent_id"] = id_map.get(agent_id, agent_id)
        team = node.get("team")
        if team:
            node["team"] = [id_map.get(a, a) for a in team]
        if node.get("type") == "tool" and node.get("tool"):
            node["tool"] = tool_name_map.get(node["tool"], node["tool"])
    return out
