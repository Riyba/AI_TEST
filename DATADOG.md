# Datadog integration

The app can push its **application metrics** — workflow runs, token usage,
user-estimated time savings, and per-agent usage — to Datadog as custom
metrics. That is the entire scope: no APM traces, no error tracking, no
host/system metrics, and no Datadog Agent is required. Metrics are submitted
directly to Datadog's metrics intake API (v2 `series` endpoint) over HTTPS.

The integration is **off by default**. Without `DATADOG_API_KEY` set, the app
makes no Datadog network calls at all.

## Setup

### 1. Get a Datadog API key

1. Log in to Datadog and go to **Organization Settings → API Keys**
   (`https://app.<your-site>/organization-settings/api-keys`).
2. Create (or copy) an API key. A plain **API key** is all that's needed —
   metric submission does not use an Application key.
3. Note which **site** your account is on; it's the domain you log in at:

   | You log in at              | `DATADOG_SITE` value |
   |----------------------------|----------------------|
   | app.datadoghq.com          | `datadoghq.com` (default) |
   | app.datadoghq.eu           | `datadoghq.eu`       |
   | us3.datadoghq.com          | `us3.datadoghq.com`  |
   | us5.datadoghq.com          | `us5.datadoghq.com`  |
   | ap1.datadoghq.com          | `ap1.datadoghq.com`  |

### 2. Configure the backend

Add to `backend/.env` (see `backend/.env.example`):

```ini
DATADOG_API_KEY=<your api key>
# Only needed if your account is not on the default US1 site:
DATADOG_SITE=datadoghq.com
# Optional: change the prefix of every metric name (default agent_studio):
DATADOG_METRIC_PREFIX=agent_studio
# Optional: extra tags applied to every metric, comma-separated:
DATADOG_TAGS=env:dev
```

Restart the backend. That's it — the next run that finishes will be synced.
`GET /api/meta` reports `datadog_configured: true` when the key is picked up,
and the Runs page shows a **Datadog** column.

### 3. Verify

Finish any workflow run, then in Datadog open **Metrics → Summary** and search
for `agent_studio.` (or your prefix). New custom metrics can take a minute or
two to appear the first time. In the app, the run shows **✓ synced** in the
Runs table.

## Metrics reference

All metric names below are prefixed with `DATADOG_METRIC_PREFIX`
(default `agent_studio`). Counts are additive: summing them over any time
window gives the true total for that window.

| Metric | Type | Tags | Meaning |
|---|---|---|---|
| `workflow.runs` | count | `workflow`, `status` | One per finished run (status: succeeded / failed / rejected / cancelled) |
| `workflow.tokens.input` | count | `workflow`, `status` | Input tokens consumed by the run |
| `workflow.tokens.output` | count | `workflow`, `status` | Output tokens produced by the run |
| `workflow.duration_seconds` | gauge | `workflow`, `status` | Wall-clock run duration (created → finished) |
| `workflow.time_saved_minutes` | count | `workflow`, `status` | User-estimated time saved. Only submitted when an estimate was captured; later edits are reconciled by submitting the delta |
| `agent.steps` | count | `agent`, `workflow` | Agent steps executed in the run, per agent |
| `agent.tokens.input` | count | `agent`, `workflow` | Input tokens attributed to the agent |
| `agent.tokens.output` | count | `agent`, `workflow` | Output tokens attributed to the agent |

Notes:

- Agent attribution uses the agent **name** recorded on each step at execution
  time (same as the in-app metrics page), so renamed or deleted agents keep
  their history.
- Points are timestamped at submission time, which is normally the moment the
  run finishes. A manually retried sync (see below) lands at retry time.
- Runs where the user never captured a time-saved estimate submit **no**
  `workflow.time_saved_minutes` point at all, so "no estimate" never skews
  averages as a zero.

## How syncing works

- When a run reaches a terminal status (succeeded, failed, rejected,
  cancelled), the backend submits that run's metrics in one batch and sets the
  run's `synced_to_datadog` flag on success. A synced run is never submitted
  again, so nothing is double-counted.
- Time-saved estimates are usually entered *after* the run finishes. Saving or
  editing an estimate submits just the difference to
  `workflow.time_saved_minutes` (a negative point if the estimate was lowered
  or cleared); if the run had never synced (e.g. Datadog was down or not yet
  configured), the full sync is attempted instead.
- Failures are best-effort by design: a Datadog outage never blocks or fails a
  run — the error is logged and the run stays **not synced**.
- Retry: the Runs table shows **not synced — retry** on finished runs, or call
  `POST /api/runs/{id}/datadog-sync`. Runs that finished before the
  integration was configured can be backfilled the same way (their points get
  the retry timestamp, not the original finish time).

The sync state is exposed on the API (`synced_to_datadog` on run objects) and
in the UI (Runs table column and the run detail header, shown only when the
integration is configured).

## Suggested Datadog dashboard

Create a new dashboard and add these queries (adjust the prefix if changed):

- **Runs per day, by workflow** — timeseries (bars, daily rollup):
  `sum:agent_studio.workflow.runs{*} by {workflow}.as_count()`
- **Success rate** — query value:
  `sum:agent_studio.workflow.runs{status:succeeded}.as_count() / sum:agent_studio.workflow.runs{*}.as_count() * 100`
- **Time saved per week** — timeseries (bars, weekly rollup):
  `sum:agent_studio.workflow.time_saved_minutes{*}.as_count()`
  (divide by 60 with a formula for hours)
- **Token spend by agent** — top list:
  `sum:agent_studio.agent.tokens.input{*} by {agent}.as_count() + sum:agent_studio.agent.tokens.output{*} by {agent}.as_count()`
- **Median run duration by workflow** — timeseries:
  `median:agent_studio.workflow.duration_seconds{*} by {workflow}`

Useful monitors: alert on `sum:agent_studio.workflow.runs{status:failed}.as_count()`
exceeding a threshold over a day.

## Troubleshooting

- **Runs stay "not synced"** — check the backend logs: rejected submissions
  log `Datadog rejected metrics: HTTP <status>`, network problems log
  `Datadog submission failed`. HTTP 403 means a wrong API key **or the wrong
  `DATADOG_SITE`** (a key from one site is invalid on another).
- **`datadog_configured` is false** — the env var isn't reaching the process;
  confirm it's in `backend/.env` (or the environment) and restart.
- **Metrics not visible in Datadog** — first-time custom metrics take a few
  minutes to be indexed; check **Metrics → Summary** rather than a dashboard.
- **Custom-metric billing** — cardinality is bounded by
  workflows × statuses + agents × workflows, tiny for a single-user tool, but
  every distinct tag combination is a billable custom metric in Datadog.
