"""Run execution engine.

Each run executes as a background asyncio task streaming LangGraph events.
State is checkpointed to SQLite (per-run thread_id), so a run paused at a
human-approval interrupt can resume later — even across server restarts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from sqlalchemy import select, update

from . import datadog
from .attachments import AttachmentContent
from .config import get_settings
from .db import SessionLocal
from .events import bus
from .graph.builder import build_graph
from .graph.nodes import AgentDef, RunContext, RunRejectedError
from .graph.spec import GraphSpec, validate_graph
from .llm import get_provider
from .models import TERMINAL_STATUSES, Agent, Artifact, Attachment, Run, Workflow


def validate_repo_path(raw: str) -> Path:
    settings = get_settings()
    roots = settings.allowed_roots()
    if not roots:
        raise ValueError(
            "PROJECT_ROOTS is not configured. Set it in backend/.env to the "
            "directories runs are allowed to target."
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"repo_path is not a directory: {raw}")
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError(
            f"repo_path must be inside one of PROJECT_ROOTS: {[str(r) for r in roots]}"
        )
    return path


class RunManager:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def start(self, run_id: int) -> None:
        self._spawn(run_id, resume_payload=None)

    def resume(self, run_id: int, payload: dict[str, Any]) -> None:
        self._spawn(run_id, resume_payload=payload)

    def is_active(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def _spawn(self, run_id: int, resume_payload: dict[str, Any] | None) -> None:
        if self.is_active(run_id):
            raise RuntimeError(f"run {run_id} is already executing")
        task = asyncio.create_task(self._execute(run_id, resume_payload))
        self._tasks[run_id] = task

    async def cancel(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        cancelled = False
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            cancelled = True
        await _set_status(run_id, "cancelled", finished=True)
        await datadog.sync_run(run_id)
        bus.emit(run_id, "run_status", status="cancelled")
        bus.close(run_id)
        return cancelled

    async def _execute(
        self, run_id: int, resume_payload: dict[str, Any] | None
    ) -> None:
        settings = get_settings()
        try:
            async with SessionLocal() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return
                workflow = await session.get(Workflow, run.workflow_id)
                if workflow is None:
                    raise ValueError("workflow no longer exists")
                spec = validate_graph(workflow.graph)
                agents = await _load_agents(session, spec)
                run_attachments = await _load_attachments(
                    session, run_id=run_id
                )
                repo_path = validate_repo_path(str(run.input.get("repo_path", "")))
                thread_id = run.thread_id
                task_text = str(run.input.get("task", ""))

            ctx = RunContext(
                run_id=run_id,
                repo_path=repo_path,
                agents=agents,
                provider=get_provider(),
                bus=bus,
                session_factory=SessionLocal,
                run_attachments=run_attachments,
            )

            await _set_status(run_id, "running")
            bus.emit(run_id, "run_status", status="running")

            interrupt_value: dict[str, Any] | None = None
            last_output = ""

            async with AsyncSqliteSaver.from_conn_string(
                str(settings.checkpoint_db_path)
            ) as saver:
                graph = build_graph(spec, ctx).compile(checkpointer=saver)
                config = {"configurable": {"thread_id": thread_id}}
                stream_input: Any
                if resume_payload is not None:
                    stream_input = Command(resume=resume_payload)
                else:
                    stream_input = {
                        "task": task_text,
                        "repo_path": str(repo_path),
                        "node_outputs": {},
                        "last_output": "",
                        "last_tool_success": True,
                    }

                async for chunk in graph.astream(
                    stream_input, config, stream_mode="updates"
                ):
                    if "__interrupt__" in chunk:
                        interrupts = chunk["__interrupt__"]
                        interrupt_value = (
                            interrupts[0].value if interrupts else {"kind": "approval"}
                        )
                        continue
                    for node_update in chunk.values():
                        if isinstance(node_update, dict) and "last_output" in node_update:
                            last_output = node_update["last_output"]

            if interrupt_value is not None:
                await _set_status(run_id, "waiting_approval")
                bus.emit(run_id, "run_status", status="waiting_approval")
                bus.emit(run_id, "approval_requested", payload=interrupt_value)
                return  # stream stays open; resume() picks up from the checkpoint

            if last_output:
                async with SessionLocal() as session:
                    session.add(
                        Artifact(
                            run_id=run_id,
                            name="final_output",
                            kind="text",
                            content=last_output,
                        )
                    )
                    await session.commit()
            await _set_status(run_id, "succeeded", finished=True)
            # Best-effort, before run_finished so watchers refetch the synced flag.
            await datadog.sync_run(run_id)
            bus.emit(run_id, "run_status", status="succeeded")
            bus.emit(run_id, "run_finished", status="succeeded")
            bus.close(run_id)

        except asyncio.CancelledError:
            raise  # cancel() handles status + events
        except RunRejectedError as exc:
            await _set_status(run_id, "rejected", finished=True, error=str(exc))
            await datadog.sync_run(run_id)
            bus.emit(run_id, "run_status", status="rejected", error=str(exc))
            bus.emit(run_id, "run_finished", status="rejected")
            bus.close(run_id)
        except Exception as exc:  # noqa: BLE001 — surface any failure on the run
            await _set_status(run_id, "failed", finished=True, error=str(exc))
            await datadog.sync_run(run_id)
            bus.emit(run_id, "run_status", status="failed", error=str(exc))
            bus.emit(run_id, "run_finished", status="failed")
            bus.close(run_id)


async def _load_agents(session: Any, spec: GraphSpec) -> dict[int, AgentDef]:
    agent_ids = {n.agent_id for n in spec.nodes if n.type == "agent" and n.agent_id}
    if not agent_ids:
        return {}
    rows = (
        (await session.execute(select(Agent).where(Agent.id.in_(agent_ids))))
        .scalars()
        .all()
    )
    found = {
        a.id: AgentDef(
            id=a.id,
            name=a.name,
            role=a.role,
            system_prompt=a.system_prompt,
            model=a.model,
            max_turns=a.max_turns,
            max_tokens=a.max_tokens,
            tools=list(a.tools or []),
            require_approval=a.require_approval,
            attachments=await _load_attachments(session, agent_id=a.id),
        )
        for a in rows
    }
    missing = agent_ids - set(found)
    if missing:
        raise ValueError(f"workflow references missing agents: {sorted(missing)}")
    return found


async def _load_attachments(
    session: Any, *, run_id: int | None = None, agent_id: int | None = None
) -> list[AttachmentContent]:
    query = select(Attachment).order_by(Attachment.id)
    if run_id is not None:
        query = query.where(Attachment.run_id == run_id)
    else:
        query = query.where(Attachment.agent_id == agent_id)
    rows = (await session.execute(query)).scalars().all()
    return [
        AttachmentContent(
            filename=a.filename, mime_type=a.mime_type, kind=a.kind, data=a.data
        )
        for a in rows
    ]


async def _set_status(
    run_id: int, status: str, *, finished: bool = False, error: str | None = None
) -> None:
    values: dict[str, Any] = {"status": status}
    if finished:
        values["finished_at"] = datetime.now(timezone.utc)
    if error is not None:
        values["error"] = error[:10_000]
    async with SessionLocal() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(**values))
        await session.commit()


run_manager = RunManager()
