import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import OverflowMenu from "../OverflowMenu";
import { api } from "../api";
import { downloadJson, pickJsonFile, slugForFilename } from "../lib/exportFile";
import type { Workflow, WorkflowExport } from "../types";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const navigate = useNavigate();

  const reload = () => api.listWorkflows().then(setWorkflows).catch((e) => setError(e.message));
  useEffect(() => { reload(); }, []);

  const createNew = async () => {
    try {
      const wf = await api.createWorkflow({ name: "New workflow", description: "", graph: {} });
      navigate(`/workflows/${wf.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const clone = async (id: number) => {
    try {
      const copy = await api.cloneWorkflow(id);
      navigate(`/workflows/${copy.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this workflow?")) return;
    try {
      await api.deleteWorkflow(id);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const exportWorkflow = async (wf: Workflow) => {
    try {
      const data = await api.exportWorkflow(wf.id);
      downloadJson(`workflow-${slugForFilename(wf.name)}.json`, data);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const importWorkflow = async () => {
    setError("");
    try {
      const data = (await pickJsonFile()) as WorkflowExport;
      if (data.format !== "workflow")
        throw new Error(`Not a workflow export (format: "${data.format}")`);
      const wf = await api.importWorkflow(data);
      navigate(`/workflows/${wf.id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const matches = (w: Workflow) => w.name.toLowerCase().includes(filter.trim().toLowerCase());
  const templates = workflows.filter((w) => w.is_template && matches(w));
  const own = workflows.filter((w) => !w.is_template && matches(w));

  // Templates are read-only — clicking the name opens the read-only viewer, and
  // the only way to change one is to Clone it. Own workflows open in the editor.
  const linkFor = (wf: Workflow) =>
    wf.is_template ? `/workflows/${wf.id}?view=1` : `/workflows/${wf.id}`;

  const renderCard = (wf: Workflow) => (
    <div className="card" key={wf.id}>
      <div className="grow">
        <h4>
          <Link to={linkFor(wf)}>{wf.name}</Link>{" "}
          {wf.is_template && <span className="badge template">template</span>}
        </h4>
        <p>{wf.description || "No description"}</p>
      </div>
      <button className="primary" onClick={() => navigate(`/runs/new?workflow=${wf.id}`)}>
        Run
      </button>
      <OverflowMenu>
        {(close) => (
          <>
            {wf.is_template ? (
              <button role="menuitem" onClick={() => { close(); navigate(`/workflows/${wf.id}?view=1`); }}>
                View
              </button>
            ) : (
              <button role="menuitem" onClick={() => { close(); navigate(`/workflows/${wf.id}`); }}>
                Edit
              </button>
            )}
            <button role="menuitem" onClick={() => { close(); clone(wf.id); }}>
              Clone
            </button>
            <button role="menuitem" onClick={() => { close(); exportWorkflow(wf); }}>
              Export
            </button>
            {!wf.is_template && (
              <>
                <div className="overflow-divider" />
                <button className="danger" role="menuitem" onClick={() => { close(); remove(wf.id); }}>
                  Delete
                </button>
              </>
            )}
          </>
        )}
      </OverflowMenu>
    </div>
  );

  return (
    <div>
      <div className="toolbar">
        <h2>Workflows</h2>
        <div className="spacer" />
        <input
          className="search-input"
          placeholder="Filter by name…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button onClick={importWorkflow}>Import</button>
        <button className="primary" onClick={createNew}>New workflow</button>
      </div>
      {error && <div className="error-box">{error}</div>}

      {own.length > 0 && (
        <>
          <h3>Your workflows</h3>
          <div className="card-list">{own.map(renderCard)}</div>
        </>
      )}

      <h3>Templates</h3>
      <p className="muted small">
        Read-only starter SDLC workflows. <b>View</b> one to inspect it, or <b>Clone</b> to
        make an editable copy — templates themselves can't be changed, so the original always
        stays intact.
      </p>
      <div className="card-list">{templates.map(renderCard)}</div>
    </div>
  );
}
