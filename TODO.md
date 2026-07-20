# TODO

## High priority

- [ ] **Add lint/type config.** Code already carries `# noqa: BLE001` markers, so
  ruff is intended but there's no `[tool.ruff]` / `[tool.mypy]` in
  `backend/pyproject.toml`. Add both, plus a minimal CI step (or a `make check`).

- [ ] **Configure SQLite for concurrency.** Two concurrent runs each open
  `AsyncSqliteSaver` on `checkpoints.db` and write `app.db`; with default SQLite
  settings this risks `database is locked`. In `db.py`, enable WAL + busy_timeout
  on connect: `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000`. Cheap, removes
  a real failure mode (a user can launch two runs at once).

## Medium priority

- [ ] **Fix shared-mutable `REGISTRY` race.** `tools/registry.py::sync_custom_tools`
  deletes then re-adds every custom tool in the global dict on each tool write,
  while concurrent agent loops read `REGISTRY` / `tool_schemas_for`. A save during
  an active run can briefly drop a custom tool mid-loop. Rebuild into a new dict
  and swap the reference atomically instead of mutating in place.

- [ ] **Prune the event bus.** `events.py` keeps `_history` and `_subscribers`
  keyed by run_id for the whole process lifetime — a slow leak on a long-lived
  server. Clean up on `close()` (drop history after a grace period, or cap
  retained runs).

- [ ] **Bound `/api/metrics`.** `routers/metrics.py::get_metrics` loads *all* runs
  and *all* agent steps into memory per call. `list_runs` caps at 200 but this
  doesn't, and `run_steps` is the fastest-growing table. Add a LIMIT or date
  window before the dataset stops being "small".

## Low priority (cleanups)

- [ ] **Simplify orchestrator persona rebuild.** `graph/nodes.py` (~L413) manually
  copies all 9 `AgentDef` fields just to override `system_prompt`. Replace with
  `dataclasses.replace(persona, system_prompt=...)` — one line, won't silently
  drop a field when `AgentDef` grows.

- [ ] **De-dupe `write_file`→artifact logic.** Same block appears in
  `graph/nodes.py::run_agent_loop` (~L262) and `make_tool_node` (~L532). Extract a
  `save_write_artifact(ctx, params)` helper.

- [ ] **De-dupe frontend error parsing.** `frontend/src/api.ts` `request` and
  `requestForm` share an identical `res.ok` error block. Extract `parseError(res)`.

- [ ] **Rename overloaded `max_tokens`.** `agent.max_tokens` (per-run input+output
  *budget*) and the provider's `max_tokens` (per-call output cap, driven by
  `llm_max_tokens`) are unrelated but identically named — a readability trap in
  `run_agent_loop`. Consider renaming the agent field to `max_token_budget`.
