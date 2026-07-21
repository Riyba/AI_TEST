"""Seed data (app/templates.py). Focused on the "Feature Delivery" workflow:
its graph must actually validate (GraphSpec allows the retry loops it relies
on), and the Developer agent must carry the require_approval=False override
that makes its write/run tool loop possible at all."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.graph.spec import validate_graph
from app.models import Agent, Workflow
from app.templates import seed_templates


async def _seed(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        await seed_templates(session)


async def test_seed_templates_creates_feature_delivery_workflow(session_factory) -> None:
    await _seed(session_factory)
    async with session_factory() as session:
        wf = (
            await session.execute(select(Workflow).where(Workflow.name == "Feature Delivery"))
        ).scalar_one()
    spec = validate_graph(wf.graph)  # raises on any structural problem
    assert spec.entry == "plan"


async def test_feature_delivery_loop_back_edges_present(session_factory) -> None:
    """Both failure paths (failing tests, changes-requested review) route back
    to the developer node rather than dead-ending — the whole point of the
    workflow being a loop, not a straight line."""
    await _seed(session_factory)
    async with session_factory() as session:
        wf = (
            await session.execute(select(Workflow).where(Workflow.name == "Feature Delivery"))
        ).scalar_one()
    edges = {(e["source"], e["target"], e.get("label")) for e in wf.graph["edges"]}
    assert ("tests_gate", "develop", "false") in edges
    assert ("review_gate", "develop", "false") in edges


async def test_developer_agent_has_mutating_tools_and_no_approval_gate(session_factory) -> None:
    """The Developer must be able to write files and run commands autonomously
    inside its own tool-use loop; per ARCHITECTURE.md an agent loop can't host
    a mid-loop approval interrupt, so this is opt-in and deliberate — the
    human checkpoint for this workflow is the plan approval upstream."""
    await _seed(session_factory)
    async with session_factory() as session:
        dev = (
            await session.execute(select(Agent).where(Agent.name == "Developer"))
        ).scalar_one()
    assert dev.require_approval is False
    assert "write_file" in dev.tools
    assert "run_command" in dev.tools


async def test_other_seeded_agents_default_to_require_approval(session_factory) -> None:
    """Everything except the Developer keeps the safe-mode default."""
    await _seed(session_factory)
    async with session_factory() as session:
        reviewer = (
            await session.execute(select(Agent).where(Agent.name == "Code Reviewer"))
        ).scalar_one()
        pr_gate = (
            await session.execute(
                select(Agent).where(Agent.name == "Code Reviewer (PR Gate)")
            )
        ).scalar_one()
    assert reviewer.require_approval is True
    assert pr_gate.require_approval is True


async def test_all_workflow_graphs_validate(session_factory) -> None:
    """Every seeded template — not just the new one — must still validate."""
    await _seed(session_factory)
    async with session_factory() as session:
        workflows = (await session.execute(select(Workflow))).scalars().all()
    assert len(workflows) >= 6
    for wf in workflows:
        validate_graph(wf.graph)


async def test_seeding_is_idempotent(session_factory) -> None:
    """seed_templates no-ops once templates already exist (checked by count),
    so re-running it on an existing DB never duplicates rows."""
    await _seed(session_factory)
    await _seed(session_factory)
    async with session_factory() as session:
        workflows = (await session.execute(select(Workflow))).scalars().all()
    names = [w.name for w in workflows]
    assert len(names) == len(set(names))
