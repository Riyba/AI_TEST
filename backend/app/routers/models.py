"""CRUD for the editable list of suggested models.

These rows only drive the model-picker suggestions surfaced via /api/meta and in
the agent / tool-builder forms. They are advisory: an agent may be saved with
any model string, so adding or removing a suggestion never rewrites or breaks
existing agents.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import SuggestedModel
from ..schemas import SuggestedModelIn, SuggestedModelOut

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[SuggestedModelOut])
async def list_models(
    session: AsyncSession = Depends(get_session),
) -> list[SuggestedModel]:
    rows = (
        (await session.execute(select(SuggestedModel).order_by(SuggestedModel.id)))
        .scalars()
        .all()
    )
    return list(rows)


@router.post("", response_model=SuggestedModelOut, status_code=201)
async def create_model(
    payload: SuggestedModelIn, session: AsyncSession = Depends(get_session)
) -> SuggestedModel:
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "model name is required")
    if len(name) > 100:
        raise HTTPException(422, "model name must be 100 characters or fewer")
    existing = (
        await session.execute(
            select(SuggestedModel).where(SuggestedModel.name == name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"'{name}' is already suggested")
    model = SuggestedModel(name=name)
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    model = await session.get(SuggestedModel, model_id)
    if model is None:
        raise HTTPException(404, "model not found")
    await session.delete(model)
    await session.commit()
