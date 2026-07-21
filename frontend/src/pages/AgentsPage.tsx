import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import AttachmentsEditor from "../components/AttachmentsEditor";
import type { Agent, AgentInput, Meta } from "../types";

const EMPTY: AgentInput = {
  name: "",
  role: "",
  system_prompt: "",
  model: "claude-sonnet-5",
  max_turns: 10,
  max_tokens: 100_000,
  tools: [],
  require_approval: true,
};

const FIELD_HELP = {
  name: "A short label so you can recognize this agent in lists and workflows.",
  model:
    "Which AI model the agent uses — its \"brain\". Smarter models give better results but are slower and cost more; smaller ones are fast and cheap. Pick a suggestion or type a model name.",
  role:
    "One sentence describing who the agent should act as, e.g. \"a careful senior engineer\". This shapes the tone and focus of everything it writes.",
  system_prompt:
    "The agent's standing instructions, followed on every run. Describe what it should do, how to present results, and anything it must never do.",
  max_turns:
    "How many back-and-forth steps the agent may take in one run. Each step is one \"thought\", possibly using a tool. More steps let it dig deeper, but take longer and cost more. 10 is a good starting point.",
  max_tokens:
    "A budget for how much text the agent may read and write in one run, measured in tokens (a token is roughly three-quarters of a word — it's what you pay for). The agent stops early if it hits this limit. 100,000 is a good starting point.",
  tools:
    "What the agent is allowed to do, like reading files or checking git history. Give it only what it needs. Items marked ⚠ can change files on your computer.",
  safe_mode:
    "When on, the agent can never change files on its own — any change (marked ⚠) must first be approved by you in the workflow. Recommended unless you fully trust the agent.",
  attachments:
    "Files the agent gets to read on every run — style guides, specs, reference docs, screenshots. Images, PDFs, and text files up to 5 MB each.",
};

function Info({ text }: { text: string }) {
  return (
    <span className="info-icon" tabIndex={0} aria-label={text}>
      i<span className="info-tip" role="tooltip">{text}</span>
    </span>
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [editing, setEditing] = useState<{ id: number | null; data: AgentInput } | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);

  const reload = () => api.listAgents().then(setAgents).catch((e) => setError(e.message));

  useEffect(() => {
    reload();
    api.meta().then(setMeta).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (editing) panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [editing]);

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

  const visibleAgents = agents.filter((a) =>
    a.name.toLowerCase().includes(filter.trim().toLowerCase())
  );

  return (
    <div>
      <div className="toolbar">
        <h2>Agents</h2>
        <div className="spacer" />
        <input
          className="search-input"
          placeholder="Filter by name…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="primary" onClick={() => setEditing({ id: null, data: { ...EMPTY } })}>
          New agent
        </button>
      </div>
      {error && <div className="error-box">{error}</div>}

      {editing && (
        <div className="panel" style={{ marginBottom: 20 }} ref={panelRef}>
          <h3 style={{ marginTop: 0 }}>{editing.id === null ? "New agent" : "Edit agent"}</h3>
          <div className="form-grid">
            <div>
              <label>Name <Info text={FIELD_HELP.name} /></label>
              <input value={editing.data.name} onChange={(e) => set({ name: e.target.value })} />
            </div>
            <div>
              <label>Model <Info text={FIELD_HELP.model} /></label>
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
              <label>Role / persona <Info text={FIELD_HELP.role} /></label>
              <input
                value={editing.data.role}
                onChange={(e) => set({ role: e.target.value })}
                placeholder="e.g. Senior engineer performing careful code review"
              />
            </div>
            <div className="full">
              <label>System prompt <Info text={FIELD_HELP.system_prompt} /></label>
              <textarea
                rows={6}
                value={editing.data.system_prompt}
                onChange={(e) => set({ system_prompt: e.target.value })}
              />
            </div>
            <div>
              <label>Max turns per run <Info text={FIELD_HELP.max_turns} /></label>
              <input
                type="number" min={1} max={100} step={1}
                value={editing.data.max_turns}
                onChange={(e) => set({ max_turns: Number(e.target.value) })}
              />
            </div>
            <div>
              <label>Max tokens per run <Info text={FIELD_HELP.max_tokens} /></label>
              <input
                type="number" min={1000} max={10_000_000} step={1000}
                value={editing.data.max_tokens}
                onChange={(e) => set({ max_tokens: Number(e.target.value) })}
              />
            </div>
            <div className="full">
              <label>Tool permissions <Info text={FIELD_HELP.tools} /></label>
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
            <div className="full">
              <label>Attachments <Info text={FIELD_HELP.attachments} /></label>
              {editing.id === null ? (
                <p className="muted small" style={{ margin: "4px 0" }}>
                  Save the agent first, then edit it to attach files.
                </p>
              ) : (
                <AttachmentsEditor agentId={editing.id} />
              )}
            </div>
            <div className="full checkbox-row">
              <input
                id="reqappr" type="checkbox"
                checked={editing.data.require_approval}
                onChange={(e) => set({ require_approval: e.target.checked })}
              />
              <label htmlFor="reqappr">
                Safe mode: the agent can't make changes on its own — anything marked ⚠ needs
                your approval first. <Info text={FIELD_HELP.safe_mode} />
              </label>
            </div>
          </div>
          <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
            <button
              className="primary"
              onClick={save}
              disabled={
                !editing.data.name.trim() ||
                editing.data.max_turns < 1 ||
                editing.data.max_tokens < 1000
              }
            >
              Save
            </button>
            <button onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="card-list">
        {visibleAgents.map((agent) => (
          <div className="card" key={agent.id}>
            <div className="grow">
              <h4>
                {agent.name}{" "}
                {agent.is_template && <span className="badge template">template</span>}
              </h4>
              <p>
                {agent.model} · tools: {agent.tools.length ? agent.tools.join(", ") : "none"} ·{" "}
                {agent.max_turns} turns · {agent.max_tokens.toLocaleString()} tokens ·{" "}
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
                    max_turns: agent.max_turns,
                    max_tokens: agent.max_tokens,
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
        {visibleAgents.length === 0 && (
          <p className="muted">{agents.length === 0 ? "No agents yet." : "No agents match your filter."}</p>
        )}
      </div>
    </div>
  );
}
