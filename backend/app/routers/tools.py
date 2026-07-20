"""CRUD + AI-authoring + dry-run for user-defined custom tools.

Custom tools live in the ``custom_tools`` table but must also be reflected into
the in-memory tool REGISTRY (which agent loops and workflow nodes read). Every
write re-syncs the registry from the database via ``_resync`` so the two never
drift within this single-process app.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..attachments import AttachmentContent
from ..db import get_session
from ..llm import get_provider
from ..models import Agent, Attachment, CustomTool, Workflow
from ..runner import validate_repo_path
from ..schemas import (
    CustomToolIn,
    CustomToolOut,
    ToolDraft,
    ToolGenerateIn,
    ToolTestIn,
    ToolTestOut,
)
from ..tools import execute_tool, is_builtin, sync_custom_tools
from ..tools.generate import ToolGenerationError, generate_tool_draft

router = APIRouter(prefix="/api/tools", tags=["tools"])

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


async def _resync(session: AsyncSession) -> None:
    """Reload every custom tool from the DB into the in-memory registry."""
    rows = (
        (await session.execute(select(CustomTool).order_by(CustomTool.id)))
        .scalars()
        .all()
    )
    sync_custom_tools(list(rows))


def _validate(payload: CustomToolIn) -> None:
    name = payload.name.strip()
    if not _NAME_RE.match(name):
        raise HTTPException(
            422,
            "name must be lowercase snake_case: start with a letter, then "
            "letters/digits/underscores",
        )
    if is_builtin(name):
        raise HTTPException(422, f"'{name}' is the name of a builtin tool")
    schema = payload.input_schema
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise HTTPException(422, "input_schema must be a JSON Schema object (type: object)")
    if "def run(" not in payload.source_code:
        raise HTTPException(422, "source_code must define a function: def run(params): ...")


async def _references(session: AsyncSession, name: str) -> list[str]:
    """Human-readable list of agents/workflows referencing a tool by name."""
    refs: list[str] = []
    agents = (await session.execute(select(Agent))).scalars().all()
    for agent in agents:
        if name in (agent.tools or []):
            refs.append(f"agent '{agent.name}'")
    workflows = (await session.execute(select(Workflow))).scalars().all()
    for wf in workflows:
        for node in (wf.graph or {}).get("nodes", []):
            if node.get("type") == "tool" and node.get("tool") == name:
                refs.append(f"workflow '{wf.name}'")
                break
    return refs


@router.get("", response_model=list[CustomToolOut])
async def list_tools(session: AsyncSession = Depends(get_session)) -> list[CustomTool]:
    rows = (
        (await session.execute(select(CustomTool).order_by(CustomTool.id)))
        .scalars()
        .all()
    )
    return list(rows)


@router.post("", response_model=CustomToolOut, status_code=201)
async def create_tool(
    payload: CustomToolIn, session: AsyncSession = Depends(get_session)
) -> CustomTool:
    _validate(payload)
    name = payload.name.strip()
    existing = (
        await session.execute(select(CustomTool).where(CustomTool.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"a tool named '{name}' already exists")
    tool = CustomTool(**{**payload.model_dump(), "name": name})
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    await _resync(session)
    return tool


@router.get("/{tool_id}", response_model=CustomToolOut)
async def get_tool(
    tool_id: int, session: AsyncSession = Depends(get_session)
) -> CustomTool:
    tool = await session.get(CustomTool, tool_id)
    if tool is None:
        raise HTTPException(404, "tool not found")
    return tool


@router.put("/{tool_id}", response_model=CustomToolOut)
async def update_tool(
    tool_id: int, payload: CustomToolIn, session: AsyncSession = Depends(get_session)
) -> CustomTool:
    tool = await session.get(CustomTool, tool_id)
    if tool is None:
        raise HTTPException(404, "tool not found")
    _validate(payload)
    name = payload.name.strip()
    clash = (
        await session.execute(
            select(CustomTool).where(
                CustomTool.name == name, CustomTool.id != tool_id
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(409, f"a tool named '{name}' already exists")
    for key, value in payload.model_dump().items():
        setattr(tool, key, value)
    tool.name = name
    await session.commit()
    await session.refresh(tool)
    await _resync(session)
    return tool


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: int,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
) -> None:
    tool = await session.get(CustomTool, tool_id)
    if tool is None:
        raise HTTPException(404, "tool not found")
    if not force:
        refs = await _references(session, tool.name)
        if refs:
            raise HTTPException(
                409,
                f"'{tool.name}' is used by {', '.join(refs)}. "
                "Delete anyway with force=true.",
            )
    await session.delete(tool)
    await session.commit()
    await _resync(session)


@router.post("/generate", response_model=ToolDraft)
async def generate_tool(
    payload: ToolGenerateIn, session: AsyncSession = Depends(get_session)
) -> ToolDraft:
    if not payload.prompt.strip():
        raise HTTPException(422, "prompt is required")
    attachments: list[AttachmentContent] = []
    for att_id in payload.attachment_ids:
        row = await session.get(Attachment, att_id)
        if row is None:
            raise HTTPException(404, f"attachment {att_id} not found")
        attachments.append(
            AttachmentContent(
                filename=row.filename,
                mime_type=row.mime_type,
                kind=row.kind,
                data=row.data,
            )
        )
    try:
        draft = await generate_tool_draft(
            provider=get_provider(),
            model=payload.model,
            prompt=payload.prompt,
            attachments=attachments,
        )
    except ToolGenerationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface provider errors to the UI
        raise HTTPException(502, f"tool generation failed: {exc}") from exc
    return ToolDraft(**draft)


@router.post("/{tool_id}/test", response_model=ToolTestOut)
async def test_tool(
    tool_id: int, payload: ToolTestIn, session: AsyncSession = Depends(get_session)
) -> ToolTestOut:
    tool = await session.get(CustomTool, tool_id)
    if tool is None:
        raise HTTPException(404, "tool not found")
    try:
        repo = validate_repo_path(payload.repo_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Ensure the registry reflects this tool's current source before running.
    await _resync(session)
    result = await execute_tool(tool.name, repo, payload.params)
    return ToolTestOut(success=result.success, output=result.output)
