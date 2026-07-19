from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..attachments import MAX_ATTACHMENT_BYTES, classify
from ..db import get_session
from ..models import Agent, Attachment
from ..schemas import AttachmentOut

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    file: UploadFile,
    agent_id: int | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> Attachment:
    """Upload a file. With agent_id it belongs to that agent (sent on every
    run). Without an owner it is 'staged' and can be claimed by a new run
    via RunCreate.attachment_ids."""
    if agent_id is not None and await session.get(Agent, agent_id) is None:
        raise HTTPException(404, "agent not found")

    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            413, f"file exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit"
        )
    if not data:
        raise HTTPException(422, "file is empty")

    filename = file.filename or "file"
    try:
        kind, mime = classify(filename, file.content_type, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    attachment = Attachment(
        agent_id=agent_id,
        filename=filename[:300],
        mime_type=mime,
        kind=kind,
        size_bytes=len(data),
        data=data,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return attachment


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    agent_id: int, session: AsyncSession = Depends(get_session)
) -> list[Attachment]:
    rows = (
        (
            await session.execute(
                select(Attachment)
                .where(Attachment.agent_id == agent_id)
                .order_by(Attachment.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "attachment not found")
    if attachment.run_id is not None:
        raise HTTPException(409, "attachment belongs to a run and cannot be deleted")
    await session.delete(attachment)
    await session.commit()
