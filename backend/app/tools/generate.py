"""AI-authored custom tools: turn a natural-language prompt (plus optional
reference attachments) into a reviewable tool draft.

This never saves or executes anything — it returns a draft that the user edits
and explicitly saves through the normal CRUD flow. Generation reuses the app's
provider abstraction (app/llm.py); the model is steered to emit a structured
definition via a single forced tool call rather than free-form JSON."""

from __future__ import annotations

from typing import Any

from ..attachments import AttachmentContent, to_content_blocks
from ..llm import LLMProvider

# Contract shown to the model. Mirrors the runtime contract enforced by
# app/tools/_pyrunner.py and the isolation described in app/tools/pyexec.py.
_SYSTEM = """You author custom tools for an AI agent platform. A tool is a small \
piece of Python that the agent can call with structured parameters.

Runtime contract — the source you write MUST:
- define a top-level function `def run(params: dict) -> str` (no other entry point);
- read its inputs from the `params` dict (keys match your input_schema);
- return a string describing the result. To signal failure, either raise an \
exception or return a `(False, "message")` tuple; a `(True, "message")` tuple \
sets success explicitly;
- rely only on the Python standard library and packages already installed in \
the environment. Do not assume network access is available unless the task \
requires it.

Execution environment: the code runs in an isolated subprocess whose working \
directory is the target repository, with secrets (API keys) stripped from the \
environment, a wall-clock timeout, and CPU/memory limits. Keep tools focused \
and fast.

Set `mutating` to true if the tool writes files, executes commands, makes \
network calls with side effects, or changes anything outside pure reads; false \
for read-only tools. The platform uses this flag to gate approvals.

Choose a concise, lowercase snake_case `name` (a valid Python identifier) and a \
one-sentence `description`. Provide a JSON Schema `input_schema` of type object \
describing each parameter with a helpful description.

Call the `emit_tool` tool exactly once with the finished definition."""

_EMIT_TOOL: dict[str, Any] = {
    "name": "emit_tool",
    "description": "Emit the finished custom tool definition for review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "snake_case identifier, unique and lowercase",
            },
            "description": {
                "type": "string",
                "description": "One sentence describing what the tool does",
            },
            "mutating": {
                "type": "boolean",
                "description": "True if the tool writes/executes/has side effects",
            },
            "input_schema": {
                "type": "object",
                "description": "JSON Schema (type: object) for the tool's params",
            },
            "source_code": {
                "type": "string",
                "description": "Python source defining def run(params: dict) -> str",
            },
        },
        "required": [
            "name",
            "description",
            "mutating",
            "input_schema",
            "source_code",
        ],
    },
}


class ToolGenerationError(Exception):
    pass


async def generate_tool_draft(
    *,
    provider: LLMProvider,
    model: str,
    prompt: str,
    attachments: list[AttachmentContent],
) -> dict[str, Any]:
    """Return a draft dict (name, description, input_schema, mutating,
    source_code). Raises ToolGenerationError if the model does not emit one."""
    content = to_content_blocks(attachments)
    content.append(
        {
            "type": "text",
            "text": f"Build a tool for this request:\n\n{prompt}",
        }
    )
    response = await provider.complete(
        model=model,
        system=_SYSTEM,
        messages=[{"role": "user", "content": content}],
        tools=[_EMIT_TOOL],
        max_tokens=4096,
    )
    for call in response.tool_calls:
        if call.name == "emit_tool":
            data = call.input
            schema = data.get("input_schema")
            if not isinstance(schema, dict) or not schema:
                schema = {"type": "object", "properties": {}}
            return {
                "name": str(data.get("name", "")).strip(),
                "description": str(data.get("description", "")).strip(),
                "input_schema": schema,
                "mutating": bool(data.get("mutating", True)),
                "source_code": str(data.get("source_code", "")),
            }
    detail = response.text.strip() or "no emit_tool call returned"
    raise ToolGenerationError(f"model did not produce a tool: {detail}")
