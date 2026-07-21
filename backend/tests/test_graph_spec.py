"""GraphSpec validation (graph/spec.py). These invariants are what keeps a
malformed workflow from ever reaching the executor."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.graph.spec import validate_graph


def _agent_node(node_id: str = "a", **extra) -> dict:
    return {"id": node_id, "type": "agent", "agent_id": 1, **extra}


def test_minimal_valid_graph() -> None:
    spec = validate_graph({"entry": "a", "nodes": [_agent_node()], "edges": []})
    assert spec.entry == "a"


def test_duplicate_node_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate node ids"):
        validate_graph({"entry": "a", "nodes": [_agent_node(), _agent_node()], "edges": []})


def test_entry_must_exist() -> None:
    with pytest.raises(ValidationError, match="entry node"):
        validate_graph({"entry": "missing", "nodes": [_agent_node()], "edges": []})


def test_edge_references_unknown_node() -> None:
    with pytest.raises(ValidationError, match="unknown node"):
        validate_graph(
            {
                "entry": "a",
                "nodes": [_agent_node()],
                "edges": [{"source": "a", "target": "ghost"}],
            }
        )


def test_agent_node_requires_agent_id() -> None:
    with pytest.raises(ValidationError, match="missing agent_id"):
        validate_graph({"entry": "a", "nodes": [{"id": "a", "type": "agent"}], "edges": []})


def test_tool_node_requires_tool_name() -> None:
    with pytest.raises(ValidationError, match="missing a tool name"):
        validate_graph({"entry": "a", "nodes": [{"id": "a", "type": "tool"}], "edges": []})


def test_condition_needs_true_and_false_edges() -> None:
    graph = {
        "entry": "c",
        "nodes": [
            {"id": "c", "type": "condition", "predicate": {"kind": "tool_success"}},
            _agent_node("a"),
        ],
        "edges": [{"source": "c", "target": "a", "label": "true"}],  # no false edge
    }
    with pytest.raises(ValidationError, match="one 'true' and one 'false'"):
        validate_graph(graph)


def test_condition_requires_predicate() -> None:
    graph = {
        "entry": "c",
        "nodes": [
            {"id": "c", "type": "condition"},
            _agent_node("a"),
            _agent_node("b"),
        ],
        "edges": [
            {"source": "c", "target": "a", "label": "true"},
            {"source": "c", "target": "b", "label": "false"},
        ],
    }
    with pytest.raises(ValidationError, match="missing a predicate"):
        validate_graph(graph)


def test_non_condition_node_cannot_have_multiple_edges() -> None:
    graph = {
        "entry": "a",
        "nodes": [_agent_node("a"), _agent_node("b"), _agent_node("c")],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
        ],
    }
    with pytest.raises(ValidationError, match="multiple outgoing edges"):
        validate_graph(graph)


def test_orchestrator_requires_team() -> None:
    with pytest.raises(ValidationError, match="at least one team member"):
        validate_graph(
            {
                "entry": "o",
                "nodes": [{"id": "o", "type": "orchestrator", "agent_id": 1, "team": []}],
                "edges": [],
            }
        )


def test_orchestrator_cannot_include_itself() -> None:
    with pytest.raises(ValidationError, match="cannot have itself"):
        validate_graph(
            {
                "entry": "o",
                "nodes": [{"id": "o", "type": "orchestrator", "agent_id": 1, "team": [1]}],
                "edges": [],
            }
        )


def test_condition_false_edge_may_loop_back_to_an_earlier_node() -> None:
    """Only a node's own outgoing-edge count is restricted; nothing stops
    multiple edges converging on the same target, which is what a retry loop
    (a condition's false edge pointing back upstream) requires."""
    graph = {
        "entry": "work",
        "nodes": [
            _agent_node("work"),
            {"id": "check", "type": "condition", "predicate": {"kind": "tool_success"}},
            _agent_node("done"),
        ],
        "edges": [
            {"source": "work", "target": "check"},
            {"source": "check", "target": "done", "label": "true"},
            {"source": "check", "target": "work", "label": "false"},
        ],
    }
    spec = validate_graph(graph)
    assert spec.entry == "work"


def test_labeled_edge_on_non_condition_rejected() -> None:
    graph = {
        "entry": "a",
        "nodes": [_agent_node("a"), _agent_node("b")],
        "edges": [{"source": "a", "target": "b", "label": "true"}],
    }
    with pytest.raises(ValidationError, match="labeled edge"):
        validate_graph(graph)
