"""JSON graph spec that maps 1:1 onto a LangGraph StateGraph.

A workflow's `graph` column stores a GraphSpec. Node types:

- agent:        runs an Agent (LLM + its permitted tools in a tool-use loop)
- orchestrator: an Agent whose tools are *other agents* — the "agents-as-tools"
                pattern. The orchestrator LLM is handed one delegation tool per
                team member and decides which sub-agent(s) should handle the
                request; each delegated call runs that sub-agent's own tool-use
                loop and returns its answer to the orchestrator.
- tool:         runs one registry tool with templated params; mutating tools
                interrupt for human approval first (unless require_approval=false)
- condition:    routes to the `true` or `false` labeled edge based on a predicate
- approval:     human-in-the-loop gate; pauses the run until approve/reject

Edges are unlabeled except out of condition nodes, which must have exactly
one `true` and one `false` edge. Nodes with no outgoing edge flow to END.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

NodeType = Literal["agent", "orchestrator", "tool", "condition", "approval"]
PredicateKind = Literal[
    "output_contains", "output_not_contains", "tool_success", "should_retry"
]


class Predicate(BaseModel):
    kind: PredicateKind
    # Substring for output_contains / output_not_contains.
    value: str = ""
    # Which node's output to inspect; defaults to the running last_output.
    node_id: str | None = None


class Position(BaseModel):
    x: float = 0
    y: float = 0


class NodeSpec(BaseModel):
    id: str
    type: NodeType
    name: str = ""
    # UI-only; persisted so the editor layout survives reloads.
    position: Position = Field(default_factory=Position)

    # type == "agent" or "orchestrator" (the orchestrator's own persona/brain).
    agent_id: int | None = None
    # Prompt template. Placeholders: {task} {repo_path} {last_output} and
    # {<node_id>} for any prior node's output.
    prompt: str = "{task}"

    # type == "orchestrator" — agent ids exposed to the orchestrator as
    # delegation tools ("agents-as-tools"). The orchestrator routes the request
    # to one or more of these sub-agents.
    team: list[int] = Field(default_factory=list)

    # type == "tool"
    tool: str | None = None
    # Param values are templated with the same placeholders as prompts.
    params: dict[str, Any] = Field(default_factory=dict)
    # Only meaningful for mutating tools; True => interrupt for approval.
    require_approval: bool = True
    # Per-node override of Settings.max_tool_attempts: how many times this tool
    # node may execute in one run before the engine aborts it as a stuck loop.
    max_attempts: int | None = None

    # type == "condition"
    predicate: Predicate | None = None

    # type == "approval"
    message: str = "Approve to continue?"


class EdgeSpec(BaseModel):
    source: str
    target: str
    # "true"/"false" only on edges leaving a condition node.
    label: Literal["true", "false"] | None = None


class GraphSpec(BaseModel):
    entry: str
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> GraphSpec:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate node ids")
        id_set = set(ids)
        if self.nodes and self.entry not in id_set:
            raise ValueError(f"entry node '{self.entry}' does not exist")
        for e in self.edges:
            if e.source not in id_set or e.target not in id_set:
                raise ValueError(f"edge {e.source}->{e.target} references unknown node")
        by_id = {n.id: n for n in self.nodes}
        for n in self.nodes:
            out = [e for e in self.edges if e.source == n.id]
            if n.type == "condition":
                labels = sorted(e.label or "" for e in out)
                if labels != ["false", "true"]:
                    raise ValueError(
                        f"condition node '{n.id}' needs exactly one 'true' and one 'false' edge"
                    )
                if n.predicate is None:
                    raise ValueError(f"condition node '{n.id}' is missing a predicate")
            else:
                if len(out) > 1:
                    raise ValueError(f"node '{n.id}' has multiple outgoing edges")
                if any(e.label for e in out):
                    raise ValueError(f"non-condition node '{n.id}' has a labeled edge")
            if n.type == "agent" and n.agent_id is None:
                raise ValueError(f"agent node '{n.id}' is missing agent_id")
            if n.type == "orchestrator":
                if n.agent_id is None:
                    raise ValueError(
                        f"orchestrator node '{n.id}' is missing agent_id (its persona)"
                    )
                if not n.team:
                    raise ValueError(
                        f"orchestrator node '{n.id}' needs at least one team member"
                    )
                if n.agent_id in n.team:
                    raise ValueError(
                        f"orchestrator node '{n.id}' cannot have itself as a team member"
                    )
            if n.type == "tool" and not n.tool:
                raise ValueError(f"tool node '{n.id}' is missing a tool name")
        _ = by_id
        return self


def validate_graph(graph: dict[str, Any]) -> GraphSpec:
    """Parse+validate a raw dict; raises pydantic.ValidationError on problems."""
    return GraphSpec.model_validate(graph)
