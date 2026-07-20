"""Agent tool-use loop termination and side effects
(graph/nodes.py::run_agent_loop).

Covers the two independent stop conditions the TODO calls out — the turn limit
and the token budget — plus the write_file → artifact side effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.graph.nodes import run_agent_loop
from app.models import Artifact
from conftest import FakeLLMProvider, make_agent, text_response, tool_response

pytestmark = pytest.mark.asyncio


async def _run(ctx, agent, prompt="do the task"):
    return await run_agent_loop(
        agent, ctx, event_node_id="n1", prompt=prompt, attachments=[]
    )


# --------------------------------------------------------------------------- #
# Normal termination                                                         #
# --------------------------------------------------------------------------- #


async def test_stops_on_end_turn(make_ctx) -> None:
    provider = FakeLLMProvider([text_response("all done")])
    ctx = await make_ctx(provider)
    result = await _run(ctx, make_agent())
    assert result.text == "all done"
    assert provider.call_count == 1


async def test_executes_tool_then_stops(make_ctx, repo: Path) -> None:
    provider = FakeLLMProvider(
        [
            tool_response("write_file", {"path": "out.txt", "content": "hi"}),
            text_response("wrote the file"),
        ]
    )
    ctx = await make_ctx(provider)
    result = await _run(ctx, make_agent())
    assert result.text == "wrote the file"
    assert provider.call_count == 2
    # Side effect happened.
    assert (repo / "out.txt").read_text() == "hi"
    # And it was logged as a tool call.
    assert result.tool_calls[0]["tool"] == "write_file"
    assert result.tool_calls[0]["success"] is True


# --------------------------------------------------------------------------- #
# Turn limit                                                                  #
# --------------------------------------------------------------------------- #


async def test_turn_limit_terminates_infinite_tool_calls(make_ctx) -> None:
    """A model that never stops calling tools is bounded by max_turns."""
    calls = {"n": 0}

    def always_tool(**_: object):
        calls["n"] += 1
        return tool_response(
            "read_file", {"path": "x.txt"}, call_id=f"c{calls['n']}"
        )

    provider = FakeLLMProvider(always_tool)
    ctx = await make_ctx(provider)
    agent = make_agent(max_turns=3, max_tokens=10_000_000)
    result = await _run(ctx, agent)

    assert provider.call_count == 3
    assert "turn limit" in result.text


async def test_max_turns_floored_at_one(make_ctx) -> None:
    """max_turns=0 must still run exactly one turn (max(1, ...))."""
    provider = FakeLLMProvider([text_response("done")])
    ctx = await make_ctx(provider)
    result = await _run(ctx, make_agent(max_turns=0))
    assert provider.call_count == 1
    assert result.text == "done"


# --------------------------------------------------------------------------- #
# Token budget                                                                #
# --------------------------------------------------------------------------- #


async def test_token_budget_stops_before_next_tool(make_ctx, repo: Path) -> None:
    """Once the running token total reaches the budget, the loop stops before
    executing the pending tool calls or making another LLM call."""
    provider = FakeLLMProvider(
        [
            # This single turn's usage already exceeds the 100-token budget.
            tool_response(
                "write_file",
                {"path": "should_not_exist.txt", "content": "x"},
                input_tokens=60,
                output_tokens=60,
            ),
            # A second response exists but must never be consumed.
            text_response("unreached"),
        ]
    )
    ctx = await make_ctx(provider)
    agent = make_agent(max_turns=10, max_tokens=100)
    result = await _run(ctx, agent)

    assert provider.call_count == 1
    assert "token limit" in result.text
    # The pending tool call from the over-budget turn was not executed.
    assert not (repo / "should_not_exist.txt").exists()
    assert result.tool_calls == []


async def test_tokens_accumulate_across_turns(make_ctx) -> None:
    """Budget is checked against the cumulative total, not a single turn."""
    provider = FakeLLMProvider(
        [
            tool_response(
                "read_file", {"path": "a.txt"}, input_tokens=30, output_tokens=30
            ),
            tool_response(
                "read_file", {"path": "b.txt"}, input_tokens=30, output_tokens=30
            ),
            text_response("unreached"),
        ]
    )
    ctx = await make_ctx(provider)
    agent = make_agent(max_turns=10, max_tokens=100)
    result = await _run(ctx, agent)

    # Turn 1: total=60 (<100) → execute tool. Turn 2: total=120 (>=100) → stop.
    assert provider.call_count == 2
    assert "token limit" in result.text
    assert result.input_tokens == 60
    assert result.output_tokens == 60


# --------------------------------------------------------------------------- #
# write_file → artifact persistence                                          #
# --------------------------------------------------------------------------- #


async def test_write_file_saves_artifact(make_ctx, session_factory) -> None:
    provider = FakeLLMProvider(
        [
            tool_response("write_file", {"path": "src/x.py", "content": "print(1)"}),
            text_response("done"),
        ]
    )
    ctx = await make_ctx(provider)
    await _run(ctx, make_agent())

    async with session_factory() as session:
        artifacts = (await session.execute(select(Artifact))).scalars().all()
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.kind == "file"
    assert art.path == "src/x.py"
    assert art.content == "print(1)"


async def test_failed_tool_does_not_save_artifact(make_ctx, session_factory) -> None:
    """A write outside the jail fails; no artifact is recorded for it."""
    provider = FakeLLMProvider(
        [
            tool_response("write_file", {"path": "../escape.py", "content": "x"}),
            text_response("could not write"),
        ]
    )
    ctx = await make_ctx(provider)
    result = await _run(ctx, make_agent())

    assert result.tool_calls[0]["success"] is False
    async with session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(Artifact))
        ).scalar_one()
    assert count == 0


# --------------------------------------------------------------------------- #
# Approval gating of the in-loop toolset                                     #
# --------------------------------------------------------------------------- #


async def test_require_approval_hides_mutating_tools(make_ctx) -> None:
    """An approval-gated agent must not be handed mutating tools in its loop."""
    provider = FakeLLMProvider([text_response("done")])
    ctx = await make_ctx(provider)
    agent = make_agent(
        require_approval=True, tools=["read_file", "write_file", "run_command"]
    )
    await _run(ctx, agent)

    tool_names = {t["name"] for t in (provider.calls[0]["tools"] or [])}
    assert "read_file" in tool_names
    assert "write_file" not in tool_names  # mutating
    assert "run_command" not in tool_names  # mutating


async def test_no_approval_includes_mutating_tools(make_ctx) -> None:
    provider = FakeLLMProvider([text_response("done")])
    ctx = await make_ctx(provider)
    agent = make_agent(require_approval=False, tools=["read_file", "write_file"])
    await _run(ctx, agent)

    tool_names = {t["name"] for t in (provider.calls[0]["tools"] or [])}
    assert {"read_file", "write_file"} <= tool_names
