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
    temperature: float | None = Field(default=None, ge=0, le=1)
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


class RunCreate(BaseModel):
    workflow_id: int
    task: str = ""
    repo_path: str


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


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = ""
    edited_output: str | None = None


class ToolMeta(BaseModel):
    name: str
    description: str
    mutating: bool
    input_schema: dict[str, Any]


class MetaOut(BaseModel):
    models: list[str]
    tools: list[ToolMeta]
    project_roots: list[str]
    api_key_configured: bool
