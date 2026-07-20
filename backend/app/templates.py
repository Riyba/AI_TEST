"""Seed data: template agents and the five starter SDLC workflows.

Templates are ordinary rows flagged is_template=True; users clone workflows
(POST /api/workflows/{id}/clone) and customize the copies.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .llm import AVAILABLE_MODELS
from .models import Agent, SuggestedModel, Workflow

READ_TOOLS = ["read_file", "list_files", "search_files"]
GIT_READ_TOOLS = ["git_status", "git_diff", "git_log"]

AGENT_SEEDS: list[dict[str, Any]] = [
    {
        "key": "reviewer",
        "name": "Code Reviewer",
        "role": "Senior engineer performing careful code review",
        "system_prompt": (
            "You review code changes. For every diff you receive: flag risk areas "
            "(correctness, security, error handling), style issues, and missing test "
            "coverage. Use your tools to read surrounding code for context before "
            "judging. Be specific — cite file and line. Order findings by severity."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 15,
        "max_tokens": 150_000,
        "tools": READ_TOOLS + GIT_READ_TOOLS,
    },
    {
        "key": "test_writer",
        "name": "Test Writer",
        "role": "Engineer who writes thorough, runnable unit tests",
        "system_prompt": (
            "You write unit tests. Read the target module and its dependencies with "
            "your tools first. Cover happy paths, edge cases, and error handling. "
            "When asked to output a test file, output ONLY the raw file content — "
            "no markdown fences, no commentary."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 12,
        "max_tokens": 120_000,
        "tools": READ_TOOLS,
    },
    {
        "key": "pr_writer",
        "name": "PR Description Writer",
        "role": "Engineer who writes clear, structured pull-request descriptions",
        "system_prompt": (
            "You write pull-request descriptions from diffs and commit history. "
            "Structure: Summary, Changes (bulleted), Rationale, Testing notes, "
            "Risks/rollback. Be accurate — only describe what the diff shows."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 8,
        "max_tokens": 80_000,
        "tools": ["read_file", "git_diff", "git_log"],
    },
    {
        "key": "dep_auditor",
        "name": "Dependency Auditor",
        "role": "Engineer auditing project dependencies",
        "system_prompt": (
            "You audit dependencies. Locate manifest/lock files (package.json, "
            "pyproject.toml, requirements.txt, go.mod, Cargo.toml, ...), read them, "
            "and flag: pinned-to-old major versions, known-risky packages, unpinned "
            "or overly-loose constraints, and deprecated packages. Note that you "
            "cannot query live CVE feeds — reason from the manifests and your "
            "knowledge, and say so explicitly."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 12,
        "max_tokens": 120_000,
        "tools": READ_TOOLS,
    },
    {
        "key": "refactor_advisor",
        "name": "Refactor Advisor",
        "role": "Engineer proposing refactors without applying them",
        "system_prompt": (
            "You suggest refactors for a target file or function. Read the code and "
            "its call sites first. For each suggestion give: what to change, why "
            "(readability, duplication, coupling, performance), and a sketch of the "
            "refactored code. NEVER apply changes — advice only."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 12,
        "max_tokens": 120_000,
        "tools": READ_TOOLS,
    },
    {
        "key": "debugger",
        "name": "Test Failure Debugger",
        "role": "Engineer diagnosing failing tests",
        "system_prompt": (
            "You diagnose failing tests. Given test output and the code involved, "
            "identify the root cause and propose concrete fixes. Read source files "
            "with your tools as needed."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 12,
        "max_tokens": 120_000,
        "tools": READ_TOOLS,
    },
    {
        "key": "summarizer",
        "name": "Summarizer (fast)",
        "role": "Fast, cheap summarizer",
        "system_prompt": "Summarize the provided content concisely for a developer audience.",
        "model": "claude-haiku-4-5",
        "max_turns": 2,
        "max_tokens": 20_000,
        "tools": [],
    },
    {
        "key": "orchestrator",
        "name": "SDLC Orchestrator",
        "role": "Routes software-development requests to specialist agents",
        "system_prompt": (
            "You are the front door for an SDLC agent team. Read the user's request, "
            "decide which specialist agent is the right one to handle it, and delegate "
            "with a clear, self-contained instruction. If the request has several "
            "distinct parts, delegate each to the appropriate agent in turn. After the "
            "specialists respond, synthesize a single, coherent answer for the user — "
            "attribute which agent produced which part when it helps. Do not attempt "
            "the specialist work yourself."
        ),
        "model": "claude-sonnet-5",
        "max_turns": 12,
        "max_tokens": 150_000,
        "tools": [],
    },
]


def _node(
    id: str, type_: str, name: str, x: float, y: float, **extra: Any
) -> dict[str, Any]:
    return {"id": id, "type": type_, "name": name, "position": {"x": x, "y": y}, **extra}


def _workflow_seeds(agent_ids: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {
            "name": "Code Review",
            "description": "Take the current git diff and produce a structured review: risk areas, style issues, missing tests.",
            "graph": {
                "entry": "diff",
                "nodes": [
                    _node("diff", "tool", "Get diff", 0, 120, tool="git_diff", params={}),
                    _node(
                        "review", "agent", "Review diff", 280, 120,
                        agent_id=agent_ids["reviewer"],
                        prompt=(
                            "Task: {task}\n\nCurrent git diff:\n\n{diff}\n\n"
                            "Review this diff. Flag risk areas, style issues, and missing tests. "
                            "Read surrounding files for context where needed."
                        ),
                    ),
                ],
                "edges": [{"source": "diff", "target": "review"}],
            },
        },
        {
            "name": "Test Generation",
            "description": "Draft unit tests for a target module, pause for approval, write the file, run the suite, then summarize or debug depending on the result.",
            "graph": {
                "entry": "draft",
                "nodes": [
                    _node(
                        "draft", "agent", "Draft tests", 0, 160,
                        agent_id=agent_ids["test_writer"],
                        prompt=(
                            "Target: {task}\n\nRead the target module and write a complete "
                            "unit test file for it. Output ONLY the raw test file content."
                        ),
                    ),
                    _node(
                        "approve", "approval", "Approve test file", 280, 160,
                        message=(
                            "About to write the drafted tests to generated_tests/test_generated.py "
                            "and run the test suite. Review (and optionally edit) the draft."
                        ),
                    ),
                    _node(
                        "write", "tool", "Write test file", 560, 160,
                        tool="write_file",
                        params={"path": "generated_tests/test_generated.py", "content": "{last_output}"},
                        require_approval=False,  # gated by the approval node above
                    ),
                    _node(
                        "test", "tool", "Run tests", 840, 160,
                        tool="run_tests", params={}, require_approval=False,
                    ),
                    _node(
                        "check", "condition", "Tests passed?", 1120, 160,
                        predicate={"kind": "tool_success", "value": ""},
                    ),
                    _node(
                        "summarize", "agent", "Summarize results", 1400, 40,
                        agent_id=agent_ids["summarizer"],
                        prompt="Summarize this test run for the developer:\n\n{test}",
                    ),
                    _node(
                        "debug", "agent", "Diagnose failures", 1400, 280,
                        agent_id=agent_ids["debugger"],
                        prompt=(
                            "The generated tests failed.\n\nTest output:\n{test}\n\n"
                            "Test file content:\n{draft}\n\nDiagnose the failures and propose fixes."
                        ),
                    ),
                ],
                "edges": [
                    {"source": "draft", "target": "approve"},
                    {"source": "approve", "target": "write"},
                    {"source": "write", "target": "test"},
                    {"source": "test", "target": "check"},
                    {"source": "check", "target": "summarize", "label": "true"},
                    {"source": "check", "target": "debug", "label": "false"},
                ],
            },
        },
        {
            "name": "PR Description Writer",
            "description": "Summarize the current diff plus recent commit history into a structured PR description.",
            "graph": {
                "entry": "diff",
                "nodes": [
                    _node("diff", "tool", "Get diff", 0, 60, tool="git_diff", params={}),
                    _node("log", "tool", "Get history", 280, 60, tool="git_log", params={"count": 15}),
                    _node(
                        "write_pr", "agent", "Write PR description", 560, 60,
                        agent_id=agent_ids["pr_writer"],
                        prompt=(
                            "Context / linked issue: {task}\n\nDiff:\n{diff}\n\n"
                            "Recent commits:\n{log}\n\nWrite a structured PR description."
                        ),
                    ),
                ],
                "edges": [
                    {"source": "diff", "target": "log"},
                    {"source": "log", "target": "write_pr"},
                ],
            },
        },
        {
            "name": "Dependency Audit",
            "description": "Scan manifest files and flag outdated or risky packages.",
            "graph": {
                "entry": "audit",
                "nodes": [
                    _node(
                        "audit", "agent", "Audit dependencies", 0, 60,
                        agent_id=agent_ids["dep_auditor"],
                        prompt=(
                            "Audit this repository's dependencies. {task}\n\n"
                            "Locate and read every manifest/lock file, then report findings "
                            "grouped by severity."
                        ),
                    ),
                ],
                "edges": [],
            },
        },
        {
            "name": "SDLC Orchestrator",
            "description": "One entry point that routes your request to the right specialist agent (reviewer, test writer, PR writer, dependency auditor, refactor advisor, or debugger) and synthesizes the result — the agents-as-tools pattern.",
            "graph": {
                "entry": "route",
                "nodes": [
                    _node(
                        "route", "orchestrator", "Route to specialist", 0, 120,
                        agent_id=agent_ids["orchestrator"],
                        team=[
                            agent_ids["reviewer"],
                            agent_ids["test_writer"],
                            agent_ids["pr_writer"],
                            agent_ids["dep_auditor"],
                            agent_ids["refactor_advisor"],
                            agent_ids["debugger"],
                        ],
                        prompt="{task}",
                    ),
                ],
                "edges": [],
            },
        },
        {
            "name": "Refactor Advisor",
            "description": "Suggest refactors for a target file or function, with rationale — never auto-applies.",
            "graph": {
                "entry": "advise",
                "nodes": [
                    _node(
                        "advise", "agent", "Suggest refactors", 0, 60,
                        agent_id=agent_ids["refactor_advisor"],
                        prompt=(
                            "Refactoring target: {task}\n\nRead the target and its call sites, "
                            "then propose refactors with rationale and code sketches. Do not "
                            "apply any changes."
                        ),
                    ),
                ],
                "edges": [],
            },
        },
    ]


async def seed_templates(session: AsyncSession) -> None:
    count = (
        await session.execute(
            select(func.count()).select_from(Workflow).where(Workflow.is_template.is_(True))
        )
    ).scalar_one()
    if count:
        return

    agent_ids: dict[str, int] = {}
    for seed in AGENT_SEEDS:
        agent = Agent(
            name=seed["name"],
            role=seed["role"],
            system_prompt=seed["system_prompt"],
            model=seed["model"],
            max_turns=seed["max_turns"],
            max_tokens=seed["max_tokens"],
            tools=seed["tools"],
            require_approval=True,
            is_template=True,
        )
        session.add(agent)
        await session.flush()
        agent_ids[seed["key"]] = agent.id

    for wf in _workflow_seeds(agent_ids):
        session.add(
            Workflow(
                name=wf["name"],
                description=wf["description"],
                graph=wf["graph"],
                is_template=True,
            )
        )
    await session.commit()


async def seed_models(session: AsyncSession) -> None:
    """Populate the suggested-model list with the built-in defaults, once.

    Runs on every boot but no-ops as soon as the table has any row, so a user
    who has deleted every default is not force-fed them again."""
    count = (
        await session.execute(select(func.count()).select_from(SuggestedModel))
    ).scalar_one()
    if count:
        return
    for name in AVAILABLE_MODELS:
        session.add(SuggestedModel(name=name))
    await session.commit()
