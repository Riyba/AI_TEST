"""Shared LangGraph state for all workflows."""

from __future__ import annotations

from typing import Annotated, TypedDict


def _merge(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    return {**a, **b}


def _add_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    """Sum per-key counts so a node's attempt tally accumulates across the
    loop-backs that re-enter it, rather than being overwritten each pass."""
    out = dict(a)
    for key, value in b.items():
        out[key] = out.get(key, 0) + value
    return out


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
    # Whether the most recent tool failure could plausibly succeed on retry
    # (see tools/registry.py::ToolResult.retryable). True when the last tool
    # succeeded; meaningful only after a failure.
    last_tool_retryable: bool
    # How many times the most recent tool node had executed, counting this run.
    last_tool_attempts: int
    # tool node_id -> number of times it has executed this run (loop guard).
    attempts: Annotated[dict[str, int], _add_counts]
    # tool node_id -> reason, for nodes that hit a terminal (non-retryable)
    # failure. Re-entering such a node aborts the run instead of looping.
    aborted_nodes: Annotated[dict[str, str], _merge]
    # Set by condition nodes; read by their conditional-edge router.
    route: bool
