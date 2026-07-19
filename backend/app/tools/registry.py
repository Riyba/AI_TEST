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

from . import fs, gitops, shell


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
