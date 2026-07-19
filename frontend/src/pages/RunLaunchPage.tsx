import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Meta, Workflow } from "../types";

export default function RunLaunchPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [workflowId, setWorkflowId] = useState<number | "">(
    params.get("workflow") ? Number(params.get("workflow")) : "",
  );
  const [task, setTask] = useState("");
  const [repoPath, setRepoPath] = useState(localStorage.getItem("lastRepoPath") ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listWorkflows().then(setWorkflows).catch((e) => setError(e.message));
    api.meta().then(setMeta).catch(() => undefined);
  }, []);

  const launch = async () => {
    if (workflowId === "") return;
    setBusy(true);
    setError("");
    try {
      localStorage.setItem("lastRepoPath", repoPath);
      const run = await api.createRun({
        workflow_id: workflowId,
        task,
        repo_path: repoPath,
      });
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 640 }}>
      <h2>New run</h2>
      {error && <div className="error-box">{error}</div>}
      {meta && meta.project_roots.length === 0 && (
        <div className="warn" style={{ marginBottom: 12 }}>
          PROJECT_ROOTS is not configured in backend/.env — runs will be rejected until you
          set the directories runs may target.
        </div>
      )}
      <div className="panel">
        <label>Workflow</label>
        <select
          value={workflowId}
          onChange={(e) => setWorkflowId(e.target.value === "" ? "" : Number(e.target.value))}
        >
          <option value="">Select a workflow…</option>
          {workflows.map((wf) => (
            <option key={wf.id} value={wf.id}>
              {wf.name}{wf.is_template ? " (template)" : ""}
            </option>
          ))}
        </select>

        <label>Repository path (must be inside PROJECT_ROOTS)</label>
        <input
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          placeholder="/Users/you/Dev/my-project"
        />

        <label>Task / target (available to prompts as {"{task}"})</label>
        <textarea
          rows={3}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="e.g. Generate tests for src/utils/parser.py"
        />

        <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
          <button
            className="primary"
            disabled={busy || workflowId === "" || !repoPath.trim()}
            onClick={launch}
          >
            {busy ? "Starting…" : "Start run"}
          </button>
        </div>
      </div>
    </div>
  );
}
