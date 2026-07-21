"""Tool registry: custom-tool syncing, schema filtering, dispatch
(tools/registry.py)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.tools import registry
from app.tools.registry import (
    BUILTIN_TOOL_NAMES,
    REGISTRY,
    execute_tool,
    sync_custom_tools,
    tool_schemas_for,
)

pytestmark_async = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def restore_registry():
    """Snapshot and restore the global REGISTRY around each test, since
    sync_custom_tools mutates it in place."""
    snapshot = dict(REGISTRY)
    try:
        yield
    finally:
        REGISTRY.clear()
        REGISTRY.update(snapshot)


@dataclass
class FakeToolRow:
    name: str
    description: str = "a custom tool"
    input_schema: dict[str, Any] | None = None
    mutating: bool = True
    source_code: str = "def run(params):\n    return 'ok'\n"


# --------------------------------------------------------------------------- #
# sync_custom_tools                                                          #
# --------------------------------------------------------------------------- #


def test_sync_adds_custom_tools() -> None:
    sync_custom_tools([FakeToolRow(name="my_tool")])
    assert "my_tool" in REGISTRY
    assert REGISTRY["my_tool"].mutating is True


def test_sync_replaces_previous_custom_tools() -> None:
    sync_custom_tools([FakeToolRow(name="old_tool")])
    sync_custom_tools([FakeToolRow(name="new_tool")])
    assert "new_tool" in REGISTRY
    assert "old_tool" not in REGISTRY  # dropped on re-sync


def test_sync_never_touches_builtins() -> None:
    sync_custom_tools([FakeToolRow(name="extra")])
    assert BUILTIN_TOOL_NAMES <= set(REGISTRY)
    # And clearing all custom tools leaves builtins intact.
    sync_custom_tools([])
    assert set(REGISTRY) == set(BUILTIN_TOOL_NAMES)


def test_sync_defaults_missing_schema() -> None:
    sync_custom_tools([FakeToolRow(name="noschema", input_schema=None)])
    assert REGISTRY["noschema"].input_schema == {"type": "object", "properties": {}}


# --------------------------------------------------------------------------- #
# tool_schemas_for                                                           #
# --------------------------------------------------------------------------- #


def test_schemas_exclude_mutating_when_gated() -> None:
    defs = tool_schemas_for(["read_file", "write_file"], include_mutating=False)
    names = {d["name"] for d in defs}
    assert names == {"read_file"}  # write_file is mutating


def test_schemas_include_mutating_when_allowed() -> None:
    defs = tool_schemas_for(["read_file", "write_file"], include_mutating=True)
    names = {d["name"] for d in defs}
    assert names == {"read_file", "write_file"}


def test_schemas_skip_unknown_names() -> None:
    defs = tool_schemas_for(["read_file", "does_not_exist"], include_mutating=True)
    assert {d["name"] for d in defs} == {"read_file"}


def test_schema_shape_is_anthropic_compatible() -> None:
    (schema,) = tool_schemas_for(["read_file"], include_mutating=False)
    assert set(schema) == {"name", "description", "input_schema"}


# --------------------------------------------------------------------------- #
# new builtin tools (branch/commit/push/PR) — registration shape only;       #
# behavior is covered by test_gitops.py / test_github.py                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name", ["git_create_branch", "git_commit", "git_push", "github_create_pr"]
)
def test_delivery_tools_registered_and_mutating(name: str) -> None:
    assert name in BUILTIN_TOOL_NAMES
    assert REGISTRY[name].mutating is True


def test_delivery_tools_excluded_from_safe_mode_toolset() -> None:
    defs = tool_schemas_for(
        ["read_file", "git_create_branch", "git_commit", "git_push", "github_create_pr"],
        include_mutating=False,
    )
    assert {d["name"] for d in defs} == {"read_file"}


# --------------------------------------------------------------------------- #
# execute_tool                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_execute_unknown_tool(repo: Path) -> None:
    result = await execute_tool("nope", repo, {})
    assert not result.success
    assert "Unknown tool" in result.output


@pytest.mark.asyncio
async def test_execute_builtin_read(repo: Path) -> None:
    (repo / "f.txt").write_text("data")
    result = await execute_tool("read_file", repo, {"path": "f.txt"})
    assert result.success
    assert result.output == "data"


@pytest.mark.asyncio
async def test_execute_catches_handler_exception(repo: Path, monkeypatch) -> None:
    """A handler that raises is turned into a failed ToolResult, not a crash —
    tool errors flow back to the model."""

    def boom(root: Path, params: dict[str, Any]) -> tuple[bool, str]:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(REGISTRY["read_file"], "handler", boom)
    result = await execute_tool("read_file", repo, {"path": "f.txt"})
    assert not result.success
    assert "Tool error" in result.output and "kaboom" in result.output
