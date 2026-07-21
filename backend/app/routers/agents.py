from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Agent, CustomTool
from ..portability import custom_tool_names_used, unique_name
from ..schemas import AgentExport, AgentIn, AgentOut, CustomToolIn
from ..tools import REGISTRY, sync_custom_tools

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _validate(payload: AgentIn) -> None:
    if not payload.model.strip():
        raise HTTPException(422, "model is required")
    unknown = [t for t in payload.tools if t not in REGISTRY]
    if unknown:
        raise HTTPException(422, f"unknown tools: {unknown}")


@router.get("", response_model=list[AgentOut])
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[Agent]:
    rows = (await session.execute(select(Agent).order_by(Agent.id))).scalars().all()
    return list(rows)


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    payload: AgentIn, session: AsyncSession = Depends(get_session)
) -> Agent:
    _validate(payload)
    agent = Agent(**payload.model_dump())
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: int, session: AsyncSession = Depends(get_session)
) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: int, payload: AgentIn, session: AsyncSession = Depends(get_session)
) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    _validate(payload)
    for key, value in payload.model_dump().items():
        setattr(agent, key, value)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    await session.delete(agent)
    await session.commit()


@router.get("/{agent_id}/export", response_model=AgentExport)
async def export_agent(
    agent_id: int, session: AsyncSession = Depends(get_session)
) -> AgentExport:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    custom_rows = (await session.execute(select(CustomTool))).scalars().all()
    used = custom_tool_names_used(agent.tools or [], {row.name for row in custom_rows})
    tools = [
        CustomToolIn.model_validate(row, from_attributes=True)
        for row in custom_rows
        if row.name in used
    ]
    return AgentExport(
        agent=AgentIn.model_validate(agent, from_attributes=True), tools=tools
    )


@router.post("/import", response_model=AgentOut, status_code=201)
async def import_agent(
    payload: AgentExport, session: AsyncSession = Depends(get_session)
) -> Agent:
    # Bundled custom tools first — renamed on collision, tracked so the
    # agent's own tool list (and, for a workflow import, its graph) can be
    # rewritten to match.
    existing_tool_names = set(
        (await session.execute(select(CustomTool.name))).scalars().all()
    )
    tool_name_map: dict[str, str] = {}
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
        session.add(CustomTool(**data))

    existing_agent_names = set(
        (await session.execute(select(Agent.name))).scalars().all()
    )
    agent_data = payload.agent.model_dump()
    if not agent_data["model"].strip():
        raise HTTPException(422, "model is required")
    agent_data["name"] = unique_name(
        agent_data["name"].strip(), existing_agent_names, "human"
    )
    agent_data["tools"] = [tool_name_map.get(t, t) for t in agent_data["tools"]]
    unknown = [
        t for t in agent_data["tools"] if t not in REGISTRY and t not in added_tool_names
    ]
    if unknown:
        raise HTTPException(422, f"unknown tools: {unknown}")

    agent = Agent(**agent_data)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    if added_tool_names:
        rows = (await session.execute(select(CustomTool))).scalars().all()
        sync_custom_tools(list(rows))
    return agent
