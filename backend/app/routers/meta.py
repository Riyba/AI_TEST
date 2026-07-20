from __future__ import annotations

import os

from fastapi import APIRouter

from ..config import get_settings
from ..llm import AVAILABLE_MODELS
from ..schemas import MetaOut, ToolMeta
from ..tools import REGISTRY

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("", response_model=MetaOut)
async def get_meta() -> MetaOut:
    settings = get_settings()
    return MetaOut(
        models=AVAILABLE_MODELS,
        tools=[
            ToolMeta(
                name=t.name,
                description=t.description,
                mutating=t.mutating,
                input_schema=t.input_schema,
            )
            for t in REGISTRY.values()
        ],
        project_roots=[str(r) for r in settings.allowed_roots()],
        api_key_configured=bool(
            settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        ),
        datadog_configured=settings.datadog_enabled,
    )
