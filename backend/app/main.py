"""FastAPI app: REST API + SSE + static frontend, single process, localhost only."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import select

from .db import SessionLocal, engine
from .db import Base
from .models import CustomTool
from .routers import agents, attachments, fs, meta, metrics, runs, tools, workflows
from .templates import seed_templates
from .tools import sync_custom_tools

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on first boot (schema evolution is handled by Alembic).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_templates(session)
        # Load user-defined tools into the in-memory registry so they are
        # available to agent loops and workflow nodes from the first request.
        rows = (
            (await session.execute(select(CustomTool).order_by(CustomTool.id)))
            .scalars()
            .all()
        )
        sync_custom_tools(list(rows))
    yield
    await engine.dispose()


app = FastAPI(title="SDLC Agent Studio", lifespan=lifespan)

# Localhost-only origins: the vite dev server and the served app itself.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(attachments.router)
app.include_router(workflows.router)
app.include_router(runs.router)
app.include_router(meta.router)
app.include_router(metrics.router)
app.include_router(fs.router)
app.include_router(tools.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve the built frontend (if present) so the whole app is one process.
if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
