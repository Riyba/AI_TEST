# Architecture

One FastAPI process serves the REST API, an SSE stream per run, and the built React
frontend. LangGraph executes workflows as background asyncio tasks in the same
process (single-user local tool — no worker queue needed).

```
frontend (React Flow editor, run views)
        │  REST + SSE (/api/…)
        ▼
FastAPI routers ── runner.RunManager ── LangGraph StateGraph
        │                │                  │
   SQLAlchemy       events.RunEventBus   AsyncSqliteSaver
   (app.db)         (in-memory pub/sub)  (checkpoints.db)
```

## Data model (SQLite, `backend/data/app.db`)

- **agents** — name, role, system prompt, model, per-run limits (`max_turns`,
  `max_tokens`), tool permissions, `require_approval` (safe mode).
- **workflows** — a `graph` JSON column holding the GraphSpec below. `is_template`
  marks seeded starters; cloning copies the graph.
- **runs** — status, input (`task`, `repo_path`), `thread_id` (checkpointer key),
  token totals, error, `time_saved_minutes` (user-estimated; NULL = never
  captured, and excluded from time-savings metrics).
- **run_steps** — one row per executed node: input, output, tool-call log,
  per-step token usage, timestamps. This is the durable trace used for replay.
- **artifacts** — files written by tools, plus the run's `final_output` text.
- **attachments** — uploaded files (image/pdf/text, ≤5 MB, blob stored in the
  row) owned by an agent (sent on every run), by a run (attached at launch), or
  by neither yet ("staged": uploaded from the launch form, claimed by
  `POST /api/runs` via `attachment_ids`; stale staged rows are just orphans).

Schema changes: Alembic (`backend/alembic/`), initial revision auto-generated from
the models. At startup `create_all` covers the fresh-install case.

## Graph JSON schema (`app/graph/spec.py`)

A workflow's `graph` column maps 1:1 onto a LangGraph `StateGraph`:

```jsonc
{
  "entry": "diff",
  "nodes": [
    {"id": "diff",   "type": "tool",      "tool": "git_diff", "params": {}},
    {"id": "review", "type": "agent",     "agent_id": 3, "prompt": "Review:\n{diff}"},
    {"id": "gate",   "type": "approval",  "message": "Ship it?"},
    {"id": "check",  "type": "condition", "predicate": {"kind": "tool_success", "value": ""}}
  ],
  "edges": [
    {"source": "diff",  "target": "review"},
    {"source": "check", "target": "a", "label": "true"},
    {"source": "check", "target": "b", "label": "false"}
  ]
}
```

Rules (validated server-side, surfaced in the editor):

- Node types: `agent`, `tool`, `condition`, `approval`.
- A `condition` node has exactly two outgoing edges labeled `true`/`false` and
  becomes `add_conditional_edges` with a router reading `state["route"]`.
- Every other node has at most one outgoing edge; nodes with none flow to `END`.
- Node `position` is editor layout only; the backend ignores it semantically.

`app/graph/builder.py` walks the spec and registers node functions produced by the
factories in `app/graph/nodes.py`.

### State

All nodes share one `WorkflowState` (`app/graph/state.py`): `task`, `repo_path`,
`node_outputs` (node_id → output text, merged with a reducer), `last_output`,
`last_tool_success`, `route`. Prompt templates and tool params are rendered with
`{task}`, `{repo_path}`, `{last_output}`, and `{<node_id>}` placeholders
(`nodes.render`, unknown placeholders pass through unchanged).

### Node semantics

- **agent** — builds the system prompt from the Agent row, renders the node's
  prompt template, and prepends run + agent attachments to the first user
  message as content blocks (`app/attachments.py`: images/PDFs as base64
  blocks, text inlined), then runs a bounded tool-use loop against the
  Anthropic API:
  the model's `tool_use` blocks are dispatched to the registry, results are fed
  back, until the model stops calling tools (or `MAX_TOOL_ITERATIONS`). The
  agent's permitted toolset excludes mutating tools when `require_approval` is on.
- **tool** — renders params, then executes one registry tool. If the tool is
  mutating and the node's `require_approval` is true, it interrupts first (below).
- **condition** — evaluates its predicate (`tool_success`, `output_contains`,
  `output_not_contains`) and writes `route` for the edge router.
- **approval** — interrupts with a rendered message plus the current
  `last_output`; the reviewer can approve, reject, or replace the output.

## Checkpointing, interrupts, resume

Each run gets a UUID `thread_id`. Graphs are compiled with LangGraph's
`AsyncSqliteSaver` (`backend/data/checkpoints.db`), so every super-step is
checkpointed under that thread.

Human-in-the-loop uses `langgraph.types.interrupt(payload)`:

1. The runner streams `graph.astream(...)` and, on seeing `__interrupt__`, sets
   the run to `waiting_approval`, emits an `approval_requested` SSE event with the
   interrupt payload, and lets the task end.
2. `POST /api/runs/{id}/approval` calls
   `graph.astream(Command(resume=decision), config)` in a fresh task; LangGraph
   reloads the thread's checkpoint and re-executes the interrupted node, with
   `interrupt()` now returning the decision. Because the checkpoint is on disk,
   this works even after a server restart.

**Invariant to preserve:** LangGraph replays the whole node function on resume, so
`interrupt()` must be the *first* effectful thing in any node. That is also why
safe-mode agents don't get mutating tools inside their LLM loop — an interrupt in
the middle of a multi-call loop would replay earlier LLM calls on every resume.
Rejection raises `RunRejectedError`, which the runner records as status `rejected`.

## Events & observability

`app/events.py` is a tiny per-run pub/sub: node executors and the runner emit
typed events (`run_status`, `node_started`, `node_finished`, `tool_call`,
`tool_result`, `llm_usage`, `approval_requested`, `artifact`, `run_finished`).
`GET /api/runs/{id}/events` is an SSE stream that replays the in-memory history
then tails live events; a `done` SSE event closes it. Durable history is the
`run_steps`/`artifacts` tables, which the run-detail page renders for finished
runs (and after restarts, when in-memory history is gone).

## Tool layer & sandboxing (`app/tools/`)

`registry.py` holds `Tool` records: name, description, JSON schema (reused as the
Anthropic tool definition), a `mutating` flag, and a sync handler run via
`asyncio.to_thread`. Enforcement:

- `fs.resolve_jailed()` — resolves every model-supplied path and requires it to
  stay under the run's repo; used by all file tools.
- `shell.py` — `shlex` parsing, **no shell**, bare-name executables checked
  against an allowlist, output caps and timeouts.
- Runs are only accepted for repos inside `PROJECT_ROOTS` (`runner.validate_repo_path`).
- The `mutating` flag drives both approval gating and safe-mode filtering.

### Adding a new tool

1. Implement a handler `(root: Path, params: dict) -> tuple[bool, str]` in an
   `app/tools/` module, jailing any paths with `resolve_jailed`.
2. `_register(Tool(...))` it in `registry.py` with a JSON schema and the correct
   `mutating` flag — set `mutating=True` if it writes, executes, or touches
   anything outside pure reads.
3. Done: it appears in `/api/meta`, the agent editor's permission list, and the
   workflow editor's tool-node dropdown automatically.

## LLM layer (`app/llm.py`)

`LLMProvider` is a one-method protocol (`complete(...) -> LLMResponse`);
`AnthropicProvider` is the default implementation. Swapping providers means
implementing that protocol — graph code never touches an SDK type beyond the
opaque `raw_content` it echoes back for tool loops. Per-agent run limits are
enforced in the agent node loop (`app/graph/nodes.py`): `max_turns` caps loop
iterations and `max_tokens` is an input+output token budget per run.

## Frontend

- `src/pages/WorkflowEditorPage.tsx` — React Flow canvas ⇄ GraphSpec
  serialization; the inspector edits the selected node's spec fields; condition
  edges are auto-labeled true/false; save round-trips through server-side
  validation.
- `src/pages/RunDetailPage.tsx` — one page for both live runs (EventSource over
  the SSE endpoint, approval form, cancel) and finished runs (DB replay). When a
  watched run reaches a terminal status it prompts for an estimated
  time-saved (hours/minutes); Done skips, and the estimate can be added or
  edited later from the Runs table (`PATCH /api/runs/{id}/time-saved`,
  terminal runs only).
- `src/pages/MetricsPage.tsx` — reads `GET /api/metrics` (aggregated in Python
  on request — the dataset is small) and renders stat tiles plus hand-rolled
  SVG charts (`src/components/charts.tsx`): runs/tokens/time-saved per day,
  tokens and steps per agent (attributed via the agent name recorded in each
  step's input), time saved per workflow. Runs without a captured estimate are
  excluded from time-saved figures.
- `src/api.ts` / `src/types.ts` — typed client mirroring the pydantic schemas.
