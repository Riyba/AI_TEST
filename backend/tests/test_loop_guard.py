"""The loop guard for tool nodes (graph/nodes.py::make_tool_node).

A workflow that loops a failing tool node back on itself must not spin to the
recursion limit. Two guards, driven here against real compiled graphs with an
in-memory checkpointer:

- a *non-retryable* failure (missing prereq / malformed command) aborts on the
  first loop-back, before re-executing;
- a *retryable* failure that never resolves aborts once the per-node attempt
  budget is spent.

Both surface as LoopAbortedError, which the runner turns into a clear failed
status rather than an opaque GraphRecursionError.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

from app.graph.builder import build_graph
from app.graph.nodes import LoopAbortedError
from app.graph.spec import GraphSpec
from app.models import RunStep
from conftest import FakeLLMProvider

pytestmark = pytest.mark.asyncio


def _retry_loop_graph(command: str) -> GraphSpec:
    """entry tool 't' runs `command`; a tool_success condition loops the false
    edge straight back to 't' and only escapes to 'done' when it succeeds."""
    return GraphSpec.model_validate(
        {
            "entry": "t",
            "nodes": [
                {
                    "id": "t",
                    "type": "tool",
                    "name": "flaky step",
                    "tool": "run_command",
                    "params": {"command": command},
                    "require_approval": False,
                },
                {
                    "id": "c",
                    "type": "condition",
                    "predicate": {"kind": "tool_success", "value": "", "node_id": None},
                },
                {
                    "id": "done",
                    "type": "tool",
                    "name": "wrap up",
                    "tool": "list_files",
                    "params": {},
                    "require_approval": False,
                },
            ],
            "edges": [
                {"source": "t", "target": "c"},
                {"source": "c", "target": "done", "label": "true"},
                {"source": "c", "target": "t", "label": "false"},
            ],
        }
    )


async def _steps_for(session_factory, node_id: str) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                select(func.count()).select_from(RunStep).where(RunStep.node_id == node_id)
            )
        ).scalar_one()


async def _drain(agen):
    return [chunk async for chunk in agen]


def _initial(repo: Path) -> dict:
    return {
        "task": "t",
        "repo_path": str(repo),
        "node_outputs": {},
        "last_output": "",
        "last_tool_success": True,
        "last_tool_retryable": True,
        "last_tool_attempts": 0,
        "attempts": {},
        "aborted_nodes": {},
    }


async def test_non_retryable_failure_aborts_on_loop_back(
    make_ctx, session_factory, repo: Path
) -> None:
    """A malformed command (not allowlisted) is a terminal failure: the node
    runs once, and the loop-back aborts before wasting a second execution."""
    ctx = await make_ctx(FakeLLMProvider([]))
    graph = build_graph(_retry_loop_graph("notarealtool --now"), ctx).compile(
        checkpointer=MemorySaver()
    )
    config = {"configurable": {"thread_id": "t-terminal"}}

    with pytest.raises(LoopAbortedError) as exc:
        await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))

    assert "cannot succeed on retry" in str(exc.value)
    assert await _steps_for(session_factory, "t") == 1  # never re-executed
    assert await _steps_for(session_factory, "done") == 0  # never escaped the loop


async def test_retryable_failure_aborts_after_budget(
    make_ctx, session_factory, repo: Path
) -> None:
    """A retryable-but-never-succeeding step stops once the attempt budget is
    spent, rather than looping to the recursion limit."""
    ctx = await make_ctx(FakeLLMProvider([]))
    ctx.max_tool_attempts = 3
    # `git status` in a non-git dir fails (exit != 0) but is retryable — the
    # exact kind of failure that would otherwise loop forever.
    graph = build_graph(_retry_loop_graph("git status"), ctx).compile(
        checkpointer=MemorySaver()
    )
    config = {"configurable": {"thread_id": "t-budget"}}

    with pytest.raises(LoopAbortedError) as exc:
        await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))

    assert "retry budget" in str(exc.value)
    assert await _steps_for(session_factory, "t") == 3  # exactly the budget
    assert await _steps_for(session_factory, "done") == 0


async def test_successful_tool_does_not_abort(
    make_ctx, session_factory, repo: Path
) -> None:
    """A tool that succeeds escapes the loop immediately — the guard is inert
    on the happy path."""
    ctx = await make_ctx(FakeLLMProvider([]))
    # `list_files` (via run_command 'ls') succeeds in the empty repo dir.
    graph = build_graph(_retry_loop_graph("ls"), ctx).compile(
        checkpointer=MemorySaver()
    )
    config = {"configurable": {"thread_id": "t-happy"}}

    await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))

    assert await _steps_for(session_factory, "t") == 1
    assert await _steps_for(session_factory, "done") == 1  # escaped to the exit
