"""Run endpoints (routers/runs.py): attachment claiming on create, and the
time-saved edit → Datadog reconciliation branch.

Uses a FastAPI TestClient with the session dependency overridden to the
in-memory DB. run_manager.start and the datadog calls are stubbed so no
background task or network I/O runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import datadog, runner
from app.config import Settings
from app.db import get_session
from app.main import app
from app.models import Attachment, Run, Workflow
from app.runner import run_manager

VALID_GRAPH = {
    "entry": "a",
    "nodes": [{"id": "a", "type": "agent", "agent_id": 1, "prompt": "{task}"}],
    "edges": [],
}


@pytest.fixture
def client(session_factory: async_sessionmaker, monkeypatch):
    """TestClient wired to the in-memory DB, with run execution stubbed out."""

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(run_manager, "start", lambda run_id: None)
    # Neutralize any PROJECT_ROOTS allowlist from a local .env so repo_path
    # validation accepts the test's tmp directory (any existing dir).
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(project_roots=""))
    try:
        with TestClient(app) as c:
            c.session_factory = session_factory  # expose for test setup/asserts
            yield c
    finally:
        app.dependency_overrides.clear()


async def _seed_workflow(session_factory) -> int:
    async with session_factory() as session:
        wf = Workflow(name="wf", graph=VALID_GRAPH)
        session.add(wf)
        await session.commit()
        return wf.id


async def _add_attachment(session_factory, **kwargs) -> int:
    async with session_factory() as session:
        att = Attachment(filename="f.txt", kind="text", data=b"hi", **kwargs)
        session.add(att)
        await session.commit()
        return att.id


# --------------------------------------------------------------------------- #
# Attachment claiming (staged → owned by the run)                            #
# --------------------------------------------------------------------------- #


async def test_create_run_claims_staged_attachment(client, repo: Path) -> None:
    sf = client.session_factory
    wf_id = await _seed_workflow(sf)
    att_id = await _add_attachment(sf)  # staged: no agent, no run

    resp = client.post(
        "/api/runs",
        json={"workflow_id": wf_id, "task": "t", "repo_path": str(repo), "attachment_ids": [att_id]},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    async with sf() as session:
        att = await session.get(Attachment, att_id)
        assert att.run_id == run_id  # claimed


async def test_create_run_rejects_agent_owned_attachment(client, repo: Path) -> None:
    sf = client.session_factory
    wf_id = await _seed_workflow(sf)
    att_id = await _add_attachment(sf, agent_id=1)  # already owned by an agent

    resp = client.post(
        "/api/runs",
        json={"workflow_id": wf_id, "task": "t", "repo_path": str(repo), "attachment_ids": [att_id]},
    )
    assert resp.status_code == 422
    assert "already belongs" in resp.json()["detail"]


async def test_create_run_rejects_run_owned_attachment(client, repo: Path) -> None:
    sf = client.session_factory
    wf_id = await _seed_workflow(sf)
    # Create a run and attach the file to it, then try to reuse it.
    async with sf() as session:
        other = Run(workflow_id=wf_id, workflow_name="wf", status="succeeded", thread_id="x")
        session.add(other)
        await session.flush()
        att = Attachment(filename="f.txt", kind="text", data=b"hi", run_id=other.id)
        session.add(att)
        await session.commit()
        att_id = att.id

    resp = client.post(
        "/api/runs",
        json={"workflow_id": wf_id, "task": "t", "repo_path": str(repo), "attachment_ids": [att_id]},
    )
    assert resp.status_code == 422
    assert "already belongs" in resp.json()["detail"]


async def test_create_run_rejects_unknown_attachment(client, repo: Path) -> None:
    sf = client.session_factory
    wf_id = await _seed_workflow(sf)

    resp = client.post(
        "/api/runs",
        json={"workflow_id": wf_id, "task": "t", "repo_path": str(repo), "attachment_ids": [9999]},
    )
    assert resp.status_code == 422
    assert "unknown attachments" in resp.json()["detail"]


async def test_create_run_bad_repo_path(client) -> None:
    sf = client.session_factory
    wf_id = await _seed_workflow(sf)

    resp = client.post(
        "/api/runs",
        json={"workflow_id": wf_id, "task": "t", "repo_path": "/definitely/not/a/dir"},
    )
    assert resp.status_code == 422


async def test_create_run_empty_graph(client, repo: Path) -> None:
    sf = client.session_factory
    async with sf() as session:
        wf = Workflow(name="empty", graph={})
        session.add(wf)
        await session.commit()
        wf_id = wf.id

    resp = client.post(
        "/api/runs",
        json={"workflow_id": wf_id, "task": "t", "repo_path": str(repo)},
    )
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# time-saved edits → Datadog reconciliation                                  #
# --------------------------------------------------------------------------- #


def _capture_datadog(monkeypatch):
    calls = {"delta": [], "full": []}

    async def fake_sync_time_saved(run, delta):
        calls["delta"].append(delta)

    async def fake_sync_run(run_id):
        calls["full"].append(run_id)
        return True

    monkeypatch.setattr(datadog, "sync_time_saved", fake_sync_time_saved)
    monkeypatch.setattr(datadog, "sync_run", fake_sync_run)
    return calls


async def _finished_run(session_factory, *, synced: bool, time_saved: int | None) -> int:
    async with session_factory() as session:
        run = Run(
            workflow_id=1,
            workflow_name="wf",
            status="succeeded",
            thread_id="t",
            synced_to_datadog=synced,
            time_saved_minutes=time_saved,
        )
        session.add(run)
        await session.commit()
        return run.id


async def test_time_saved_synced_run_sends_delta(client, monkeypatch) -> None:
    sf = client.session_factory
    calls = _capture_datadog(monkeypatch)
    run_id = await _finished_run(sf, synced=True, time_saved=30)

    resp = client.patch(f"/api/runs/{run_id}/time-saved", json={"time_saved_minutes": 50})
    assert resp.status_code == 200
    # Already synced → the +20 delta is reconciled, no full re-sync.
    assert calls["delta"] == [20]
    assert calls["full"] == []


async def test_time_saved_lowering_sends_negative_delta(client, monkeypatch) -> None:
    sf = client.session_factory
    calls = _capture_datadog(monkeypatch)
    run_id = await _finished_run(sf, synced=True, time_saved=40)

    resp = client.patch(f"/api/runs/{run_id}/time-saved", json={"time_saved_minutes": 10})
    assert resp.status_code == 200
    assert calls["delta"] == [-30]


async def test_time_saved_clearing_sends_negative_delta(client, monkeypatch) -> None:
    sf = client.session_factory
    calls = _capture_datadog(monkeypatch)
    run_id = await _finished_run(sf, synced=True, time_saved=25)

    resp = client.patch(f"/api/runs/{run_id}/time-saved", json={"time_saved_minutes": None})
    assert resp.status_code == 200
    assert calls["delta"] == [-25]  # cleared estimate reconciles to zero


async def test_time_saved_unsynced_run_does_full_sync(client, monkeypatch) -> None:
    sf = client.session_factory
    calls = _capture_datadog(monkeypatch)
    run_id = await _finished_run(sf, synced=False, time_saved=None)

    resp = client.patch(f"/api/runs/{run_id}/time-saved", json={"time_saved_minutes": 15})
    assert resp.status_code == 200
    # Never synced → full sync attempt (which now includes the estimate), no delta.
    assert calls["full"] == [run_id]
    assert calls["delta"] == []


async def test_time_saved_rejects_unfinished_run(client, monkeypatch) -> None:
    sf = client.session_factory
    _capture_datadog(monkeypatch)
    async with sf() as session:
        run = Run(workflow_id=1, workflow_name="wf", status="running", thread_id="t")
        session.add(run)
        await session.commit()
        run_id = run.id

    resp = client.patch(f"/api/runs/{run_id}/time-saved", json={"time_saved_minutes": 15})
    assert resp.status_code == 409


async def test_time_saved_persists_value(client, monkeypatch) -> None:
    sf = client.session_factory
    _capture_datadog(monkeypatch)
    run_id = await _finished_run(sf, synced=True, time_saved=None)

    client.patch(f"/api/runs/{run_id}/time-saved", json={"time_saved_minutes": 42})
    async with sf() as session:
        run = await session.get(Run, run_id)
        assert run.time_saved_minutes == 42
