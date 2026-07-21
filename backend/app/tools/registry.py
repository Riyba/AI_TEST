"""Tool registry: metadata + dispatch for everything agents can call.

Every tool runs jailed to the run's repo_path. Tools flagged `mutating`
(file writes, command execution) are excluded from agent tool-use loops
when the agent has require_approval=True, and tool nodes running them
interrupt for human approval first.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import fs, github, gitops, shell


@dataclass
class ToolResult:
    success: bool
    output: str


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    mutating: bool
    handler: Callable[[Path, dict[str, Any]], tuple[bool, str]]
    params_doc: dict[str, str] = field(default_factory=dict)


def _schema(props: dict[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


REGISTRY: dict[str, Tool] = {}


def _register(tool: Tool) -> None:
    REGISTRY[tool.name] = tool


_register(Tool(
    name="read_file",
    description="Read a text file from the repository. Use a path relative to the repo root.",
    input_schema=_schema({"path": {"type": "string", "description": "File path relative to repo root"}}, ["path"]),
    mutating=False,
    handler=lambda root, p: fs.read_file(root, p.get("path", "")),
))

_register(Tool(
    name="list_files",
    description="List files in the repository (recursively), optionally under a subdirectory. Skips .git, node_modules, and other vendor dirs.",
    input_schema=_schema({"path": {"type": "string", "description": "Subdirectory relative to repo root (default: repo root)"}}, []),
    mutating=False,
    handler=lambda root, p: fs.list_files(root, p.get("path", ".")),
))

_register(Tool(
    name="search_files",
    description="Search file contents with a regular expression. Returns matching lines as path:line:text.",
    input_schema=_schema(
        {
            "pattern": {"type": "string", "description": "Regular expression to search for"},
            "path": {"type": "string", "description": "Subdirectory to search (default: repo root)"},
        },
        ["pattern"],
    ),
    mutating=False,
    handler=lambda root, p: fs.search_files(root, p.get("pattern", ""), p.get("path", ".")),
))

_register(Tool(
    name="git_status",
    description="Show git working tree status.",
    input_schema=_schema({}, []),
    mutating=False,
    handler=lambda root, p: gitops.status(root),
))

_register(Tool(
    name="git_diff",
    description="Show the current git diff (working tree + staged vs HEAD), or an explicit revision range.",
    input_schema=_schema({"range": {"type": "string", "description": "Optional revision range, e.g. 'main..HEAD'"}}, []),
    mutating=False,
    handler=lambda root, p: gitops.diff(root, p.get("range", "")),
))

_register(Tool(
    name="git_log",
    description="Show recent git commit history.",
    input_schema=_schema({"count": {"type": "integer", "description": "Number of commits (default 10)"}}, []),
    mutating=False,
    handler=lambda root, p: gitops.log(root, int(p.get("count", 10) or 10)),
))

_register(Tool(
    name="write_file",
    description="Write content to a file in the repository (creates parent directories). MUTATING.",
    input_schema=_schema(
        {
            "path": {"type": "string", "description": "File path relative to repo root"},
            "content": {"type": "string", "description": "Full file content to write"},
        },
        ["path", "content"],
    ),
    mutating=True,
    handler=lambda root, p: fs.write_file(root, p.get("path", ""), p.get("content", "")),
))

_register(Tool(
    name="run_command",
    description=(
        "Run an allowlisted command in the repo root. Allowed executables: "
        + ", ".join(sorted(shell.ALLOWED_EXECUTABLES))
        + ". No pipes or shell operators. MUTATING."
    ),
    input_schema=_schema({"command": {"type": "string", "description": "Command line, e.g. 'pytest -q' or 'ruff check .'"}}, ["command"]),
    mutating=True,
    handler=lambda root, p: shell.run_command(root, p.get("command", "")),
))

_register(Tool(
    name="run_tests",
    description="Run the project's test suite (auto-detects pytest or npm test, or pass an explicit test command). MUTATING.",
    input_schema=_schema({"command": {"type": "string", "description": "Optional explicit test command (must be an allowlisted runner)"}}, []),
    mutating=True,
    handler=lambda root, p: shell.run_tests(root, p.get("command", "")),
))

_register(Tool(
    name="git_create_branch",
    description=(
        "Create and check out a new branch off a base branch (fetches the base "
        "from origin first when possible). The branch name is derived by "
        "slugifying the given name plus a random suffix for uniqueness. MUTATING."
    ),
    input_schema=_schema(
        {
            "base": {"type": "string", "description": "Base branch to branch from (default: dev)"},
            "name": {"type": "string", "description": "Short description used to derive the branch name, e.g. the task"},
        },
        ["name"],
    ),
    mutating=True,
    handler=lambda root, p: gitops.create_branch(root, p.get("base", "dev"), p.get("name", "")),
))

_register(Tool(
    name="git_commit",
    description="Stage all changes (git add -A) and commit them with the given message. MUTATING.",
    input_schema=_schema({"message": {"type": "string", "description": "Commit message"}}, ["message"]),
    mutating=True,
    handler=lambda root, p: gitops.commit(root, p.get("message", "")),
))

_register(Tool(
    name="git_push",
    description="Push a branch to origin, setting upstream. Defaults to the currently checked-out branch. MUTATING.",
    input_schema=_schema({"branch": {"type": "string", "description": "Branch to push (default: current branch)"}}, []),
    mutating=True,
    handler=lambda root, p: gitops.push(root, p.get("branch", "")),
))

_register(Tool(
    name="github_create_pr",
    description=(
        "Open a pull request on GitHub via the REST API (requires GITHUB_TOKEN to be "
        "configured). Repository owner/repo is inferred from the origin remote; head "
        "branch defaults to the currently checked-out branch. MUTATING."
    ),
    input_schema=_schema(
        {
            "base": {"type": "string", "description": "Target branch the PR merges into (default: dev)"},
            "head": {"type": "string", "description": "Source branch (default: currently checked-out branch)"},
            "title": {"type": "string", "description": "PR title"},
            "body": {"type": "string", "description": "PR description body"},
        },
        [],
    ),
    mutating=True,
    handler=lambda root, p: github.create_pull_request(root, p),
))


# Names registered above are the builtin, code-defined tools. Everything added
# later via sync_custom_tools() is a user-defined tool loaded from the database.
BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(REGISTRY)


def is_builtin(name: str) -> bool:
    return name in BUILTIN_TOOL_NAMES


def _custom_handler(source: str) -> Callable[[Path, dict[str, Any]], tuple[bool, str]]:
    """Build a registry handler that runs stored Python in an isolated
    subprocess. Imported lazily so the registry has no hard dependency on the
    executor at import time."""

    def handler(root: Path, params: dict[str, Any]) -> tuple[bool, str]:
        from .pyexec import run_python_tool

        return run_python_tool(source, root, params)

    return handler


def register_custom_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    mutating: bool,
    source_code: str,
) -> None:
    REGISTRY[name] = Tool(
        name=name,
        description=description,
        input_schema=input_schema,
        mutating=mutating,
        handler=_custom_handler(source_code),
    )


def sync_custom_tools(rows: list[Any]) -> None:
    """Replace all custom tools in the registry with the given DB rows.

    ``rows`` are objects exposing name/description/input_schema/mutating/
    source_code (the CustomTool ORM rows). Builtins are never touched, so a
    custom tool can never shadow or remove one."""
    for existing in list(REGISTRY):
        if existing not in BUILTIN_TOOL_NAMES:
            del REGISTRY[existing]
    for row in rows:
        register_custom_tool(
            name=row.name,
            description=row.description,
            input_schema=row.input_schema or {"type": "object", "properties": {}},
            mutating=bool(row.mutating),
            source_code=row.source_code,
        )


def tool_schemas_for(names: list[str], *, include_mutating: bool) -> list[dict[str, Any]]:
    """Anthropic tool definitions for the given tool names."""
    defs: list[dict[str, Any]] = []
    for name in names:
        tool = REGISTRY.get(name)
        if tool is None:
            continue
        if tool.mutating and not include_mutating:
            continue
        defs.append(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
        )
    return defs


async def execute_tool(name: str, repo_path: Path, params: dict[str, Any]) -> ToolResult:
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolResult(False, f"Unknown tool: {name}")
    try:
        # Handlers are sync (subprocess / file IO); run off the event loop.
        success, output = await asyncio.to_thread(tool.handler, repo_path, params)
        return ToolResult(success, output)
    except Exception as exc:  # noqa: BLE001 — tool errors go back to the model
        return ToolResult(False, f"Tool error: {exc}")
