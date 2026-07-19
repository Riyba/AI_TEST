"""Compile a GraphSpec into a LangGraph StateGraph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    RunContext,
    make_agent_node,
    make_approval_node,
    make_condition_node,
    make_tool_node,
    route_condition,
)
from .spec import GraphSpec
from .state import WorkflowState

_FACTORIES = {
    "agent": make_agent_node,
    "tool": make_tool_node,
    "condition": make_condition_node,
    "approval": make_approval_node,
}


def build_graph(spec: GraphSpec, ctx: RunContext) -> StateGraph:
    graph: StateGraph = StateGraph(WorkflowState)

    for node in spec.nodes:
        graph.add_node(node.id, _FACTORIES[node.type](node, ctx))

    graph.add_edge(START, spec.entry)

    condition_ids = {n.id for n in spec.nodes if n.type == "condition"}
    for node in spec.nodes:
        outgoing = [e for e in spec.edges if e.source == node.id]
        if node.id in condition_ids:
            targets = {e.label: e.target for e in outgoing}
            graph.add_conditional_edges(
                node.id,
                route_condition,
                {"true": targets["true"], "false": targets["false"]},
            )
        elif outgoing:
            graph.add_edge(node.id, outgoing[0].target)
        else:
            graph.add_edge(node.id, END)

    return graph
