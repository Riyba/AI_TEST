# Database Model

Backend storage uses SQLAlchemy (async engine, see [backend/app/db.py](../backend/app/db.py)) with
Alembic migrations under `backend/alembic/versions/`. Models are defined in
[backend/app/models.py](../backend/app/models.py).

## Entity overview

```
agents ──< attachments >── runs ──< run_steps
                              └──< artifacts

workflows ──< runs

custom_tools        (standalone)
suggested_models     (standalone)
```

## Tables

### agents
An agent configuration: model, prompt, tool permissions, and limits.

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| name | string(200) | |
| role | string(500) | default "" |
| system_prompt | text | default "" |
| model | string(100) | default `eu.anthropic.claude-sonnet-5` |
| max_turns | int | cap on think/act turns per run, default 10 |
| max_tokens | int | input+output token budget per run, default 100,000 |
| tools | JSON (list[str]) | tool names this agent may call |
| require_approval | bool | default True; when True, mutating tools are excluded from the in-loop toolset and only run via approval-gated tool nodes |
| is_template | bool | default False |
| created_at | datetime (tz) | |
| updated_at | datetime (tz) | auto-updated on write |

Relationships: has many `attachments`.

### custom_tools
A user-defined tool: stored Python source for a `run(params: dict) -> str` function,
executed in an isolated subprocess jailed to the run's repo directory. Merged into the
in-memory tool registry at startup and after every write.

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| name | string(100), unique | must be a valid identifier, must not collide with a builtin tool |
| description | text | default "" |
| input_schema | JSON (dict) | JSON Schema, used verbatim as the Anthropic tool `input_schema` |
| mutating | bool | default True; drives approval gating / safe-mode filtering |
| source_code | text | default ""; Python source defining `run()` |
| created_at | datetime (tz) | |
| updated_at | datetime (tz) | auto-updated on write |

### suggested_models
Model ids offered as suggestions in the UI's model pickers. Suggestions only — an agent
may still be given any model string, so removing a suggestion never invalidates existing
agents. Seeded from `AVAILABLE_MODELS` on first boot, then user-editable.

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| name | string(100), unique | model id as sent to the provider |
| created_at | datetime (tz) | |

### workflows
A saved workflow definition (graph of nodes).

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| name | string(200) | |
| description | text | default "" |
| graph | JSON (dict) | GraphSpec — see [backend/app/graph/spec.py](../backend/app/graph/spec.py) |
| is_template | bool | default False |
| created_at | datetime (tz) | |
| updated_at | datetime (tz) | auto-updated on write |

Relationships: has many `runs`.

### runs
A single execution of a workflow.

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| workflow_id | int, FK → workflows.id | |
| workflow_name | string(200) | denormalized copy of the workflow's name at run time |
| status | string(30) | `pending`, `running`, `waiting_approval`, `succeeded`, `failed`, `rejected`, `cancelled`; terminal set is `{succeeded, failed, rejected, cancelled}` |
| input | JSON (dict) | `{"task": str, "repo_path": str}` |
| error | text, nullable | |
| thread_id | string(64) | LangGraph checkpointer thread id, enables pause/resume |
| total_input_tokens | int | default 0 |
| total_output_tokens | int | default 0 |
| time_saved_minutes | int, nullable | user-estimated time saved; NULL means never captured (distinct from 0), excluded from metrics |
| synced_to_datadog | bool | default False; True once metrics were accepted by Datadog (see [backend/app/datadog.py](../backend/app/datadog.py)) |
| created_at | datetime (tz) | |
| finished_at | datetime (tz), nullable | |

Relationships: has many `run_steps`, `artifacts`, `attachments` (all cascade delete-orphan).

### run_steps
One step (node execution) within a run.

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| run_id | int, FK → runs.id | |
| node_id | string(100) | |
| node_type | string(30) | |
| name | string(200) | default "" |
| status | string(30) | `running`, `succeeded`, `failed`, `rejected`; default `running` |
| input | JSON (dict) | |
| output | JSON (dict) | |
| tool_calls | JSON (list[dict]) | chronological log of tool calls made inside this step (agent loop) |
| input_tokens | int | default 0 |
| output_tokens | int | default 0 |
| started_at | datetime (tz) | |
| finished_at | datetime (tz), nullable | |

### artifacts
An output produced by a run (text, file, or diff).

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| run_id | int, FK → runs.id | |
| name | string(300) | |
| kind | string(30) | `text`, `file`, or `diff`; default `text` |
| path | string(1000), nullable | |
| content | text | default "" |
| created_at | datetime (tz) | |

### attachments
An uploaded file. Owned by an agent (included in every run of that agent), by a run
(attached at launch), or by neither yet — "staged", uploaded from the run-launch form and
claimed when the run is created.

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| agent_id | int, FK → agents.id, nullable | |
| run_id | int, FK → runs.id, nullable | |
| filename | string(300) | |
| mime_type | string(100) | default "" |
| kind | string(20) | `image`, `pdf`, or `text` — decides how the file is presented to the LLM; default `text` |
| size_bytes | int | default 0 |
| data | binary (LargeBinary) | default b"" |
| created_at | datetime (tz) | |

## Migrations

Managed with Alembic (`backend/alembic/`, config in `backend/alembic.ini`). Version history,
oldest first:

1. `c876dcb5b44b` — initial schema
2. `b3f2a91c7d54` — agent run limits
3. `e7c41f6a2b98` — run time saved
4. `a91d3e5f8c02` — attachments
5. `f4a8c2d91e63` — run datadog sync
6. `d5b9e0173a4c` — custom tools
7. `a1b2c3d4e5f6` — suggested models
