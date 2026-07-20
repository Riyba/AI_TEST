"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Run statuses that mean the run is finished and will not change again.
TERMINAL_STATUSES = {"succeeded", "failed", "rejected", "cancelled"}


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(500), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(100), default="claude-sonnet-5")
    # Cap on think/act turns in this agent's tool-use loop, per run.
    max_turns: Mapped[int] = mapped_column(Integer, default=10)
    # Token budget (input + output) for this agent per run; the loop stops
    # once the budget is spent.
    max_tokens: Mapped[int] = mapped_column(Integer, default=100_000)
    # List of tool names this agent may call in its tool-use loop.
    tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    # When True (default), mutating tools are excluded from the agent's
    # in-loop toolset; mutation happens only via approval-gated tool nodes.
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="Attachment.id"
    )


class CustomTool(Base):
    """A user-defined tool. Its behaviour is stored Python source that defines
    a top-level ``run(params: dict) -> str`` function, executed in an isolated
    subprocess (see app/tools/pyexec.py) jailed to the run's repo directory.

    Custom tools are merged into the in-memory tool REGISTRY at startup and
    after every write, so they appear anywhere a builtin tool does (agent
    permissions, workflow tool nodes, /api/meta)."""

    __tablename__ = "custom_tools"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Tool name as the model sees it; must be a valid identifier and must not
    # collide with a builtin tool.
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # JSON Schema for the tool's params (reused verbatim as the Anthropic
    # tool input_schema).
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # True if the tool writes, executes, or touches anything outside pure
    # reads. Drives approval gating and safe-mode filtering, exactly like a
    # builtin's mutating flag.
    mutating: Mapped[bool] = mapped_column(Boolean, default=True)
    # Python source defining `def run(params: dict) -> str`.
    source_code: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # GraphSpec JSON — see app/graph/spec.py
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"))
    workflow_name: Mapped[str] = mapped_column(String(200), default="")
    # pending | running | waiting_approval | succeeded | failed | rejected | cancelled
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # {"task": str, "repo_path": str}
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LangGraph checkpointer thread id (enables pause/resume).
    thread_id: Mapped[str] = mapped_column(String(64))
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # User-estimated time saved by this run, in minutes. NULL means the user
    # never captured an estimate — metrics must exclude those runs, so 0 and
    # "not captured" stay distinct.
    time_saved_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True once this run's metrics were accepted by Datadog (see app/datadog.py).
    # Stays False when the integration is disabled or submission failed.
    synced_to_datadog: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunStep.id"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Artifact.id"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Attachment.id"
    )


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    node_id: Mapped[str] = mapped_column(String(100))
    node_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200), default="")
    # running | succeeded | failed | rejected
    status: Mapped[str] = mapped_column(String(30), default="running")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Chronological log of tool calls made inside this step (agent loop).
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    run: Mapped[Run] = relationship(back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    name: Mapped[str] = mapped_column(String(300))
    # text | file | diff
    kind: Mapped[str] = mapped_column(String(30), default="text")
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="artifacts")


class Attachment(Base):
    """An uploaded file, owned by an agent (included in every run of that
    agent), by a run (attached at launch), or by neither yet ("staged" —
    uploaded from the run-launch form and claimed when the run is created)."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    # image | pdf | text — decides how the file is presented to the LLM.
    kind: Mapped[str] = mapped_column(String(20), default="text")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped[Agent | None] = relationship(back_populates="attachments")
    run: Mapped[Run | None] = relationship(back_populates="attachments")
