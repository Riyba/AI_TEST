from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..graph.spec import validate_graph
from ..models import Agent, CustomTool, Workflow
from ..portability import custom_tool_names_used, remap_graph, unique_name
from ..schemas import AgentIn, CustomToolIn, WorkflowExport, WorkflowIn, WorkflowOut
from ..tools import REGISTRY, sync_custom_tools

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _check_graph(graph: dict[str, Any]) -> None:
    if not graph or not graph.get("nodes"):
        return  # empty graphs are fine while editing
    try:
        validate_graph(graph)
    except ValidationError as exc:
        messages = "; ".join(e["msg"] for e in exc.errors())
        raise HTTPException(422, f"invalid graph: {messages}") from exc


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(session: AsyncSession = Depends(get_session)) -> list[Workflow]:
    rows = (await session.execute(select(Workflow).order_by(Workflow.id))).scalars().all()
    return list(rows)


@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    payload: WorkflowIn, session: AsyncSession = Depends(get_session)
) -> Workflow:
    _check_graph(payload.graph)
    workflow = Workflow(**payload.model_dump())
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: int, session: AsyncSession = Depends(get_session)
) -> Workflow:
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(404, "workflow not found")
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: int, payload: WorkflowIn, session: AsyncSession = Depends(get_session)
) -> Workflow:
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(404, "workflow not found")
    _check_graph(payload.graph)
    for key, value in payload.model_dump().items():
        setattr(workflow, key, value)
    await session.commit()
    await session.refresh(workflow)
    return workflow


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(404, "workflow not found")
    await session.delete(workflow)
    await session.commit()


@router.post("/{workflow_id}/clone", response_model=WorkflowOut, status_code=201)
async def clone_workflow(
    workflow_id: int, session: AsyncSession = Depends(get_session)
) -> Workflow:
    source = await session.get(Workflow, workflow_id)
    if source is None:
        raise HTTPException(404, "workflow not found")
    clone = Workflow(
        name=f"{source.name} (copy)",
        description=source.description,
        graph=source.graph,
        is_template=False,
    )
    session.add(clone)
    await session.commit()
    await session.refresh(clone)
    return clone


@router.get("/{workflow_id}/export", response_model=WorkflowExport)
async def export_workflow(
    workflow_id: int, session: AsyncSession = Depends(get_session)
) -> WorkflowExport:
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(404, "workflow not found")

    agent_ids: set[int] = set()
    tool_names: set[str] = set()
    for node in (workflow.graph or {}).get("nodes", []):
        if node.get("agent_id") is not None:
            agent_ids.add(node["agent_id"])
        agent_ids.update(node.get("team") or [])
        if node.get("type") == "tool" and node.get("tool"):
            tool_names.add(node["tool"])

    agents: list[Agent] = []
    if agent_ids:
        agents = list(
            (
                await session.execute(select(Agent).where(Agent.id.in_(agent_ids)))
            )
            .scalars()
            .all()
        )
    for agent in agents:
        tool_names.update(agent.tools or [])

    custom_rows = (await session.execute(select(CustomTool))).scalars().all()
    used = custom_tool_names_used(list(tool_names), {row.name for row in custom_rows})
    tools = [
        CustomToolIn.model_validate(row, from_attributes=True)
        for row in custom_rows
        if row.name in used
    ]
    agent_dicts = [
        {
            "id": agent.id,
            **AgentIn.model_validate(agent, from_attributes=True).model_dump(),
        }
        for agent in agents
    ]
    return WorkflowExport(
        workflow=WorkflowIn.model_validate(workflow, from_attributes=True),
        agents=agent_dicts,
        tools=tools,
    )


@router.post("/import", response_model=WorkflowOut, status_code=201)
async def import_workflow(
    payload: WorkflowExport, session: AsyncSession = Depends(get_session)
) -> Workflow:
    # -- custom tools: compute a collision-safe rename plan ------------
    existing_tool_names = set(
        (await session.execute(select(CustomTool.name))).scalars().all()
    )
    tool_name_map: dict[str, str] = {}
    tool_creates: list[dict[str, Any]] = []
    added_tool_names: set[str] = set()
    for tool_in in payload.tools:
        data = tool_in.model_dump()
        old_name = data["name"].strip()
        new_name = unique_name(old_name, existing_tool_names, "snake")
        if new_name != old_name:
            tool_name_map[old_name] = new_name
        existing_tool_names.add(new_name)
        added_tool_names.add(new_name)
        data["name"] = new_name
        tool_creates.append(data)

    # -- agents: rename plan + tool-reference validation, all up front -
    existing_agent_names = set(
        (await session.execute(select(Agent.name))).scalars().all()
    )
    agent_creates: list[tuple[int | None, dict[str, Any]]] = []
    for entry in payload.agents:
        original_id = entry.get("id")
        agent_in = AgentIn(**{k: v for k, v in entry.items() if k != "id"})
        data = agent_in.model_dump()
        if not data["model"].strip():
            raise HTTPException(422, "model is required")
        new_name = unique_name(data["name"].strip(), existing_agent_names, "human")
        existing_agent_names.add(new_name)
        data["name"] = new_name
        data["tools"] = [tool_name_map.get(t, t) for t in data["tools"]]
        unknown = [
            t for t in data["tools"] if t not in REGISTRY and t not in added_tool_names
        ]
        if unknown:
            raise HTTPException(422, f"unknown tools: {unknown}")
        agent_creates.append((original_id, data))

    existing_workflow_names = set(
        (await session.execute(select(Workflow.name))).scalars().all()
    )
    workflow_name = unique_name(
        payload.workflow.name.strip(), existing_workflow_names, "human"
    )

    # -- validated; now write ------------------------------------------
    for data in tool_creates:
        session.add(CustomTool(**data))

    id_map: dict[int, int] = {}
    for original_id, data in agent_creates:
        agent = Agent(**data)
        session.add(agent)
        await session.flush()
        if original_id is not None:
            id_map[original_id] = agent.id

    remapped_graph = remap_graph(payload.workflow.graph, id_map, tool_name_map)
    _check_graph(remapped_graph)

    workflow = Workflow(
        name=workflow_name,
        description=payload.workflow.description,
        graph=remapped_graph,
        is_template=False,
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    if tool_creates:
        rows = (await session.execute(select(CustomTool))).scalars().all()
        sync_custom_tools(list(rows))
    return workflow


@router.post("/validate")
async def validate_workflow_graph(graph: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_graph(graph)
    except ValidationError as exc:
        return {"valid": False, "errors": [e["msg"] for e in exc.errors()]}
    return {"valid": True, "errors": []}
