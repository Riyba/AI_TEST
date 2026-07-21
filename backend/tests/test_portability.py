"""Export/import for agents, custom tools, and workflows (app/portability.py +
the export/import routes in routers/agents.py, routers/tools.py,
routers/workflows.py).

Uses a FastAPI TestClient wired to the in-memory DB (same pattern as
test_runs_api.py). The global tool REGISTRY is snapshotted/restored around
each test since import endpoints call sync_custom_tools (same pattern as
test_registry.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import get_session
from app.main import app
from app.models import Agent, CustomTool, Workflow
from app.tools.registry import REGISTRY

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def restore_registry():
    snapshot = dict(REGISTRY)
    try:
        yield
    finally:
        REGISTRY.clear()
        REGISTRY.update(snapshot)


@pytest.fixture
def client(session_factory: async_sessionmaker):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as c:
            c.session_factory = session_factory
            yield c
    finally:
        app.dependency_overrides.clear()


async def _add_tool(session_factory, **kwargs) -> CustomTool:
    defaults = dict(
        name="greet",
        description="says hi",
        input_schema={"type": "object", "properties": {}},
        mutating=False,
        source_code="def run(params):\n    return 'hi'\n",
    )
    defaults.update(kwargs)
    async with session_factory() as session:
        tool = CustomTool(**defaults)
        session.add(tool)
        await session.commit()
        await session.refresh(tool)
        return tool


async def _add_agent(session_factory, **kwargs) -> Agent:
    defaults = dict(
        name="Reviewer",
        role="reviews code",
        system_prompt="Be careful.",
        model="claude-sonnet-5",
        max_turns=10,
        max_tokens=100_000,
        tools=[],
        require_approval=True,
    )
    defaults.update(kwargs)
    async with session_factory() as session:
        agent = Agent(**defaults)
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return agent


# --------------------------------------------------------------------------- #
# Tool export/import                                                         #
# --------------------------------------------------------------------------- #


async def test_export_tool_shape(client) -> None:
    sf = client.session_factory
    tool = await _add_tool(sf)
    resp = client.get(f"/api/tools/{tool.id}/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "tool"
    assert body["tool"]["name"] == "greet"


async def test_import_tool_keeps_name_when_no_collision(client) -> None:
    sf = client.session_factory
    tool = await _add_tool(sf)
    export = client.get(f"/api/tools/{tool.id}/export").json()
    delete_resp = client.delete(f"/api/tools/{tool.id}")
    assert delete_resp.status_code == 204

    resp = client.post("/api/tools/import", json=export)
    assert resp.status_code == 201
    assert resp.json()["name"] == "greet"

    listing = client.get("/api/tools").json()
    assert {t["name"] for t in listing} == {"greet"}


async def test_import_tool_renames_on_name_collision(client) -> None:
    sf = client.session_factory
    tool = await _add_tool(sf)
    export = client.get(f"/api/tools/{tool.id}/export").json()

    resp = client.post("/api/tools/import", json=export)
    assert resp.status_code == 201
    assert resp.json()["name"] == "greet_imported"

    names = {t["name"] for t in client.get("/api/tools").json()}
    assert names == {"greet", "greet_imported"}


async def test_import_tool_rejects_wrong_format(client) -> None:
    resp = client.post(
        "/api/tools/import",
        json={"format": "workflow", "workflow": {}, "agents": [], "tools": []},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Agent export/import                                                        #
# --------------------------------------------------------------------------- #


async def test_export_agent_bundles_referenced_custom_tool(client) -> None:
    sf = client.session_factory
    await _add_tool(sf, name="my_tool")
    agent = await _add_agent(sf, tools=["read_file", "my_tool"])

    resp = client.get(f"/api/agents/{agent.id}/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "agent"
    assert body["agent"]["tools"] == ["read_file", "my_tool"]
    # Only the custom tool is bundled — read_file is a builtin.
    assert [t["name"] for t in body["tools"]] == ["my_tool"]


async def test_import_agent_round_trip_renames_on_collision(client) -> None:
    sf = client.session_factory
    await _add_tool(sf, name="my_tool")
    agent = await _add_agent(sf, name="Reviewer", tools=["read_file", "my_tool"])
    export = client.get(f"/api/agents/{agent.id}/export").json()

    resp = client.post("/api/agents/import", json=export)
    assert resp.status_code == 201
    imported = resp.json()
    assert imported["name"] == "Reviewer (imported)"
    # The bundled tool was renamed on collision, and the agent's own tools
    # list follows the rename.
    assert imported["tools"] == ["read_file", "my_tool_imported"]

    tool_names = {t["name"] for t in client.get("/api/tools").json()}
    assert tool_names == {"my_tool", "my_tool_imported"}


async def test_import_agent_rejects_unbundled_unknown_tool(client) -> None:
    export = {
        "format": "agent",
        "version": 1,
        "agent": {
            "name": "Ghost",
            "role": "",
            "system_prompt": "",
            "model": "claude-sonnet-5",
            "max_turns": 10,
            "max_tokens": 100_000,
            "tools": ["does_not_exist"],
            "require_approval": True,
        },
        "tools": [],
    }
    resp = client.post("/api/agents/import", json=export)
    assert resp.status_code == 422
    assert "unknown tools" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Workflow export/import                                                     #
# --------------------------------------------------------------------------- #


def _graph(reviewer_id: int, lead_id: int) -> dict:
    return {
        "entry": "rev",
        "nodes": [
            {"id": "rev", "type": "agent", "agent_id": reviewer_id, "prompt": "{task}"},
            {
                "id": "orch",
                "type": "orchestrator",
                "agent_id": lead_id,
                "team": [reviewer_id],
                "prompt": "{task}",
            },
            {"id": "t", "type": "tool", "tool": "greet", "params": {}},
        ],
        "edges": [
            {"source": "rev", "target": "orch"},
            {"source": "orch", "target": "t"},
        ],
    }


async def test_export_workflow_bundles_agents_and_tools(client) -> None:
    sf = client.session_factory
    await _add_tool(sf, name="greet")
    reviewer = await _add_agent(sf, name="Reviewer")
    lead = await _add_agent(sf, name="Lead", tools=[])
    graph = _graph(reviewer.id, lead.id)
    async with sf() as session:
        wf = Workflow(name="Review flow", graph=graph)
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

    resp = client.get(f"/api/workflows/{wf.id}/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "workflow"
    assert {a["id"] for a in body["agents"]} == {reviewer.id, lead.id}
    assert [t["name"] for t in body["tools"]] == ["greet"]


async def test_import_workflow_remaps_ids_and_renames_on_collision(client) -> None:
    sf = client.session_factory
    await _add_tool(sf, name="greet")
    reviewer = await _add_agent(sf, name="Reviewer")
    lead = await _add_agent(sf, name="Lead", tools=[])
    graph = _graph(reviewer.id, lead.id)
    async with sf() as session:
        wf = Workflow(name="Review flow", graph=graph)
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

    export = client.get(f"/api/workflows/{wf.id}/export").json()

    resp = client.post("/api/workflows/import", json=export)
    assert resp.status_code == 201
    imported = resp.json()
    assert imported["name"] == "Review flow (imported)"

    new_graph = imported["graph"]
    by_id = {n["id"]: n for n in new_graph["nodes"]}

    # Every id/name reference in the rewritten graph points at newly created
    # rows, not the originals (which still exist, unmodified).
    assert by_id["rev"]["agent_id"] not in (reviewer.id, None)
    assert by_id["orch"]["agent_id"] not in (lead.id, None)
    assert by_id["orch"]["team"] == [by_id["rev"]["agent_id"]]
    assert by_id["t"]["tool"] == "greet_imported"

    agent_names = {a["name"] for a in client.get("/api/agents").json()}
    assert agent_names == {"Reviewer", "Lead", "Reviewer (imported)", "Lead (imported)"}
    tool_names = {t["name"] for t in client.get("/api/tools").json()}
    assert tool_names == {"greet", "greet_imported"}


async def test_import_workflow_rejects_wrong_format(client) -> None:
    resp = client.post(
        "/api/workflows/import",
        json={"format": "tool", "tool": {"name": "x", "source_code": "def run(params): pass"}},
    )
    assert resp.status_code == 422
