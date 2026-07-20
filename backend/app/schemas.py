"""Pydantic schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentIn(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    model: str = "claude-sonnet-5"
    max_turns: int = Field(default=10, ge=1, le=100)
    max_tokens: int = Field(default=100_000, ge=1_000, le=10_000_000)
    tools: list[str] = Field(default_factory=list)
    require_approval: bool = True


class AgentOut(AgentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_template: bool = False
    created_at: datetime
    updated_at: datetime


class WorkflowIn(BaseModel):
    name: str
    description: str = ""
    graph: dict[str, Any] = Field(default_factory=dict)


class WorkflowOut(WorkflowIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_template: bool = False
    created_at: datetime
    updated_at: datetime


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: int | None = None
    run_id: int | None = None
    filename: str
    mime_type: str
    kind: str
    size_bytes: int
    created_at: datetime


class RunCreate(BaseModel):
    workflow_id: int
    task: str = ""
    repo_path: str
    # IDs of staged attachments (uploaded via POST /api/attachments with no
    # owner) to attach to this run.
    attachment_ids: list[int] = Field(default_factory=list)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workflow_id: int
    workflow_name: str
    status: str
    input: dict[str, Any]
    error: str | None = None
    total_input_tokens: int
    total_output_tokens: int
    # None = the user never captured an estimate for this run.
    time_saved_minutes: int | None = None
    # True once the run's metrics were accepted by Datadog.
    synced_to_datadog: bool = False
    created_at: datetime
    finished_at: datetime | None = None


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    node_id: str
    node_type: str
    name: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    started_at: datetime
    finished_at: datetime | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: str
    path: str | None = None
    content: str
    created_at: datetime


class RunDetail(RunOut):
    steps: list[StepOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)


class TimeSavedIn(BaseModel):
    # None clears a previously captured estimate. Capped at 30 days.
    time_saved_minutes: int | None = Field(default=None, ge=0, le=43_200)


class MetricsTotals(BaseModel):
    runs: int
    runs_by_status: dict[str, int]
    input_tokens: int
    output_tokens: int
    time_saved_minutes: int
    runs_with_time_saved: int


class DayMetrics(BaseModel):
    date: str  # ISO date (UTC)
    runs: int
    input_tokens: int
    output_tokens: int
    time_saved_minutes: int
    runs_with_time_saved: int


class WorkflowMetrics(BaseModel):
    workflow_name: str
    runs: int
    succeeded: int
    input_tokens: int
    output_tokens: int
    time_saved_minutes: int
    runs_with_time_saved: int


class AgentMetrics(BaseModel):
    agent: str
    steps: int
    runs: int
    input_tokens: int
    output_tokens: int


class MetricsOut(BaseModel):
    totals: MetricsTotals
    by_day: list[DayMetrics]
    by_workflow: list[WorkflowMetrics]
    by_agent: list[AgentMetrics]


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = ""
    edited_output: str | None = None


class ToolMeta(BaseModel):
    name: str
    description: str
    mutating: bool
    input_schema: dict[str, Any]
    # False for user-defined tools (editable on the Tools page); True for the
    # builtin, code-defined tools which are read-only.
    builtin: bool = True


class CustomToolIn(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    mutating: bool = True
    source_code: str = ""


class CustomToolOut(CustomToolIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class ToolGenerateIn(BaseModel):
    # Natural-language description of the tool to build.
    prompt: str
    # Staged attachment ids (uploaded via POST /api/attachments) to give the
    # model as reference material (API docs, examples, schemas…).
    attachment_ids: list[int] = Field(default_factory=list)
    model: str = "claude-sonnet-5"


class ToolDraft(BaseModel):
    """An unsaved tool definition drafted by the model, for human review."""

    name: str
    description: str
    input_schema: dict[str, Any]
    mutating: bool
    source_code: str


class ToolTestIn(BaseModel):
    repo_path: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolTestOut(BaseModel):
    success: bool
    output: str


class MetaOut(BaseModel):
    models: list[str]
    tools: list[ToolMeta]
    project_roots: list[str]
    api_key_configured: bool
    datadog_configured: bool


class FsEntry(BaseModel):
    name: str
    path: str
    is_git_repo: bool


class FsListing(BaseModel):
    path: str
    parent: str | None
    is_git_repo: bool
    entries: list[FsEntry]
