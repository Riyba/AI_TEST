"""Datadog sync for application metrics (see DATADOG.md).

Pushes the app's business metrics — runs, token usage, time saved, per-agent
usage — as custom metrics to Datadog's metrics intake API (v2 series). No
Datadog Agent, APM, or error tracking is involved: this submits only the
application-specific metrics, over one HTTPS call per finished run.

Sync model:
- When a run reaches a terminal status the runner calls `sync_run`, which
  submits one batch of series for that run and, on acceptance, flips
  `Run.synced_to_datadog`. A run is never submitted twice (the flag is the
  guard), so counts in Datadog are never double-counted.
- A time-saved estimate is usually captured *after* the run finished, so the
  time-saved PATCH endpoint submits the delta separately (`sync_time_saved`).
- Everything here is best-effort: failures are logged and leave
  `synced_to_datadog` False; POST /api/runs/{id}/datadog-sync retries.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from sqlalchemy import select

from .config import Settings, get_settings
from .db import SessionLocal
from .models import TERMINAL_STATUSES, Run, RunStep

log = logging.getLogger(__name__)

# Datadog v2 series metric types.
_COUNT = 1
_GAUGE = 3

_TIMEOUT_SECONDS = 5.0


def _intake_url(settings: Settings) -> str:
    return f"https://api.{settings.datadog_site}/api/v2/series"


def _tag(key: str, value: str) -> str:
    # Commas separate tags in Datadog; strip them from values defensively.
    cleaned = str(value).strip().replace(",", "_") or "unknown"
    return f"{key}:{cleaned}"


def _series(
    settings: Settings,
    name: str,
    value: float,
    tags: list[str],
    *,
    type_: int = _COUNT,
    ts: int,
) -> dict[str, Any]:
    return {
        "metric": f"{settings.datadog_metric_prefix}.{name}",
        "type": type_,
        "points": [{"timestamp": ts, "value": value}],
        "tags": tags + settings.datadog_base_tags(),
    }


def _run_series(settings: Settings, run: Run, steps: list[RunStep]) -> list[dict[str, Any]]:
    ts = int(time.time())
    wf_tags = [_tag("workflow", run.workflow_name), _tag("status", run.status)]
    series = [
        _series(settings, "workflow.runs", 1, wf_tags, ts=ts),
        _series(settings, "workflow.tokens.input", run.total_input_tokens, wf_tags, ts=ts),
        _series(settings, "workflow.tokens.output", run.total_output_tokens, wf_tags, ts=ts),
    ]
    if run.finished_at is not None:
        duration = (run.finished_at - run.created_at).total_seconds()
        series.append(
            _series(
                settings, "workflow.duration_seconds", max(duration, 0.0),
                wf_tags, type_=_GAUGE, ts=ts,
            )
        )
    # NULL = the user never captured an estimate; nothing is submitted, and
    # sync_time_saved sends the value if it is captured later.
    if run.time_saved_minutes is not None:
        series.append(
            _series(
                settings, "workflow.time_saved_minutes", run.time_saved_minutes,
                wf_tags, ts=ts,
            )
        )

    # Per-agent usage, attributed via the agent name recorded in each agent
    # step's input (same attribution as /api/metrics).
    agent_totals: dict[str, dict[str, int]] = {}
    for step in steps:
        name = str(step.input.get("agent") or "(unknown agent)")
        totals = agent_totals.setdefault(name, {"steps": 0, "input": 0, "output": 0})
        totals["steps"] += 1
        totals["input"] += step.input_tokens
        totals["output"] += step.output_tokens
    for name, totals in agent_totals.items():
        agent_tags = [_tag("agent", name), _tag("workflow", run.workflow_name)]
        series += [
            _series(settings, "agent.steps", totals["steps"], agent_tags, ts=ts),
            _series(settings, "agent.tokens.input", totals["input"], agent_tags, ts=ts),
            _series(settings, "agent.tokens.output", totals["output"], agent_tags, ts=ts),
        ]
    return series


async def _post_series(settings: Settings, series: list[dict[str, Any]]) -> bool:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _intake_url(settings),
                json={"series": series},
                headers={"DD-API-KEY": settings.datadog_api_key or ""},
            )
        if response.is_success:
            return True
        log.warning(
            "Datadog rejected metrics: HTTP %s %s",
            response.status_code,
            response.text[:500],
        )
    except httpx.HTTPError as exc:
        log.warning("Datadog submission failed: %s", exc)
    return False


async def sync_run(run_id: int) -> bool:
    """Submit a finished run's metrics to Datadog once.

    Returns True when the run is synced (now or previously). No-op (False)
    when the integration is disabled or the run is not terminal; submission
    failures are logged, never raised.
    """
    settings = get_settings()
    if not settings.datadog_enabled:
        return False
    try:
        async with SessionLocal() as session:
            run = await session.get(Run, run_id)
            if run is None or run.status not in TERMINAL_STATUSES:
                return False
            if run.synced_to_datadog:
                return True
            steps = (
                (
                    await session.execute(
                        select(RunStep).where(
                            RunStep.run_id == run_id, RunStep.node_type == "agent"
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not await _post_series(settings, _run_series(settings, run, list(steps))):
                return False
            run.synced_to_datadog = True
            await session.commit()
            return True
    except Exception:  # noqa: BLE001 — sync must never break run handling
        log.exception("Datadog sync failed for run %s", run_id)
        return False


async def sync_time_saved(run: Run, delta_minutes: int) -> None:
    """Submit a change to an already-synced run's time-saved estimate.

    Counts are additive in Datadog, so edits are reconciled by submitting the
    delta (negative when the estimate was lowered or cleared). Best-effort.
    """
    settings = get_settings()
    if not settings.datadog_enabled or delta_minutes == 0:
        return
    series = [
        _series(
            settings,
            "workflow.time_saved_minutes",
            delta_minutes,
            [_tag("workflow", run.workflow_name), _tag("status", run.status)],
            ts=int(time.time()),
        )
    ]
    await _post_series(settings, series)
