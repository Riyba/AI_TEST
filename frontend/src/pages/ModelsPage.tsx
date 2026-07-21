import { useEffect, useState } from "react";
import { api } from "../api";
import type { SuggestedModel } from "../types";

export default function ModelsPage() {
  const [models, setModels] = useState<SuggestedModel[]>([]);
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  const reload = () => api.listModels().then(setModels).catch((e) => setError(e.message));

  useEffect(() => {
    reload();
  }, []);

  const add = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setError("");
    setAdding(true);
    try {
      await api.createModel(trimmed);
      setName("");
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAdding(false);
    }
  };

  const remove = async (model: SuggestedModel) => {
    setError("");
    try {
      await api.deleteModel(model.id);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const visibleModels = models.filter((m) =>
    m.name.toLowerCase().includes(filter.trim().toLowerCase())
  );

  return (
    <div>
      <div className="toolbar">
        <h2>Models</h2>
        <div className="spacer" />
        <input
          className="search-input"
          placeholder="Filter by name…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <p className="muted small" style={{ marginTop: -6 }}>
        The model ids suggested in the agent and tool-builder pickers. These are
        suggestions only — you can still type any model name when configuring an
        agent — so removing one here never affects existing agents.
      </p>
      {error && <div className="error-box">{error}</div>}

      <div className="panel" style={{ marginBottom: 20 }}>
        <label>Add a model</label>
        <div className="toolbar" style={{ marginTop: 6, marginBottom: 0, gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: "1 1 260px" }}
            placeholder="e.g. eu.anthropic.claude-opus-4-8"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") add();
            }}
          />
          <button className="primary" onClick={add} disabled={adding || !name.trim()}>
            {adding ? "Adding…" : "Add model"}
          </button>
        </div>
      </div>

      <div className="card-list">
        {visibleModels.map((model) => (
          <div className="card" key={model.id}>
            <div className="grow">
              <h4 className="mono">{model.name}</h4>
            </div>
            <button className="danger" onClick={() => remove(model)}>Remove</button>
          </div>
        ))}
        {visibleModels.length === 0 && (
          <p className="muted">
            {models.length === 0
              ? "No suggested models. Add one above — until you do, the built-in defaults are offered."
              : "No models match your filter."}
          </p>
        )}
      </div>
    </div>
  );
}
