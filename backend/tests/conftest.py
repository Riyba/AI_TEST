"""Shared test fixtures.

The whole suite runs offline and deterministically:

- ``session_factory`` gives an in-memory SQLite database (StaticPool so every
  session shares one connection) with the schema created — no data/app.db is
  touched.
- ``FakeLLMProvider`` implements the ``LLMProvider`` protocol (see app/llm.py)
  from a canned script of responses, so agent loops run without network calls.
- ``make_ctx`` assembles a ``RunContext`` wired to the fake provider, a fresh
  temp repo directory, and the in-memory DB, with a real ``Run`` row present so
  step/artifact writes have a parent to reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.events import RunEventBus
from app.graph.nodes import AgentDef, RunContext
from app.llm import LLMResponse, ToolCall
from app.models import Run


# --------------------------------------------------------------------------- #
# In-memory database                                                          #
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker:
    """A fresh in-memory SQLite DB with all tables, isolated per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Fake LLM provider                                                           #
# --------------------------------------------------------------------------- #


def text_response(text: str, *, input_tokens: int = 5, output_tokens: int = 5) -> LLMResponse:
    """A terminal assistant turn (no tool calls)."""
    return LLMResponse(
        text=text,
        stop_reason="end_turn",
        tool_calls=[],
        raw_content=[{"type": "text", "text": text}],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def tool_response(
    name: str,
    tool_input: dict[str, Any],
    *,
    call_id: str = "call_1",
    text: str = "",
    input_tokens: int = 5,
    output_tokens: int = 5,
) -> LLMResponse:
    """A turn that asks to call one tool."""
    return LLMResponse(
        text=text,
        stop_reason="tool_use",
        tool_calls=[ToolCall(id=call_id, name=name, input=tool_input)],
        raw_content=[
            {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}
        ],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class FakeLLMProvider:
    """Scripted ``LLMProvider``.

    Pass either a list of ``LLMResponse`` (returned in order) or a callable
    ``(messages, tools) -> LLMResponse`` for open-ended behaviour (e.g. an
    agent that never stops calling tools). Records each call for assertions.
    """

    def __init__(
        self,
        responses: list[LLMResponse] | Callable[..., LLMResponse],
    ) -> None:
        self._script = responses
        self.calls: list[dict[str, Any]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {"model": model, "system": system, "messages": messages, "tools": tools}
        )
        if callable(self._script):
            return self._script(messages=messages, tools=tools)
        if not self._script:
            raise AssertionError("FakeLLMProvider ran out of scripted responses")
        return self._script.pop(0)


# --------------------------------------------------------------------------- #
# RunContext assembly                                                         #
# --------------------------------------------------------------------------- #


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An isolated 'repository' directory for tool jailing."""
    root = tmp_path / "repo"
    root.mkdir()
    return root


def make_agent(**overrides: Any) -> AgentDef:
    defaults: dict[str, Any] = dict(
        id=1,
        name="Coder",
        role="writes code",
        system_prompt="You write code.",
        model="claude-sonnet-5",
        max_turns=10,
        max_tokens=100_000,
        tools=["read_file", "write_file"],
        require_approval=False,
    )
    defaults.update(overrides)
    return AgentDef(**defaults)


@pytest_asyncio.fixture
async def make_ctx(session_factory: async_sessionmaker, repo: Path):
    """Factory that builds a RunContext (and its backing Run row).

    Returns ``(ctx, provider)``; the caller supplies the fake provider's
    script and any agents.
    """

    async def _build(
        provider: FakeLLMProvider,
        agents: dict[int, AgentDef] | None = None,
    ) -> RunContext:
        async with session_factory() as session:
            run = Run(
                workflow_id=1,
                workflow_name="wf",
                status="running",
                input={"task": "do it", "repo_path": str(repo)},
                thread_id="thread-1",
            )
            session.add(run)
            await session.commit()
            run_id = run.id
        return RunContext(
            run_id=run_id,
            repo_path=repo,
            agents=agents or {1: make_agent()},
            provider=provider,
            bus=RunEventBus(),
            session_factory=session_factory,
        )

    return _build
