from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..llm import AVAILABLE_MODELS
from ..models import SuggestedModel
from ..schemas import MetaOut, ToolMeta
from ..tools import REGISTRY, is_builtin

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("", response_model=MetaOut)
async def get_meta(session: AsyncSession = Depends(get_session)) -> MetaOut:
    settings = get_settings()
    model_rows = (
        (await session.execute(select(SuggestedModel).order_by(SuggestedModel.id)))
        .scalars()
        .all()
    )
    # Fall back to the built-in defaults if the user has emptied the list, so
    # the pickers are never left with zero suggestions.
    models = [m.name for m in model_rows] or list(AVAILABLE_MODELS)
    return MetaOut(
        models=models,
        tools=[
            ToolMeta(
                name=t.name,
                description=t.description,
                mutating=t.mutating,
                input_schema=t.input_schema,
                builtin=is_builtin(t.name),
            )
            for t in REGISTRY.values()
        ],
        project_roots=[str(r) for r in settings.allowed_roots()],
        api_key_configured=bool(
            settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        ),
        datadog_configured=settings.datadog_enabled,
    )
