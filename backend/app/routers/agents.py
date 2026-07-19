from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..llm import AVAILABLE_MODELS
from ..models import Agent
from ..schemas import AgentIn, AgentOut
from ..tools import REGISTRY

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _validate(payload: AgentIn) -> None:
    if payload.model not in AVAILABLE_MODELS:
        raise HTTPException(422, f"unknown model '{payload.model}'")
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
