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
        "model": "eu.anthropic.claude-sonnet-5",
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
        "model": "eu.anthropic.claude-sonnet-5",
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
        "model": "eu.anthropic.claude-sonnet-5",
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
        "model": "eu.anthropic.claude-sonnet-5",
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
        "model": "eu.anthropic.claude-sonnet-5",
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
        "model": "eu.anthropic.claude-sonnet-5",
        "max_turns": 12,
        "max_tokens": 120_000,
        "tools": READ_TOOLS,
    },
    {
        "key": "summarizer",
        "name": "Summarizer (fast)",
        "role": "Fast, cheap summarizer",
        "system_prompt": "Summarize the provided content concisely for a developer audience.",
        "model": "eu.anthropic.claude-haiku-4-5-2025-1001-v1:0",
        "max_turns": 2,
        "max_tokens": 20_000,
        "tools": [],
    },
    {
        "key": "planner",
        "name": "Planner",
        "role": "Engineer who scopes and plans a change before any code is written",
        "system_prompt": (
            "You scope and plan changes to this codebase. Read whatever files you need "
            "for context first. If the request is simple and unambiguous, output a "
            "concrete step-by-step implementation plan: what changes, in which files, "
            "and why. If there are decisions only a human can make (missing "
            "requirements, a genuine design choice, something you'd be guessing at), "
            "output the plan you can already commit to, then a section starting with "
            "the literal heading 'QUESTIONS:' listing exactly what you need answered "
            "before implementation should start."
        ),
        "model": "eu.anthropic.claude-sonnet-5",
        "max_turns": 15,
        "max_tokens": 120_000,
        "tools": READ_TOOLS + GIT_READ_TOOLS,
    },
    {
        "key": "branch_namer",
        "name": "Branch Namer (fast)",
        "role": "Names a git feature branch from a task description",
        "system_prompt": (
            "You turn a feature request into a short git branch name. Output ONLY the "
            "name — three to five lowercase words joined by hyphens (kebab-case), no "
            "'feature/' prefix, no quotes, no punctuation, no explanation. Example: for "
            "'Add rate limiting to the login endpoint' output 'rate-limit-login-endpoint'."
        ),
        "model": "eu.anthropic.claude-haiku-4-5-2025-1001-v1:0",
        "max_turns": 1,
        "max_tokens": 2_000,
        "tools": [],
    },
    {
        "key": "developer",
        "name": "Developer",
        "role": "Engineer who implements an approved plan end-to-end",
        "system_prompt": (
            "You implement an approved implementation plan. Read the target files and "
            "their surroundings for context, then write or modify whatever files the "
            "plan calls for. You may run allowlisted commands (e.g. a linter or "
            "formatter) to sanity-check your work. If you're given prior test failures "
            "or code review feedback, that means an earlier attempt was incomplete or "
            "wrong — fix the specific issues described, don't just retry the same "
            "thing. Do not touch git (branching, committing, and pushing are handled "
            "outside your loop) — just leave the working tree in the state it should "
            "be committed from."
        ),
        "model": "eu.anthropic.claude-sonnet-5",
        "max_turns": 30,
        "max_tokens": 300_000,
        "tools": READ_TOOLS + ["write_file", "run_command"],
        "require_approval": False,
    },
    {
        "key": "pr_reviewer",
        "name": "Code Reviewer (PR Gate)",
        "role": "Senior engineer gatekeeping a pull request before it ships",
        "system_prompt": (
            "You are the last check before a change ships as a pull request. Review "
            "the diff against the stated plan: correctness, security, error handling, "
            "style, and missing test coverage. Read surrounding code for context where "
            "needed. Be specific — cite file and line. Then end your response with "
            "EXACTLY one line, and nothing after it: 'VERDICT: APPROVE' if this is "
            "safe to merge as-is, or 'VERDICT: CHANGES_REQUESTED' if not. When "
            "requesting changes, make sure the findings above are concrete enough for "
            "another engineer to act on without asking you anything further."
        ),
        "model": "eu.anthropic.claude-sonnet-5",
        "max_turns": 15,
        "max_tokens": 150_000,
        "tools": READ_TOOLS + GIT_READ_TOOLS,
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
        "model": "eu.anthropic.claude-sonnet-5",
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
        {
            "name": "Feature Delivery",
            "description": (
                "End-to-end feature delivery: plan the change and get human approval, "
                "branch, implement, test and review it — looping back to the developer "
                "on any failure — then commit, push, and open a pull request into dev "
                "for human review."
            ),
            "graph": {
                "entry": "plan",
                "nodes": [
                    _node(
                        "plan", "agent", "Plan the change", 0, 200,
                        agent_id=agent_ids["planner"],
                        prompt=(
                            "Task: {task}\n\nRepository: {repo_path}\n\n"
                            "Scope and plan this change. Read whatever context you need "
                            "before answering."
                        ),
                    ),
                    _node(
                        "plan_gate", "approval", "Approve plan", 280, 200,
                        message=(
                            "Review the plan below. Approve to create a branch and start "
                            "implementation. If the planner listed QUESTIONS, edit this text "
                            "to answer them (or rewrite the plan outright) before approving — "
                            "your edited text is what the developer implements. Reject to "
                            "cancel the run."
                        ),
                    ),
                    _node(
                        "branch_name", "agent", "Name the branch", 560, 200,
                        agent_id=agent_ids["branch_namer"],
                        prompt=(
                            "Feature request: {task}\n\nApproved plan:\n{plan_gate}\n\n"
                            "Output a short kebab-case branch name for this work."
                        ),
                    ),
                    _node(
                        "branch", "tool", "Create branch", 840, 200,
                        tool="git_create_branch",
                        params={"base": "dev", "name": "{branch_name}"},
                        require_approval=False,
                    ),
                    _node(
                        "develop", "agent", "Implement changes", 1120, 200,
                        agent_id=agent_ids["developer"],
                        prompt=(
                            "Task: {task}\n\nApproved plan:\n{plan_gate}\n\n"
                            "Repository: {repo_path}\n\nImplement the plan now.\n\n"
                            "If this is a retry, fix the specific issues below (blank on a "
                            "first attempt):\n\nTest failures:\n{unit_tests}\n\n"
                            "Code review feedback:\n{code_review}"
                        ),
                    ),
                    _node(
                        "unit_tests", "tool", "Run unit tests", 1400, 200,
                        tool="run_tests", params={}, require_approval=False,
                    ),
                    _node(
                        "tests_gate", "condition", "Tests passed?", 1680, 200,
                        predicate={"kind": "tool_success"},
                    ),
                    _node(
                        "diff_for_review", "tool", "Get diff", 1960, 80,
                        tool="git_diff", params={},
                    ),
                    _node(
                        "code_review", "agent", "Review changes", 2240, 80,
                        agent_id=agent_ids["pr_reviewer"],
                        prompt=(
                            "Task: {task}\n\nApproved plan:\n{plan_gate}\n\n"
                            "Diff:\n{diff_for_review}\n\n"
                            "Review these changes against the plan and give your verdict."
                        ),
                    ),
                    _node(
                        "review_gate", "condition", "Review approved?", 2520, 80,
                        predicate={
                            "kind": "output_contains",
                            "value": "VERDICT: APPROVE",
                            "node_id": "code_review",
                        },
                    ),
                    _node(
                        "pr_description", "agent", "Write PR description", 2800, 80,
                        agent_id=agent_ids["pr_writer"],
                        prompt=(
                            "Context: {task}\n\nDiff:\n{diff_for_review}\n\n"
                            "Write a structured PR description for this change."
                        ),
                    ),
                    _node(
                        "commit", "tool", "Commit changes", 3080, 80,
                        tool="git_commit", params={"message": "{task}"},
                        require_approval=False,
                    ),
                    _node(
                        "push", "tool", "Push branch", 3360, 80,
                        tool="git_push", params={}, require_approval=False,
                    ),
                    _node(
                        "open_pr", "tool", "Open pull request", 3640, 80,
                        tool="github_create_pr",
                        params={"base": "dev", "title": "{task}", "body": "{pr_description}"},
                        require_approval=False,
                    ),
                ],
                "edges": [
                    {"source": "plan", "target": "plan_gate"},
                    {"source": "plan_gate", "target": "branch_name"},
                    {"source": "branch_name", "target": "branch"},
                    {"source": "branch", "target": "develop"},
                    {"source": "develop", "target": "unit_tests"},
                    {"source": "unit_tests", "target": "tests_gate"},
                    {"source": "tests_gate", "target": "diff_for_review", "label": "true"},
                    {"source": "tests_gate", "target": "develop", "label": "false"},
                    {"source": "diff_for_review", "target": "code_review"},
                    {"source": "code_review", "target": "review_gate"},
                    {"source": "review_gate", "target": "pr_description", "label": "true"},
                    {"source": "review_gate", "target": "develop", "label": "false"},
                    {"source": "pr_description", "target": "commit"},
                    {"source": "commit", "target": "push"},
                    {"source": "push", "target": "open_pr"},
                ],
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
            require_approval=seed.get("require_approval", True),
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
