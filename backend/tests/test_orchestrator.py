"""Orchestrator node: agents-as-tools delegation (graph/nodes.py).

An orchestrator persona is handed one delegate_to_<name> tool per team member;
calling it runs that sub-agent's own loop and returns its answer. We verify the
delegation round-trip and that the sub-agent's work is persisted as its own step.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select

from app.graph.builder import build_graph
from app.graph.spec import GraphSpec
from app.models import RunStep
from conftest import FakeLLMProvider, make_agent, text_response, tool_response

pytestmark = pytest.mark.asyncio


def _orchestrator_graph() -> GraphSpec:
    return GraphSpec.model_validate(
        {
            "entry": "o",
            "nodes": [
                {
                    "id": "o",
                    "type": "orchestrator",
                    "agent_id": 1,
                    "team": [2],
                    "prompt": "{task}",
                }
            ],
            "edges": [],
        }
    )


async def test_orchestrator_delegates_to_team_member(make_ctx, session_factory, repo) -> None:
    agents = {
        1: make_agent(id=1, name="Boss", role="routes work", tools=[]),
        2: make_agent(id=2, name="Reviewer", role="reviews code", tools=["read_file"]),
    }
    provider = FakeLLMProvider(
        [
            # Persona routes to the Reviewer.
            tool_response("delegate_to_reviewer", {"request": "review the diff"}),
            # Reviewer's own loop answers.
            text_response("the code looks good"),
            # Persona composes the final answer.
            text_response("Final: reviewer says the code looks good"),
        ]
    )
    ctx = await make_ctx(provider, agents=agents)

    graph = build_graph(_orchestrator_graph(), ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "orch"}}
    updates = [
        chunk
        async for chunk in graph.astream(
            {
                "task": "please review",
                "repo_path": str(repo),
                "node_outputs": {},
                "last_output": "",
                "last_tool_success": True,
            },
            config,
            stream_mode="updates",
        )
    ]

    # Final orchestrator output propagated.
    last = next(c["o"] for c in updates if "o" in c)
    assert "reviewer says" in last["last_output"]
    assert provider.call_count == 3

    # The delegated sub-agent ran as its own persisted step.
    async with session_factory() as session:
        steps = (await session.execute(select(RunStep))).scalars().all()
    names = {s.name for s in steps}
    assert "Reviewer" in names
    reviewer_step = next(s for s in steps if s.name == "Reviewer")
    assert reviewer_step.input["delegated_by"] == "Boss"
    assert reviewer_step.status == "succeeded"


async def test_orchestrator_exposes_one_tool_per_member(make_ctx, repo) -> None:
    agents = {
        1: make_agent(id=1, name="Boss", tools=[]),
        2: make_agent(id=2, name="Reviewer", tools=["read_file"]),
    }
    provider = FakeLLMProvider([text_response("done immediately")])
    ctx = await make_ctx(provider, agents=agents)

    graph = build_graph(_orchestrator_graph(), ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "orch2"}}
    async for _ in graph.astream(
        {
            "task": "t",
            "repo_path": str(repo),
            "node_outputs": {},
            "last_output": "",
            "last_tool_success": True,
        },
        config,
        stream_mode="updates",
    ):
        pass

    tool_names = {t["name"] for t in (provider.calls[0]["tools"] or [])}
    assert "delegate_to_reviewer" in tool_names
