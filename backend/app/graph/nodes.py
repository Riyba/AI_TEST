"""Node executors: the async functions that become LangGraph nodes.

Design note on interrupts: LangGraph re-executes a node function from the top
when a run resumes after `interrupt()`. To keep resume cheap and deterministic,
interrupts only ever happen *before* any side effect (LLM call, tool execution,
DB write) inside a node. That is why agents with require_approval=True simply
don't get mutating tools in their tool-use loop — mutation is expressed as a
dedicated tool node whose approval interrupt is the first thing it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.types import interrupt
from sqlalchemy import update

from ..events import RunEventBus
from ..llm import LLMProvider
from ..models import Artifact, Run, RunStep
from ..tools import REGISTRY, execute_tool, tool_schemas_for
from .spec import NodeSpec, Predicate
from .state import WorkflowState


class RunRejectedError(Exception):
    """Raised when a human rejects an approval gate."""


@dataclass
class AgentDef:
    id: int
    name: str
    role: str
    system_prompt: str
    model: str
    max_turns: int
    max_tokens: int
    tools: list[str]
    require_approval: bool


@dataclass
class RunContext:
    run_id: int
    repo_path: Path
    agents: dict[int, AgentDef]
    provider: LLMProvider
    bus: RunEventBus
    session_factory: Any  # async_sessionmaker
    node_names: dict[str, str] = field(default_factory=dict)

    # -- persistence helpers -------------------------------------------------

    async def start_step(
        self, node: NodeSpec, input_data: dict[str, Any]
    ) -> int:
        async with self.session_factory() as session:
            step = RunStep(
                run_id=self.run_id,
                node_id=node.id,
                node_type=node.type,
                name=node.name or node.id,
                status="running",
                input=input_data,
            )
            session.add(step)
            await session.commit()
            step_id = step.id
        self.bus.emit(
            self.run_id,
            "node_started",
            node_id=node.id,
            node_type=node.type,
            name=node.name or node.id,
            step_id=step_id,
            input=input_data,
        )
        return step_id

    async def finish_step(
        self,
        step_id: int,
        node: NodeSpec,
        *,
        status: str,
        output: dict[str, Any],
        tool_calls: list[dict[str, Any]] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(RunStep)
                .where(RunStep.id == step_id)
                .values(
                    status=status,
                    output=output,
                    tool_calls=tool_calls or [],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            if input_tokens or output_tokens:
                await session.execute(
                    update(Run)
                    .where(Run.id == self.run_id)
                    .values(
                        total_input_tokens=Run.total_input_tokens + input_tokens,
                        total_output_tokens=Run.total_output_tokens + output_tokens,
                    )
                )
            await session.commit()
        self.bus.emit(
            self.run_id,
            "node_finished",
            node_id=node.id,
            node_type=node.type,
            name=node.name or node.id,
            step_id=step_id,
            status=status,
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def save_artifact(
        self, name: str, kind: str, content: str, path: str | None = None
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                Artifact(
                    run_id=self.run_id, name=name, kind=kind, content=content, path=path
                )
            )
            await session.commit()
        self.bus.emit(self.run_id, "artifact", name=name, kind=kind, path=path)


# -- templating ---------------------------------------------------------------


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, state: WorkflowState) -> str:
    mapping = _SafeDict(
        task=state.get("task", ""),
        repo_path=state.get("repo_path", ""),
        last_output=state.get("last_output", ""),
    )
    mapping.update(state.get("node_outputs", {}))
    return template.format_map(mapping)


# -- node factories -----------------------------------------------------------


def make_agent_node(node: NodeSpec, ctx: RunContext):
    agent = ctx.agents[node.agent_id or 0]

    async def run_agent(state: WorkflowState) -> dict[str, Any]:
        prompt = render(node.prompt or "{task}", state)
        system = agent.system_prompt
        if agent.role:
            system = f"Role: {agent.role}\n\n{system}".strip()
        system += (
            f"\n\nYou are working inside the repository at: {state.get('repo_path', '')}"
            "\nUse relative paths with your tools."
        )
        tools = tool_schemas_for(
            agent.tools, include_mutating=not agent.require_approval
        )
        step_id = await ctx.start_step(
            node, {"prompt": prompt, "model": agent.model, "agent": agent.name}
        )

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_call_log: list[dict[str, Any]] = []
        total_in = total_out = 0
        text = ""
        try:
            for _ in range(max(1, agent.max_turns)):
                response = await ctx.provider.complete(
                    model=agent.model,
                    system=system,
                    messages=messages,
                    tools=tools or None,
                )
                total_in += response.input_tokens
                total_out += response.output_tokens
                ctx.bus.emit(
                    ctx.run_id,
                    "llm_usage",
                    node_id=node.id,
                    model=agent.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
                text = response.text
                if response.stop_reason != "tool_use" or not response.tool_calls:
                    break
                if total_in + total_out >= agent.max_tokens:
                    text = (text + "\n\n" if text else "") + (
                        "(agent stopped early: reached its token limit for this run)"
                    )
                    break
                messages.append({"role": "assistant", "content": response.raw_content})
                results: list[dict[str, Any]] = []
                for call in response.tool_calls:
                    ctx.bus.emit(
                        ctx.run_id,
                        "tool_call",
                        node_id=node.id,
                        tool=call.name,
                        params=call.input,
                    )
                    result = await execute_tool(call.name, ctx.repo_path, call.input)
                    ctx.bus.emit(
                        ctx.run_id,
                        "tool_result",
                        node_id=node.id,
                        tool=call.name,
                        success=result.success,
                        output=result.output[:4000],
                    )
                    tool_call_log.append(
                        {
                            "tool": call.name,
                            "params": call.input,
                            "success": result.success,
                            "output": result.output[:8000],
                        }
                    )
                    if call.name == "write_file" and result.success:
                        await ctx.save_artifact(
                            name=str(call.input.get("path", "file")),
                            kind="file",
                            content=str(call.input.get("content", "")),
                            path=str(call.input.get("path", "")),
                        )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": result.output[:50_000],
                            **({} if result.success else {"is_error": True}),
                        }
                    )
                messages.append({"role": "user", "content": results})
            else:
                text = text or "(agent reached its turn limit for this run)"
        except Exception:
            await ctx.finish_step(
                step_id, node, status="failed", output={"error": "agent step failed"},
                tool_calls=tool_call_log, input_tokens=total_in, output_tokens=total_out,
            )
            raise

        await ctx.finish_step(
            step_id,
            node,
            status="succeeded",
            output={"text": text},
            tool_calls=tool_call_log,
            input_tokens=total_in,
            output_tokens=total_out,
        )
        return {"node_outputs": {node.id: text}, "last_output": text}

    return run_agent


def make_tool_node(node: NodeSpec, ctx: RunContext):
    tool = REGISTRY[node.tool or ""]

    async def run_tool(state: WorkflowState) -> dict[str, Any]:
        params = {
            k: render(v, state) if isinstance(v, str) else v
            for k, v in node.params.items()
        }
        # Approval gate FIRST — everything above this line is pure, so the
        # post-resume replay of this node is free of duplicated side effects.
        if tool.mutating and node.require_approval:
            decision: dict[str, Any] = interrupt(
                {
                    "kind": "tool_approval",
                    "node_id": node.id,
                    "node_name": node.name or node.id,
                    "tool": tool.name,
                    "params": {k: str(v)[:4000] for k, v in params.items()},
                    "message": f"Approve running mutating tool '{tool.name}'?",
                }
            )
            if decision.get("decision") != "approve":
                raise RunRejectedError(decision.get("note") or "rejected by user")

        step_id = await ctx.start_step(node, {"tool": tool.name, "params": {k: str(v)[:2000] for k, v in params.items()}})
        result = await execute_tool(tool.name, ctx.repo_path, params)
        if tool.name == "write_file" and result.success:
            await ctx.save_artifact(
                name=str(params.get("path", "file")),
                kind="file",
                content=str(params.get("content", "")),
                path=str(params.get("path", "")),
            )
        await ctx.finish_step(
            step_id,
            node,
            status="succeeded" if result.success else "failed",
            output={"success": result.success, "text": result.output},
        )
        return {
            "node_outputs": {node.id: result.output},
            "last_output": result.output,
            "last_tool_success": result.success,
        }

    return run_tool


def _eval_predicate(predicate: Predicate, state: WorkflowState) -> bool:
    if predicate.kind == "tool_success":
        return bool(state.get("last_tool_success", False))
    if predicate.node_id:
        subject = state.get("node_outputs", {}).get(predicate.node_id, "")
    else:
        subject = state.get("last_output", "")
    contains = predicate.value.lower() in subject.lower()
    return contains if predicate.kind == "output_contains" else not contains


def make_condition_node(node: NodeSpec, ctx: RunContext):
    predicate = node.predicate
    assert predicate is not None

    async def run_condition(state: WorkflowState) -> dict[str, Any]:
        result = _eval_predicate(predicate, state)
        step_id = await ctx.start_step(
            node, {"predicate": predicate.model_dump()}
        )
        await ctx.finish_step(
            step_id, node, status="succeeded", output={"route": result}
        )
        return {"route": result, "node_outputs": {node.id: str(result).lower()}}

    return run_condition


def route_condition(state: WorkflowState) -> str:
    return "true" if state.get("route") else "false"


def make_approval_node(node: NodeSpec, ctx: RunContext):
    async def run_approval(state: WorkflowState) -> dict[str, Any]:
        decision: dict[str, Any] = interrupt(
            {
                "kind": "approval",
                "node_id": node.id,
                "node_name": node.name or node.id,
                "message": render(node.message, state),
                "last_output": state.get("last_output", ""),
            }
        )
        if decision.get("decision") != "approve":
            raise RunRejectedError(decision.get("note") or "rejected by user")
        step_id = await ctx.start_step(node, {"message": node.message})
        edited = decision.get("edited_output")
        updates: dict[str, Any] = {"node_outputs": {node.id: "approved"}}
        if isinstance(edited, str) and edited.strip():
            updates["last_output"] = edited
            updates["node_outputs"] = {node.id: edited}
        await ctx.finish_step(
            step_id,
            node,
            status="succeeded",
            output={"decision": "approve", "edited": bool(edited)},
        )
        return updates

    return run_approval
