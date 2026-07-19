from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import SessionLocal, get_session
from ..events import bus
from ..models import Run, Workflow
from ..runner import TERMINAL_STATUSES, run_manager, validate_repo_path
from ..schemas import ApprovalDecision, RunCreate, RunDetail, RunOut, TimeSavedIn

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=RunOut, status_code=201)
async def create_run(
    payload: RunCreate, session: AsyncSession = Depends(get_session)
) -> Run:
    workflow = await session.get(Workflow, payload.workflow_id)
    if workflow is None:
        raise HTTPException(404, "workflow not found")
    if not workflow.graph or not workflow.graph.get("nodes"):
        raise HTTPException(422, "workflow graph is empty")
    try:
        validate_repo_path(payload.repo_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    run = Run(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        status="pending",
        input={"task": payload.task, "repo_path": payload.repo_path},
        thread_id=uuid.uuid4().hex,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    run_manager.start(run.id)
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[Run]:
    rows = (
        (await session.execute(select(Run).order_by(Run.id.desc()).limit(200)))
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)) -> Run:
    run = (
        await session.execute(
            select(Run)
            .where(Run.id == run_id)
            .options(selectinload(Run.steps), selectinload(Run.artifacts))
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.get("/{run_id}/events")
async def run_events(run_id: int) -> StreamingResponse:
    """SSE stream: replays in-memory history, then live events until terminal."""
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        already_terminal = run.status in TERMINAL_STATUSES and not run_manager.is_active(
            run_id
        )

    history, queue = bus.subscribe(run_id)

    async def generate():
        try:
            for event in history:
                yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
            if already_terminal:
                yield "event: done\ndata: {}\n\n"
                return
            while True:
                event = await queue.get()
                if event is None:
                    yield "event: done\ndata: {}\n\n"
                    return
                yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
        finally:
            bus.unsubscribe(run_id, queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/approval", response_model=RunOut)
async def submit_approval(
    run_id: int,
    payload: ApprovalDecision,
    session: AsyncSession = Depends(get_session),
) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "waiting_approval":
        raise HTTPException(409, f"run is not waiting for approval (status={run.status})")
    if run_manager.is_active(run_id):
        raise HTTPException(409, "run is still executing")

    run_manager.resume(run_id, payload.model_dump())
    await session.refresh(run)
    return run


@router.patch("/{run_id}/time-saved", response_model=RunOut)
async def set_time_saved(
    run_id: int,
    payload: TimeSavedIn,
    session: AsyncSession = Depends(get_session),
) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status not in TERMINAL_STATUSES:
        raise HTTPException(409, f"run has not finished (status={run.status})")
    run.time_saved_minutes = payload.time_saved_minutes
    await session.commit()
    await session.refresh(run)
    return run


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: int, session: AsyncSession = Depends(get_session)
) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(409, f"run already finished (status={run.status})")
    await run_manager.cancel(run_id)
    await session.refresh(run)
    return run
