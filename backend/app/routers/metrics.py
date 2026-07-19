"""Usage metrics, aggregated on demand.

The dataset is small (a few hundred runs at most), so aggregation happens in
Python over one query per table rather than SQL group-bys — simpler to keep
correct, and the endpoint is only hit when the metrics page is opened.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Run, RunStep
from ..schemas import (
    AgentMetrics,
    DayMetrics,
    MetricsOut,
    MetricsTotals,
    WorkflowMetrics,
)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=MetricsOut)
async def get_metrics(session: AsyncSession = Depends(get_session)) -> MetricsOut:
    runs = (await session.execute(select(Run))).scalars().all()

    by_status: dict[str, int] = defaultdict(int)
    days: dict[str, DayMetrics] = {}
    workflows: dict[str, WorkflowMetrics] = {}
    total_in = total_out = total_saved = captured = 0

    for run in runs:
        by_status[run.status] += 1
        total_in += run.total_input_tokens
        total_out += run.total_output_tokens
        # NULL time_saved_minutes = never captured; excluded from time metrics.
        has_saved = run.time_saved_minutes is not None
        saved = run.time_saved_minutes or 0
        if has_saved:
            captured += 1
            total_saved += saved

        day = run.created_at.date().isoformat()
        d = days.setdefault(
            day,
            DayMetrics(
                date=day, runs=0, input_tokens=0, output_tokens=0,
                time_saved_minutes=0, runs_with_time_saved=0,
            ),
        )
        d.runs += 1
        d.input_tokens += run.total_input_tokens
        d.output_tokens += run.total_output_tokens
        if has_saved:
            d.time_saved_minutes += saved
            d.runs_with_time_saved += 1

        w = workflows.setdefault(
            run.workflow_name,
            WorkflowMetrics(
                workflow_name=run.workflow_name, runs=0, succeeded=0,
                input_tokens=0, output_tokens=0,
                time_saved_minutes=0, runs_with_time_saved=0,
            ),
        )
        w.runs += 1
        if run.status == "succeeded":
            w.succeeded += 1
        w.input_tokens += run.total_input_tokens
        w.output_tokens += run.total_output_tokens
        if has_saved:
            w.time_saved_minutes += saved
            w.runs_with_time_saved += 1

    # Agent usage comes from agent steps; the agent's name is recorded in the
    # step input (see nodes.py) so renamed/deleted agents still attribute.
    steps = (
        (await session.execute(select(RunStep).where(RunStep.node_type == "agent")))
        .scalars()
        .all()
    )
    agents: dict[str, AgentMetrics] = {}
    agent_runs: dict[str, set[int]] = defaultdict(set)
    for step in steps:
        name = str(step.input.get("agent") or "(unknown agent)")
        a = agents.setdefault(
            name,
            AgentMetrics(agent=name, steps=0, runs=0, input_tokens=0, output_tokens=0),
        )
        a.steps += 1
        a.input_tokens += step.input_tokens
        a.output_tokens += step.output_tokens
        agent_runs[name].add(step.run_id)
    for name, a in agents.items():
        a.runs = len(agent_runs[name])

    return MetricsOut(
        totals=MetricsTotals(
            runs=len(runs),
            runs_by_status=dict(by_status),
            input_tokens=total_in,
            output_tokens=total_out,
            time_saved_minutes=total_saved,
            runs_with_time_saved=captured,
        ),
        by_day=sorted(days.values(), key=lambda d: d.date),
        by_workflow=sorted(
            workflows.values(),
            key=lambda w: w.input_tokens + w.output_tokens,
            reverse=True,
        ),
        by_agent=sorted(
            agents.values(),
            key=lambda a: a.input_tokens + a.output_tokens,
            reverse=True,
        ),
    )
