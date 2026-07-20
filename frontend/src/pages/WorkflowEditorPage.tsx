import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { api } from "../api";
import { useTheme } from "../theme";
import type { Agent, GraphSpec, Meta, NodeSpec, NodeType, Workflow } from "../types";

type WfData = { spec: NodeSpec; subtitle: string; isEntry: boolean; [key: string]: unknown };
type WfNode = Node<WfData>;

function WfNodeView({ data, selected }: NodeProps<WfNode>) {
  return (
    <div className={`wf-node ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className={`nt ${data.spec.type}`}>
        {data.spec.type}
        {data.isEntry ? " · entry" : ""}
      </div>
      <div className="nm">{data.spec.name || data.spec.id}</div>
      {data.subtitle && <div className="sub">{data.subtitle}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { wf: WfNodeView };

const DEFAULTS: Record<NodeType, Partial<NodeSpec>> = {
  agent: { prompt: "{task}" },
  orchestrator: { prompt: "{task}", team: [] },
  tool: { tool: "git_diff", params: {}, require_approval: true },
  condition: { predicate: { kind: "tool_success", value: "", node_id: null } },
  approval: { message: "Approve to continue?" },
};

function subtitleFor(spec: NodeSpec, agents: Agent[]): string {
  if (spec.type === "agent") {
    return agents.find((a) => a.id === spec.agent_id)?.name ?? "(no agent)";
  }
  if (spec.type === "orchestrator") {
    const persona = agents.find((a) => a.id === spec.agent_id)?.name ?? "(no agent)";
    return `${persona} · ${(spec.team ?? []).length} agents`;
  }
  if (spec.type === "tool") return spec.tool ?? "";
  if (spec.type === "condition") {
    const p = spec.predicate;
    if (!p) return "";
    return p.kind === "tool_success" ? "tool succeeded?" : `${p.kind}: "${p.value}"`;
  }
  return "";
}

export default function WorkflowEditorPage() {
  const { id } = useParams();
  const workflowId = Number(id);
  const [theme] = useTheme();
  const navigate = useNavigate();

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [entry, setEntry] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const counter = useRef(1);

  const [nodes, setNodes, onNodesChange] = useNodesState<WfNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    Promise.all([api.getWorkflow(workflowId), api.listAgents(), api.meta()])
      .then(([wf, agentList, m]) => {
        setWorkflow(wf);
        setAgents(agentList);
        setMeta(m);
        setName(wf.name);
        setDescription(wf.description);
        const graph = wf.graph as GraphSpec;
        const specNodes = graph.nodes ?? [];
        setEntry(graph.entry ?? specNodes[0]?.id ?? "");
        setNodes(
          specNodes.map((spec) => ({
            id: spec.id,
            type: "wf",
            position: spec.position ?? { x: 0, y: 0 },
            data: {
              spec,
              subtitle: subtitleFor(spec, agentList),
              isEntry: spec.id === (graph.entry ?? specNodes[0]?.id),
            },
          })),
        );
        setEdges(
          (graph.edges ?? []).map((e) => ({
            id: `${e.source}->${e.target}:${e.label ?? ""}`,
            source: e.source,
            target: e.target,
            label: e.label ?? undefined,
            markerEnd: { type: MarkerType.ArrowClosed },
          })),
        );
      })
      .catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId]);

  // Keep entry flag + subtitles in sync.
  useEffect(() => {
    setNodes((current) =>
      current.map((node) => ({
        ...node,
        data: {
          ...node.data,
          isEntry: node.id === entry,
          subtitle: subtitleFor(node.data.spec, agents),
        },
      })),
    );
  }, [entry, agents, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      const source = nodes.find((n) => n.id === connection.source);
      if (!source || !connection.source || !connection.target) return;
      setEdges((current) => {
        let next = current;
        let label: string | undefined;
        if (source.data.spec.type === "condition") {
          const existing = current.filter((e) => e.source === connection.source);
          if (existing.length >= 2) return current; // both branches wired
          label = existing.some((e) => e.label === "true") ? "false" : "true";
        } else {
          // Non-condition nodes have at most one outgoing edge — replace it.
          next = current.filter((e) => e.source !== connection.source);
        }
        return [
          ...next,
          {
            id: `${connection.source}->${connection.target}:${label ?? ""}`,
            source: connection.source,
            target: connection.target,
            label,
            markerEnd: { type: MarkerType.ArrowClosed },
          },
        ];
      });
    },
    [nodes, setEdges],
  );

  const addNode = (type: NodeType) => {
    let nodeId = "";
    do {
      nodeId = `${type}_${counter.current++}`;
    } while (nodes.some((n) => n.id === nodeId));
    const spec: NodeSpec = {
      id: nodeId,
      type,
      name: nodeId,
      position: { x: 80 + nodes.length * 40, y: 80 + (nodes.length % 5) * 60 },
      agent_id:
        type === "agent" || type === "orchestrator" ? agents[0]?.id ?? null : null,
      ...DEFAULTS[type],
    } as NodeSpec;
    setNodes((current) => [
      ...current,
      {
        id: nodeId,
        type: "wf",
        position: spec.position,
        data: { spec, subtitle: subtitleFor(spec, agents), isEntry: nodes.length === 0 },
      },
    ]);
    if (nodes.length === 0) setEntry(nodeId);
    setSelectedId(nodeId);
  };

  const updateSpec = (nodeId: string, patch: Partial<NodeSpec>) => {
    setNodes((current) =>
      current.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              data: {
                ...node.data,
                spec: { ...node.data.spec, ...patch },
                subtitle: subtitleFor({ ...node.data.spec, ...patch }, agents),
              },
            }
          : node,
      ),
    );
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    setNodes((current) => current.filter((n) => n.id !== selectedId));
    setEdges((current) =>
      current.filter((e) => e.source !== selectedId && e.target !== selectedId),
    );
    setSelectedId(null);
  };

  const toSpec = (): GraphSpec => ({
    entry,
    nodes: nodes.map((node) => ({ ...node.data.spec, position: node.position })),
    edges: edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      label: (edge.label as "true" | "false" | undefined) ?? null,
    })),
  });

  const save = async () => {
    setError("");
    setStatus("");
    try {
      await api.updateWorkflow(workflowId, { name, description, graph: toSpec() });
      setStatus("Saved ✓");
      setTimeout(() => setStatus(""), 2500);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId) ?? null,
    [nodes, selectedId],
  );

  if (!workflow) return <p className="muted">{error || "Loading…"}</p>;

  return (
    <div>
      <div className="toolbar">
        <input
          style={{ width: 260 }}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {workflow.is_template && <span className="badge template">template</span>}
        <div className="spacer" />
        <span className="muted small">{status}</span>
        <button onClick={() => addNode("agent")}>+ Agent</button>
        <button onClick={() => addNode("orchestrator")}>+ Orchestrator</button>
        <button onClick={() => addNode("tool")}>+ Tool</button>
        <button onClick={() => addNode("condition")}>+ Condition</button>
        <button onClick={() => addNode("approval")}>+ Approval</button>
        <button className="primary" onClick={save}>Save</button>
        <button onClick={() => navigate(`/runs/new?workflow=${workflowId}`)}>Run…</button>
      </div>
      {error && <div className="error-box">{error}</div>}

      <div className="editor-layout">
        <div className="editor-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            deleteKeyCode={["Backspace", "Delete"]}
            fitView
            colorMode={theme}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>

        <div className="editor-side">
          <div className="panel">
            <label>Description</label>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <label>Entry node</label>
            <select value={entry} onChange={(e) => setEntry(e.target.value)}>
              {nodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.data.spec.name || node.id}
                </option>
              ))}
            </select>
          </div>

          {selected ? (
            <div className="panel" style={{ marginTop: 12 }}>
              <h3 style={{ marginTop: 0 }}>
                {selected.data.spec.type} node <span className="muted">({selected.id})</span>
              </h3>
              <label>Name</label>
              <input
                value={selected.data.spec.name}
                onChange={(e) => updateSpec(selected.id, { name: e.target.value })}
              />
              <NodeFields
                spec={selected.data.spec}
                agents={agents}
                meta={meta}
                onChange={(patch) => updateSpec(selected.id, patch)}
              />
              <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
                <button className="danger" onClick={deleteSelected}>Delete node</button>
              </div>
            </div>
          ) : (
            <p className="muted small" style={{ padding: 12 }}>
              Select a node to edit it. Drag between node handles to connect. Placeholders
              usable in prompts and tool params: {"{task}"}, {"{repo_path}"},{" "}
              {"{last_output}"}, and {"{<node_id>}"} for any earlier node's output.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function NodeFields({
  spec,
  agents,
  meta,
  onChange,
}: {
  spec: NodeSpec;
  agents: Agent[];
  meta: Meta | null;
  onChange: (patch: Partial<NodeSpec>) => void;
}) {
  const [paramsText, setParamsText] = useState(JSON.stringify(spec.params ?? {}, null, 2));
  const [paramsError, setParamsError] = useState("");

  useEffect(() => {
    setParamsText(JSON.stringify(spec.params ?? {}, null, 2));
    setParamsError("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec.id]);

  if (spec.type === "agent") {
    return (
      <>
        <label>Agent</label>
        <select
          value={spec.agent_id ?? ""}
          onChange={(e) => onChange({ agent_id: Number(e.target.value) })}
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name} · {a.model}</option>
          ))}
        </select>
        <label>Prompt template</label>
        <textarea
          rows={7}
          value={spec.prompt ?? ""}
          onChange={(e) => onChange({ prompt: e.target.value })}
        />
      </>
    );
  }

  if (spec.type === "orchestrator") {
    const team = spec.team ?? [];
    const toggleMember = (agentId: number) =>
      onChange({
        team: team.includes(agentId)
          ? team.filter((t) => t !== agentId)
          : [...team, agentId],
      });
    return (
      <>
        <label>Orchestrator agent (the router persona)</label>
        <select
          value={spec.agent_id ?? ""}
          onChange={(e) => onChange({ agent_id: Number(e.target.value) })}
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name} · {a.model}</option>
          ))}
        </select>
        <label>Team — agents exposed as delegation tools</label>
        <div className="team-picker">
          {agents
            .filter((a) => a.id !== spec.agent_id)
            .map((a) => (
              <div key={a.id} className="checkbox-row">
                <input
                  id={`team-${spec.id}-${a.id}`}
                  type="checkbox"
                  checked={team.includes(a.id)}
                  onChange={() => toggleMember(a.id)}
                />
                <label htmlFor={`team-${spec.id}-${a.id}`}>
                  {a.name} <span className="muted small">· {a.role || a.model}</span>
                </label>
              </div>
            ))}
        </div>
        {team.length === 0 && (
          <p className="warn small">Select at least one team member.</p>
        )}
        <label>Prompt template</label>
        <textarea
          rows={5}
          value={spec.prompt ?? ""}
          onChange={(e) => onChange({ prompt: e.target.value })}
        />
        <p className="muted small">
          The orchestrator LLM receives one <code>delegate_to_&lt;agent&gt;</code> tool per
          team member and decides which specialist handles the request, then synthesizes
          the result.
        </p>
      </>
    );
  }

  if (spec.type === "tool") {
    const toolMeta = meta?.tools.find((t) => t.name === spec.tool);
    return (
      <>
        <label>Tool</label>
        <select value={spec.tool ?? ""} onChange={(e) => onChange({ tool: e.target.value })}>
          {(meta?.tools ?? []).map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}{t.mutating ? " ⚠" : ""}
            </option>
          ))}
        </select>
        {toolMeta && <p className="muted small">{toolMeta.description}</p>}
        <label>Params (JSON, values support templating)</label>
        <textarea
          rows={6}
          value={paramsText}
          onChange={(e) => {
            setParamsText(e.target.value);
            try {
              onChange({ params: JSON.parse(e.target.value) as Record<string, unknown> });
              setParamsError("");
            } catch {
              setParamsError("invalid JSON — not saved yet");
            }
          }}
        />
        {paramsError && <p className="warn small">{paramsError}</p>}
        {toolMeta?.mutating && (
          <div className="checkbox-row">
            <input
              id={`appr-${spec.id}`}
              type="checkbox"
              checked={spec.require_approval ?? true}
              onChange={(e) => onChange({ require_approval: e.target.checked })}
            />
            <label htmlFor={`appr-${spec.id}`}>
              Pause for human approval before executing
            </label>
          </div>
        )}
      </>
    );
  }

  if (spec.type === "condition") {
    const predicate = spec.predicate ?? { kind: "tool_success" as const, value: "", node_id: null };
    return (
      <>
        <label>Predicate</label>
        <select
          value={predicate.kind}
          onChange={(e) =>
            onChange({ predicate: { ...predicate, kind: e.target.value as typeof predicate.kind } })
          }
        >
          <option value="tool_success">last tool succeeded</option>
          <option value="output_contains">output contains…</option>
          <option value="output_not_contains">output does not contain…</option>
        </select>
        {predicate.kind !== "tool_success" && (
          <>
            <label>Substring</label>
            <input
              value={predicate.value}
              onChange={(e) => onChange({ predicate: { ...predicate, value: e.target.value } })}
            />
            <label>Inspect node output (blank = last output)</label>
            <input
              value={predicate.node_id ?? ""}
              onChange={(e) =>
                onChange({ predicate: { ...predicate, node_id: e.target.value || null } })
              }
              placeholder="node id"
            />
          </>
        )}
        <p className="muted small">
          Wire two outgoing edges: the first gets labeled <b>true</b>, the second <b>false</b>.
        </p>
      </>
    );
  }

  return (
    <>
      <label>Approval message (templated)</label>
      <textarea
        rows={4}
        value={spec.message ?? ""}
        onChange={(e) => onChange({ message: e.target.value })}
      />
      <p className="muted small">
        The run pauses here. The reviewer can approve, reject, or edit the current output
        before the graph continues.
      </p>
    </>
  );
}
