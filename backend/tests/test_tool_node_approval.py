"""The interrupt-first invariant for mutating tool nodes
(graph/nodes.py::make_tool_node).

LangGraph replays a node from the top when a run resumes after interrupt(), so
the approval interrupt MUST be the first effectful thing in the node — no DB
write and no tool execution may happen before the human decides. We prove this
by driving a real compiled graph with an in-memory checkpointer and asserting
that, at the interrupt, nothing has been written and no step row exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import func, select

from app.graph.builder import build_graph
from app.graph.nodes import RunRejectedError
from app.graph.spec import GraphSpec
from app.models import Artifact, RunStep
from conftest import FakeLLMProvider

pytestmark = pytest.mark.asyncio


def _write_tool_graph(require_approval: bool) -> GraphSpec:
    return GraphSpec.model_validate(
        {
            "entry": "w",
            "nodes": [
                {
                    "id": "w",
                    "type": "tool",
                    "name": "write it",
                    "tool": "write_file",
                    "params": {"path": "out.txt", "content": "written"},
                    "require_approval": require_approval,
                }
            ],
            "edges": [],
        }
    )


async def _step_count(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(RunStep))
        ).scalar_one()


async def _drain(agen):
    return [chunk async for chunk in agen]


async def test_interrupt_is_first_effect(make_ctx, session_factory, repo: Path) -> None:
    provider = FakeLLMProvider([])  # no LLM calls for a tool node
    ctx = await make_ctx(provider)
    graph = build_graph(_write_tool_graph(True), ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-approve"}}

    chunks = await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))

    # We interrupted...
    assert any("__interrupt__" in c for c in chunks)
    # ...and NOTHING effectful ran before the interrupt.
    assert not (repo / "out.txt").exists()
    assert await _step_count(session_factory) == 0


async def test_resume_approve_runs_the_tool(make_ctx, session_factory, repo: Path) -> None:
    provider = FakeLLMProvider([])
    ctx = await make_ctx(provider)
    graph = build_graph(_write_tool_graph(True), ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-approve2"}}

    await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))
    # Resume with approval — now the side effect should happen exactly once.
    await _drain(
        graph.astream(Command(resume={"decision": "approve"}), config, stream_mode="updates")
    )

    assert (repo / "out.txt").read_text() == "written"
    assert await _step_count(session_factory) == 1
    async with session_factory() as session:
        artifacts = (await session.execute(select(Artifact))).scalars().all()
    assert len(artifacts) == 1
    assert artifacts[0].path == "out.txt"


async def test_resume_reject_raises_and_skips_tool(
    make_ctx, session_factory, repo: Path
) -> None:
    provider = FakeLLMProvider([])
    ctx = await make_ctx(provider)
    graph = build_graph(_write_tool_graph(True), ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-reject"}}

    await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))
    with pytest.raises(RunRejectedError):
        await _drain(
            graph.astream(
                Command(resume={"decision": "reject", "note": "no thanks"}),
                config,
                stream_mode="updates",
            )
        )

    assert not (repo / "out.txt").exists()
    assert await _step_count(session_factory) == 0


async def test_no_approval_runs_without_interrupt(
    make_ctx, session_factory, repo: Path
) -> None:
    """require_approval=False on the node => the tool runs immediately, no gate."""
    provider = FakeLLMProvider([])
    ctx = await make_ctx(provider)
    graph = build_graph(_write_tool_graph(False), ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-noapprove"}}

    chunks = await _drain(graph.astream(_initial(repo), config, stream_mode="updates"))

    assert not any("__interrupt__" in c for c in chunks)
    assert (repo / "out.txt").read_text() == "written"
    assert await _step_count(session_factory) == 1


def _initial(repo: Path) -> dict:
    return {
        "task": "t",
        "repo_path": str(repo),
        "node_outputs": {},
        "last_output": "",
        "last_tool_success": True,
    }
