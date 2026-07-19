"""Shared LangGraph state for all workflows."""

from __future__ import annotations

from typing import Annotated, TypedDict


def _merge(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    return {**a, **b}


class WorkflowState(TypedDict, total=False):
    # Run inputs — set once at start.
    task: str
    repo_path: str
    # node_id -> that node's output text; merged across nodes.
    node_outputs: Annotated[dict[str, str], _merge]
    # Output of the most recently executed producing node.
    last_output: str
    # Whether the most recent tool node succeeded (exit code 0 / no error).
    last_tool_success: bool
    # Set by condition nodes; read by their conditional-edge router.
    route: bool
