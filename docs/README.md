# SDLC Agent Studio

A **localhost-only** web app for designing, running, and observing AI agent workflows
that automate software-development-lifecycle tasks: code review, test generation,
PR descriptions, dependency audits, refactor advice, and anything else you compose
from agents + tools.

- **Orchestration:** LangGraph (Python) — nodes, conditional edges, SQLite checkpointing,
  human-in-the-loop interrupts
- **Backend:** FastAPI + SQLAlchemy (async) + SQLite, SSE for live run traces
- **Frontend:** React + Vite + TypeScript + React Flow (visual graph editor), built once
  and served statically by FastAPI — the whole app is **one process**
- **LLM:** Anthropic API (model selectable per agent — e.g. Sonnet for reasoning steps,
  Haiku for cheap/fast steps), behind a thin provider-agnostic wrapper

**Privacy:** nothing leaves your machine except the Anthropic API calls themselves.
There is no auth/login because the server binds to `127.0.0.1` only and is unreachable
from the network. All data (agents, workflows, runs, logs, artifacts, checkpoints)
lives in SQLite files under `backend/data/`.

---

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) (manages Python 3.12 automatically)
and Node 18+ (only needed to build the frontend once, or for frontend dev).

```bash
# 1. Backend deps
cd backend
uv sync

# 2. Configure environment
cp .env.example .env
#    - set ANTHROPIC_API_KEY
#    - set PROJECT_ROOTS to the directory(ies) your repos live under,
#      e.g. PROJECT_ROOTS=/Users/you/Dev  (colon-separate multiple roots)
#    - optional: set GITHUB_TOKEN to let the Feature Delivery workflow open
#      pull requests (needs pull_request:write on the target repo)

# 3. Build the frontend (once, and after frontend changes)
cd ../frontend
npm install
npm run build
```

## Run (single process)

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. On first boot the database is created and seeded
with 11 template agents and 7 template workflows.

> Keep `--host 127.0.0.1`. Binding to `0.0.0.0` would expose an auth-less app to
> your network — don't.

### Frontend dev mode (optional)

For iterating on the UI with hot reload, run the backend as above plus:

```bash
cd frontend && npm run dev   # http://localhost:5173, proxies /api to :8000
```

## First run, end to end

1. **Workflows → Code Review → Run** (or clone it first to customize).
2. Enter a repo path (inside `PROJECT_ROOTS`) that has uncommitted changes, and an
   optional task note. Start the run.
3. Watch the live trace: node starts/finishes, tool calls, token usage per step.
4. Try **Test Generation** to see the full loop: draft → **pause for your approval**
   (you can edit the draft in place) → write file → run tests → conditional branch
   to a summary or a failure diagnosis.
5. **Runs** lists history; every past run's steps, tool calls, and artifacts are
   replayable from SQLite without re-executing.

## The starter workflows

| Template | What it does |
|---|---|
| Code Review | `git diff` → reviewer agent flags risks, style issues, missing tests |
| Test Generation | draft tests → **human approval** → write file → run tests → branch: summarize (Haiku) or diagnose failures |
| PR Description Writer | diff + commit log → structured PR description |
| Dependency Audit | agent locates and reads manifests, flags risky/outdated packages |
| Refactor Advisor | reads target + call sites, proposes refactors with rationale — never applies them |
| SDLC Orchestrator | one entry point that routes your request to the right specialist agent (agents-as-tools) |
| **Feature Delivery** | plan → **human approval** → branch → implement → test → review, looping back to the developer on any failure → commit → push → open a pull request into `dev` for human review. The full plan-to-PR loop; see below. |

Clone any template and edit it in the visual graph editor: add agent / tool /
condition / approval nodes, wire edges, edit prompts and params. Prompts and tool
params support `{task}`, `{repo_path}`, `{last_output}`, and `{<node_id>}`
placeholders.

**Feature Delivery** needs `GITHUB_TOKEN` set (see above) for its final `open_pr`
step, and its `git_create_branch`/`git_push` steps need a `dev` branch and an
`origin` remote to exist in the target repo. Pair it with a GitHub Actions
workflow on `pull_request` → `dev` that runs secret-scanning (e.g. `gitleaks`)
and linting — that's an independent, un-bypassable check on what the agents
produced, which local tool calls inside the run can't give you. A branch
protection rule requiring those checks is what makes the human review at the
end of the flow actually mean something.

## Safety model

- **Path jail:** every file/git/shell tool resolves paths against the run's repo and
  rejects anything that escapes it. The repo itself must be inside `PROJECT_ROOTS`.
- **Command allowlist:** `run_command`/`run_tests` parse with `shlex`, execute
  **without a shell** (no pipes/chaining possible), and only accept an allowlisted
  executable (`git`, `pytest`, `npm`, linters, …).
- **Approval by default:** mutating tools (`write_file`, `run_command`, `run_tests`,
  `git_create_branch`, `git_commit`, `git_push`, `github_create_pr`) pause the run
  for human approval before executing. Agents in "safe mode" (the default) can't
  call mutating tools autonomously at all — mutations only happen through
  approval-gated workflow nodes. Both are opt-out per node / per agent — the
  **Feature Delivery** template's Developer agent is the one seeded exception:
  it runs with `require_approval=false` so it can write files and run commands
  across a multi-file change in one tool-use loop (an agent loop can't host a
  mid-loop approval interrupt — see ARCHITECTURE.md). The human checkpoint that
  makes this safe is the plan-approval step earlier in that workflow, plus the
  pull request waiting for review at the end.
- Runs paused at an approval survive server restarts — state is checkpointed by
  LangGraph's SQLite checkpointer and resumes from the checkpoint.

## Database & migrations

Tables are created automatically on first boot. Schema changes are managed with
Alembic:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

## Docker (optional)

Not the primary path — this is a local, single-user tool. If you want isolation of
the Python/Node toolchain, a straightforward two-stage Dockerfile (node build of
`frontend/dist`, then a python image running uvicorn with `backend/` + the built
dist) works; publish only `-p 127.0.0.1:8000:8000` and mount your project directory
plus `backend/data/`. Note that path-jailed tools then see the container's
filesystem, so mount your repos at the same paths you configure in `PROJECT_ROOTS`.

## Layout

```
backend/    FastAPI + LangGraph + SQLite (see ARCHITECTURE.md)
frontend/   React + Vite + React Flow; `npm run build` → frontend/dist served by FastAPI
```

See **ARCHITECTURE.md** for the graph JSON schema, how checkpointing and approvals
work, and how to add a new agent tool.
