import { useEffect, useState } from "react";
import { api } from "../api";
import type { Agent, AgentInput, Meta } from "../types";

const EMPTY: AgentInput = {
  name: "",
  role: "",
  system_prompt: "",
  model: "claude-sonnet-5",
  temperature: null,
  tools: [],
  require_approval: true,
};

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [editing, setEditing] = useState<{ id: number | null; data: AgentInput } | null>(null);
  const [error, setError] = useState("");

  const reload = () => api.listAgents().then(setAgents).catch((e) => setError(e.message));

  useEffect(() => {
    reload();
    api.meta().then(setMeta).catch(() => undefined);
  }, []);

  const save = async () => {
    if (!editing) return;
    setError("");
    try {
      if (editing.id === null) await api.createAgent(editing.data);
      else await api.updateAgent(editing.id, editing.data);
      setEditing(null);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this agent? Workflows referencing it will fail to run.")) return;
    try {
      await api.deleteAgent(id);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const set = (patch: Partial<AgentInput>) =>
    setEditing((cur) => (cur ? { ...cur, data: { ...cur.data, ...patch } } : cur));

  return (
    <div>
      <div className="toolbar">
        <h2>Agents</h2>
        <div className="spacer" />
        <button className="primary" onClick={() => setEditing({ id: null, data: { ...EMPTY } })}>
          New agent
        </button>
      </div>
      {error && <div className="error-box">{error}</div>}

      {editing && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <h3 style={{ marginTop: 0 }}>{editing.id === null ? "New agent" : "Edit agent"}</h3>
          <div className="form-grid">
            <div>
              <label>Name</label>
              <input value={editing.data.name} onChange={(e) => set({ name: e.target.value })} />
            </div>
            <div>
              <label>Model</label>
              <input
                value={editing.data.model}
                onChange={(e) => set({ model: e.target.value })}
                list="model-suggestions"
                placeholder="e.g. claude-sonnet-5"
              />
              <datalist id="model-suggestions">
                {meta?.models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            <div className="full">
              <label>Role / persona</label>
              <input
                value={editing.data.role}
                onChange={(e) => set({ role: e.target.value })}
                placeholder="e.g. Senior engineer performing careful code review"
              />
            </div>
            <div className="full">
              <label>System prompt</label>
              <textarea
                rows={6}
                value={editing.data.system_prompt}
                onChange={(e) => set({ system_prompt: e.target.value })}
              />
            </div>
            <div>
              <label>Temperature (only honored on models that accept sampling params)</label>
              <input
                type="number" min={0} max={1} step={0.1}
                value={editing.data.temperature ?? ""}
                onChange={(e) =>
                  set({ temperature: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </div>
            <div className="full">
              <label>Tool permissions</label>
              <div className="tool-check-list">
                {(meta?.tools ?? []).map((tool) => {
                  const on = editing.data.tools.includes(tool.name);
                  return (
                    <span
                      key={tool.name}
                      title={tool.description}
                      className={`tool-chip ${on ? "on" : ""} ${tool.mutating ? "mutating" : ""}`}
                      onClick={() =>
                        set({
                          tools: on
                            ? editing.data.tools.filter((t) => t !== tool.name)
                            : [...editing.data.tools, tool.name],
                        })
                      }
                    >
                      {tool.name}
                      {tool.mutating ? " ⚠" : ""}
                    </span>
                  );
                })}
              </div>
            </div>
            <div className="full checkbox-row">
              <input
                id="reqappr" type="checkbox"
                checked={editing.data.require_approval}
                onChange={(e) => set({ require_approval: e.target.checked })}
              />
              <label htmlFor="reqappr">
                Safe mode: exclude mutating tools (⚠) from this agent's autonomous tool loop.
                Mutations then only happen via approval-gated workflow tool nodes.
              </label>
            </div>
          </div>
          <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
            <button className="primary" onClick={save} disabled={!editing.data.name.trim()}>
              Save
            </button>
            <button onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="card-list">
        {agents.map((agent) => (
          <div className="card" key={agent.id}>
            <div className="grow">
              <h4>
                {agent.name}{" "}
                {agent.is_template && <span className="badge template">template</span>}
              </h4>
              <p>
                {agent.model} · tools: {agent.tools.length ? agent.tools.join(", ") : "none"} ·{" "}
                {agent.require_approval ? "safe mode" : "autonomous mutations"}
              </p>
            </div>
            <button
              onClick={() =>
                setEditing({
                  id: agent.id,
                  data: {
                    name: agent.name,
                    role: agent.role,
                    system_prompt: agent.system_prompt,
                    model: agent.model,
                    temperature: agent.temperature,
                    tools: agent.tools,
                    require_approval: agent.require_approval,
                  },
                })
              }
            >
              Edit
            </button>
            <button className="danger" onClick={() => remove(agent.id)}>Delete</button>
          </div>
        ))}
        {agents.length === 0 && <p className="muted">No agents yet.</p>}
      </div>
    </div>
  );
}
