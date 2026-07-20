"""Datadog metric submission and delta reconciliation (app/datadog.py).

No network: _post_series is monkeypatched to capture the series payload. The
key behaviour under test is that time-saved edits reconcile as deltas and that
a run is submitted at most once.
"""

from __future__ import annotations

import pytest

from app import datadog
from app.config import Settings
from app.models import Run, RunStep


def _settings(**overrides) -> Settings:
    base = dict(
        datadog_api_key="test-key",
        datadog_site="datadoghq.com",
        datadog_metric_prefix="agent_studio",
        datadog_tags="env:test",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def captured(monkeypatch):
    """Capture series passed to _post_series; pretend submission succeeds."""
    batches: list[list[dict]] = []

    async def fake_post(settings, series):
        batches.append(series)
        return True

    monkeypatch.setattr(datadog, "_post_series", fake_post)
    return batches


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(datadog, "get_settings", lambda: _settings())


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setattr(datadog, "get_settings", lambda: _settings(datadog_api_key=None))


def _metric(series: list[dict], suffix: str) -> dict | None:
    return next((s for s in series if s["metric"].endswith(suffix)), None)


# --------------------------------------------------------------------------- #
# sync_time_saved — the delta reconciliation                                 #
# --------------------------------------------------------------------------- #


async def test_time_saved_submits_positive_delta(enabled, captured) -> None:
    run = Run(workflow_name="wf", status="succeeded")
    await datadog.sync_time_saved(run, 20)
    assert len(captured) == 1
    point = _metric(captured[0], "workflow.time_saved_minutes")
    assert point is not None
    assert point["points"][0]["value"] == 20


async def test_time_saved_submits_negative_delta(enabled, captured) -> None:
    """Lowering an estimate reconciles by submitting a negative count."""
    run = Run(workflow_name="wf", status="succeeded")
    await datadog.sync_time_saved(run, -15)
    assert captured[0][0]["points"][0]["value"] == -15


async def test_time_saved_zero_delta_is_noop(enabled, captured) -> None:
    run = Run(workflow_name="wf", status="succeeded")
    await datadog.sync_time_saved(run, 0)
    assert captured == []  # no HTTP call when nothing changed


async def test_time_saved_disabled_is_noop(disabled, captured) -> None:
    run = Run(workflow_name="wf", status="succeeded")
    await datadog.sync_time_saved(run, 30)
    assert captured == []


async def test_time_saved_tags_include_workflow_and_status(enabled, captured) -> None:
    run = Run(workflow_name="my flow", status="succeeded")
    await datadog.sync_time_saved(run, 5)
    tags = captured[0][0]["tags"]
    assert "workflow:my flow" in tags
    assert "status:succeeded" in tags
    assert "env:test" in tags  # base tag


# --------------------------------------------------------------------------- #
# _run_series building                                                       #
# --------------------------------------------------------------------------- #


def test_run_series_includes_core_and_agent_metrics() -> None:
    settings = _settings()
    run = Run(
        workflow_name="wf",
        status="succeeded",
        total_input_tokens=100,
        total_output_tokens=40,
        time_saved_minutes=12,
    )
    steps = [
        RunStep(node_type="agent", input={"agent": "Coder"}, input_tokens=70, output_tokens=30),
        RunStep(node_type="agent", input={"agent": "Coder"}, input_tokens=30, output_tokens=10),
    ]
    series = datadog._run_series(settings, run, steps)
    metrics = {s["metric"] for s in series}
    assert "agent_studio.workflow.runs" in metrics
    assert "agent_studio.workflow.tokens.input" in metrics
    assert "agent_studio.workflow.time_saved_minutes" in metrics
    assert "agent_studio.agent.steps" in metrics
    # Two steps for the same agent are aggregated.
    steps_point = _metric(series, "agent.steps")
    assert steps_point["points"][0]["value"] == 2


def test_run_series_omits_time_saved_when_none() -> None:
    settings = _settings()
    run = Run(workflow_name="wf", status="succeeded", time_saved_minutes=None)
    series = datadog._run_series(settings, run, [])
    assert _metric(series, "workflow.time_saved_minutes") is None


def test_tag_strips_commas() -> None:
    # Commas separate tags in Datadog; a value containing one is sanitized.
    assert datadog._tag("workflow", "a,b") == "workflow:a_b"


# --------------------------------------------------------------------------- #
# sync_run — submit-once semantics                                           #
# --------------------------------------------------------------------------- #


async def test_sync_run_submits_and_flips_flag(monkeypatch, captured, session_factory) -> None:
    monkeypatch.setattr(datadog, "get_settings", lambda: _settings())
    monkeypatch.setattr(datadog, "SessionLocal", session_factory)
    async with session_factory() as session:
        run = Run(workflow_id=1, workflow_name="wf", status="succeeded", thread_id="t", synced_to_datadog=False)
        session.add(run)
        await session.commit()
        run_id = run.id

    assert await datadog.sync_run(run_id) is True
    assert len(captured) == 1

    async with session_factory() as session:
        refreshed = await session.get(Run, run_id)
        assert refreshed.synced_to_datadog is True


async def test_sync_run_is_idempotent(monkeypatch, captured, session_factory) -> None:
    monkeypatch.setattr(datadog, "get_settings", lambda: _settings())
    monkeypatch.setattr(datadog, "SessionLocal", session_factory)
    async with session_factory() as session:
        run = Run(workflow_id=1, workflow_name="wf", status="succeeded", thread_id="t", synced_to_datadog=True)
        session.add(run)
        await session.commit()
        run_id = run.id

    # Already synced → returns True but submits nothing (no double counting).
    assert await datadog.sync_run(run_id) is True
    assert captured == []


async def test_sync_run_skips_non_terminal(monkeypatch, captured, session_factory) -> None:
    monkeypatch.setattr(datadog, "get_settings", lambda: _settings())
    monkeypatch.setattr(datadog, "SessionLocal", session_factory)
    async with session_factory() as session:
        run = Run(workflow_id=1, workflow_name="wf", status="running", thread_id="t")
        session.add(run)
        await session.commit()
        run_id = run.id

    assert await datadog.sync_run(run_id) is False
    assert captured == []


async def test_sync_run_disabled(monkeypatch, captured) -> None:
    monkeypatch.setattr(datadog, "get_settings", lambda: _settings(datadog_api_key=None))
    assert await datadog.sync_run(1) is False
    assert captured == []
