from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..graph.spec import validate_graph
from ..models import Workflow
from ..schemas import WorkflowIn, WorkflowOut

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


@router.post("/validate")
async def validate_workflow_graph(graph: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_graph(graph)
    except ValidationError as exc:
        return {"valid": False, "errors": [e["msg"] for e in exc.errors()]}
    return {"valid": True, "errors": []}
