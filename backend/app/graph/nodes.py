"""Node executors: the async functions that become LangGraph nodes.

Design note on interrupts: LangGraph re-executes a node function from the top
when a run resumes after `interrupt()`. To keep resume cheap and deterministic,
interrupts only ever happen *before* any side effect (LLM call, tool execution,
DB write) inside a node. That is why agents with require_approval=True simply
don't get mutating tools in their tool-use loop — mutation is expressed as a
dedicated tool node whose approval interrupt is the first thing it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.types import interrupt
from sqlalchemy import update

from ..attachments import AttachmentContent, to_content_blocks
from ..events import RunEventBus
from ..llm import LLMProvider
from ..models import Artifact, Run, RunStep
from ..tools import REGISTRY, execute_tool, tool_schemas_for
from .spec import NodeSpec, Predicate
from .state import WorkflowState


class RunRejectedError(Exception):
    """Raised when a human rejects an approval gate."""


class LoopAbortedError(Exception):
    """Raised when a tool node would keep looping to no purpose: either it hit
    a terminal (non-retryable) failure, or it exhausted its retry budget. Ends
    the run with an actionable message instead of spinning to the recursion
    limit and dying with an opaque GraphRecursionError."""


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
    # Files attached to this agent; included in every run.
    attachments: list[AttachmentContent] = field(default_factory=list)


@dataclass
class RunContext:
    run_id: int
    repo_path: Path
    agents: dict[int, AgentDef]
    provider: LLMProvider
    bus: RunEventBus
    session_factory: Any  # async_sessionmaker
    node_names: dict[str, str] = field(default_factory=dict)
    # Files attached when the run was launched; given to every agent node.
    run_attachments: list[AttachmentContent] = field(default_factory=list)
    # Default cap on how many times a single tool node may execute in one run
    # before the engine aborts it as a stuck loop (Settings.max_tool_attempts).
    max_tool_attempts: int = 5

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
        # A referenced node that hasn't executed on this path yet (e.g. a
        # loop-back prompt referencing a node only reached on retries) is
        # blank, not a literal "{node_id}" the model would otherwise see.
        return ""


def render(template: str, state: WorkflowState) -> str:
    mapping = _SafeDict(
        task=state.get("task", ""),
        repo_path=state.get("repo_path", ""),
        last_output=state.get("last_output", ""),
    )
    mapping.update(state.get("node_outputs", {}))
    return template.format_map(mapping)


# -- agent tool-use loop (shared by agent + orchestrator nodes) ----------------


@dataclass
class AgentLoopResult:
    text: str
    input_tokens: int
    output_tokens: int
    tool_calls: list[dict[str, Any]]


def build_agent_system(agent: AgentDef, repo_path: str) -> str:
    system = agent.system_prompt
    if agent.role:
        system = f"Role: {agent.role}\n\n{system}".strip()
    system += (
        f"\n\nYou are working inside the repository at: {repo_path}"
        "\nUse relative paths with your tools."
    )
    return system


async def run_agent_loop(
    agent: AgentDef,
    ctx: RunContext,
    *,
    event_node_id: str,
    prompt: str,
    attachments: list[AttachmentContent],
    extra_tools: list[dict[str, Any]] | None = None,
    extra_dispatch: dict[str, Any] | None = None,
) -> AgentLoopResult:
    """Run one agent's bounded tool-use loop and return its result.

    `extra_tools`/`extra_dispatch` let a caller inject synthetic tools (e.g. an
    orchestrator's per-agent delegation tools): any tool call whose name is in
    `extra_dispatch` is handled by the given async callable `(input) -> (success,
    output)` instead of the registry. Events and token usage are emitted under
    `event_node_id`.
    """
    system = build_agent_system(agent, str(ctx.repo_path))
    tools = tool_schemas_for(agent.tools, include_mutating=not agent.require_approval)
    if extra_tools:
        tools = tools + extra_tools
    dispatch = extra_dispatch or {}

    content: Any = prompt
    if attachments:
        content = to_content_blocks(attachments) + [{"type": "text", "text": prompt}]
    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
    tool_call_log: list[dict[str, Any]] = []
    total_in = total_out = 0
    text = ""

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
            node_id=event_node_id,
            model=agent.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        # Keep the latest *substantive* answer only. A model that emits its
        # final answer (e.g. a review + "VERDICT: APPROVE") and then makes one
        # more tool call whose turn carries little or no text would otherwise
        # have that answer clobbered by the empty turn — and, if the loop then
        # exhausts its turn/token budget, replaced by a sentinel with no verdict
        # at all, which routes an approved review back to the developer forever.
        if response.text.strip():
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
                node_id=event_node_id,
                tool=call.name,
                params=call.input,
            )
            if call.name in dispatch:
                success, output = await dispatch[call.name](call.input)
            else:
                res = await execute_tool(call.name, ctx.repo_path, call.input)
                success, output = res.success, res.output
                if call.name == "write_file" and success:
                    await ctx.save_artifact(
                        name=str(call.input.get("path", "file")),
                        kind="file",
                        content=str(call.input.get("content", "")),
                        path=str(call.input.get("path", "")),
                    )
            ctx.bus.emit(
                ctx.run_id,
                "tool_result",
                node_id=event_node_id,
                tool=call.name,
                success=success,
                output=output[:4000],
            )
            tool_call_log.append(
                {
                    "tool": call.name,
                    "params": call.input,
                    "success": success,
                    "output": output[:8000],
                }
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": output[:50_000],
                    **({} if success else {"is_error": True}),
                }
            )
        messages.append({"role": "user", "content": results})
    else:
        text = text or "(agent reached its turn limit for this run)"

    return AgentLoopResult(
        text=text,
        input_tokens=total_in,
        output_tokens=total_out,
        tool_calls=tool_call_log,
    )


# -- node factories -----------------------------------------------------------


def make_agent_node(node: NodeSpec, ctx: RunContext):
    agent = ctx.agents[node.agent_id or 0]

    async def run_agent(state: WorkflowState) -> dict[str, Any]:
        prompt = render(node.prompt or "{task}", state)
        attachments = ctx.run_attachments + agent.attachments
        step_input = {"prompt": prompt, "model": agent.model, "agent": agent.name}
        if attachments:
            step_input["attachments"] = [a.filename for a in attachments]
        step_id = await ctx.start_step(node, step_input)

        try:
            result = await run_agent_loop(
                agent,
                ctx,
                event_node_id=node.id,
                prompt=prompt,
                attachments=attachments,
            )
        except Exception:
            await ctx.finish_step(
                step_id, node, status="failed", output={"error": "agent step failed"},
                tool_calls=[],
            )
            raise

        await ctx.finish_step(
            step_id,
            node,
            status="succeeded",
            output={"text": result.text},
            tool_calls=result.tool_calls,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return {"node_outputs": {node.id: result.text}, "last_output": result.text}

    return run_agent


def _delegation_tool_name(agent: AgentDef, used: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", agent.name.lower()).strip("_") or "agent"
    name = f"delegate_to_{slug}"
    if name in used:  # disambiguate same-named agents
        name = f"{name}_{agent.id}"
    used.add(name)
    return name


def make_orchestrator_node(node: NodeSpec, ctx: RunContext):
    """Agents-as-tools: an LLM persona that delegates to a team of sub-agents.

    Each team member is exposed to the orchestrator as a `delegate_to_<name>`
    tool taking a free-text `request`. When the orchestrator calls it, that
    sub-agent runs its own tool-use loop against the request and returns its
    answer, which the orchestrator uses to decide what to do next (route to
    another agent, or produce the final response).
    """
    persona = ctx.agents[node.agent_id or 0]
    team = [ctx.agents[tid] for tid in node.team if tid in ctx.agents]

    used_names: set[str] = set()
    tool_names: dict[int, str] = {}
    delegation_tools: list[dict[str, Any]] = []
    for member in team:
        tname = _delegation_tool_name(member, used_names)
        tool_names[member.id] = tname
        can_do = member.role or "handles software-development tasks"
        toolset = ", ".join(member.tools) if member.tools else "no repository tools"
        delegation_tools.append(
            {
                "name": tname,
                "description": (
                    f"Delegate a sub-task to the '{member.name}' agent. "
                    f"{can_do}. Available tools: {toolset}. "
                    "Give it a self-contained request describing exactly what you "
                    "need; it cannot see this conversation."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "A complete, standalone instruction for the sub-agent.",
                        }
                    },
                    "required": ["request"],
                },
            }
        )

    async def run_orchestrator(state: WorkflowState) -> dict[str, Any]:
        prompt = render(node.prompt or "{task}", state)
        roster = "\n".join(
            f"- `{tool_names[m.id]}` → {m.name}: {m.role or 'general SDLC agent'}"
            for m in team
        )
        routing_note = (
            "\n\nYou are an orchestrator. You do not do the work yourself; you "
            "route each request to the most appropriate specialist agent using the "
            "delegation tools below, then combine their results into a final answer. "
            "Choose the single best agent when one clearly fits; delegate to several "
            "(sequentially) when a request has distinct parts. Available agents:\n"
            f"{roster}"
        )
        orchestrator_persona = AgentDef(
            id=persona.id,
            name=persona.name,
            role=persona.role,
            system_prompt=persona.system_prompt + routing_note,
            model=persona.model,
            max_turns=persona.max_turns,
            max_tokens=persona.max_tokens,
            tools=persona.tools,
            require_approval=persona.require_approval,
            attachments=persona.attachments,
        )

        step_input = {"prompt": prompt, "model": persona.model, "agent": persona.name}
        step_id = await ctx.start_step(node, step_input)

        def make_dispatch(member: AgentDef):
            async def dispatch(tool_input: dict[str, Any]) -> tuple[bool, str]:
                request = str(tool_input.get("request", "")).strip()
                sub_node = NodeSpec(
                    id=f"{node.id}:{tool_names[member.id]}",
                    type="agent",
                    name=member.name,
                )
                sub_step_id = await ctx.start_step(
                    sub_node,
                    {
                        "prompt": request,
                        "model": member.model,
                        "agent": member.name,
                        "delegated_by": persona.name,
                    },
                )
                try:
                    sub = await run_agent_loop(
                        member,
                        ctx,
                        event_node_id=node.id,
                        prompt=request or "(no request provided)",
                        attachments=member.attachments,
                    )
                except Exception:
                    await ctx.finish_step(
                        sub_step_id, sub_node, status="failed",
                        output={"error": "sub-agent failed"},
                    )
                    return False, f"Sub-agent '{member.name}' failed."
                await ctx.finish_step(
                    sub_step_id,
                    sub_node,
                    status="succeeded",
                    output={"text": sub.text},
                    tool_calls=sub.tool_calls,
                    input_tokens=sub.input_tokens,
                    output_tokens=sub.output_tokens,
                )
                return True, sub.text

            return dispatch

        dispatch_map = {tool_names[m.id]: make_dispatch(m) for m in team}

        try:
            result = await run_agent_loop(
                orchestrator_persona,
                ctx,
                event_node_id=node.id,
                prompt=prompt,
                attachments=ctx.run_attachments + persona.attachments,
                extra_tools=delegation_tools,
                extra_dispatch=dispatch_map,
            )
        except Exception:
            await ctx.finish_step(
                step_id, node, status="failed",
                output={"error": "orchestrator step failed"}, tool_calls=[],
            )
            raise

        await ctx.finish_step(
            step_id,
            node,
            status="succeeded",
            output={"text": result.text},
            tool_calls=result.tool_calls,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return {"node_outputs": {node.id: result.text}, "last_output": result.text}

    return run_orchestrator


def make_tool_node(node: NodeSpec, ctx: RunContext):
    tool = REGISTRY[node.tool or ""]
    max_attempts = max(1, node.max_attempts or ctx.max_tool_attempts)

    async def run_tool(state: WorkflowState) -> dict[str, Any]:
        # Loop guard, evaluated BEFORE any side effect (and before the approval
        # gate, so we never ask a human to approve a step we're about to abort).
        # Two ways a re-entry is pointless:
        #   1. a prior pass here failed terminally (missing prereq / misconfig);
        #   2. we've already burned the retry budget on this node.
        prior_attempts = state.get("attempts", {}).get(node.id, 0)
        aborted = state.get("aborted_nodes", {})
        if node.id in aborted:
            raise LoopAbortedError(aborted[node.id])
        if prior_attempts >= max_attempts:
            raise LoopAbortedError(
                f"tool node '{node.name or node.id}' ({tool.name}) exhausted its "
                f"retry budget of {max_attempts} attempts without succeeding; "
                "aborting to avoid an infinite loop."
            )

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
        attempts_now = prior_attempts + 1
        updates: dict[str, Any] = {
            "node_outputs": {node.id: result.output},
            "last_output": result.output,
            "last_tool_success": result.success,
            "last_tool_retryable": result.retryable,
            "last_tool_attempts": attempts_now,
            "attempts": {node.id: 1},
        }
        # A terminal failure doesn't raise on this pass — the workflow may have
        # an authored give-up branch (e.g. a `should_retry` condition routing
        # elsewhere) that gets to run. But we record it, so if the graph instead
        # loops straight back here, the guard above aborts before re-executing.
        if not result.success and not result.retryable:
            updates["aborted_nodes"] = {
                node.id: (
                    f"tool node '{node.name or node.id}' ({tool.name}) failed and "
                    f"cannot succeed on retry: {result.output[:500]}"
                )
            }
        return updates

    return run_tool


_EMPHASIS = str.maketrans("", "", "*_`")


def _normalize_for_match(text: str) -> str:
    """Lower-case and strip markdown emphasis / collapse whitespace before a
    substring test. An LLM told to end with a marker like ``VERDICT: APPROVE``
    routinely wraps it (``**VERDICT: APPROVE**``, ``VERDICT: **APPROVE**``) or
    wraps the line, which a raw substring match silently misses — sending, e.g.,
    an approved review down the "rejected" edge and looping forever."""
    return re.sub(r"\s+", " ", text.translate(_EMPHASIS)).lower().strip()


def _eval_predicate(
    predicate: Predicate, state: WorkflowState, *, max_attempts: int = 5
) -> bool:
    if predicate.kind == "tool_success":
        return bool(state.get("last_tool_success", False))
    if predicate.kind == "should_retry":
        # True only while retrying still has a chance: the last tool failed, the
        # failure was retryable, and the budget isn't spent. Lets a workflow
        # route a "give up" branch on the false edge instead of looping blindly.
        return (
            not state.get("last_tool_success", True)
            and state.get("last_tool_retryable", True)
            and state.get("last_tool_attempts", 0) < max_attempts
        )
    if predicate.node_id:
        subject = state.get("node_outputs", {}).get(predicate.node_id, "")
    else:
        subject = state.get("last_output", "")
    contains = _normalize_for_match(predicate.value) in _normalize_for_match(subject)
    return contains if predicate.kind == "output_contains" else not contains


def make_condition_node(node: NodeSpec, ctx: RunContext):
    predicate = node.predicate
    assert predicate is not None

    async def run_condition(state: WorkflowState) -> dict[str, Any]:
        result = _eval_predicate(predicate, state, max_attempts=ctx.max_tool_attempts)
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
        has_edit = isinstance(edited, str) and edited.strip()
        # node_outputs[node.id] is "whatever was approved here" — the edit if
        # the reviewer supplied one, else the content they approved as-is —
        # so a node many hops downstream can reference {<this_node_id>} and
        # get the right text either way, not just the immediate next node
        # (which can already use {last_output}).
        approved_text = edited if has_edit else state.get("last_output", "")
        updates: dict[str, Any] = {"node_outputs": {node.id: approved_text}}
        if has_edit:
            updates["last_output"] = edited
        await ctx.finish_step(
            step_id,
            node,
            status="succeeded",
            output={"decision": "approve", "edited": bool(edited)},
        )
        return updates

    return run_approval
