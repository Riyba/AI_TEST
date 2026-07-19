import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Run } from "../types";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api.listRuns().then(setRuns).catch((e) => setError(e.message));
    const timer = setInterval(() => {
      api.listRuns().then(setRuns).catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div>
      <div className="toolbar">
        <h2>Run history</h2>
        <div className="spacer" />
        <button className="primary" onClick={() => navigate("/runs/new")}>New run</button>
      </div>
      {error && <div className="error-box">{error}</div>}
      <table className="step-table">
        <thead>
          <tr>
            <th>#</th><th>Workflow</th><th>Task</th><th>Status</th>
            <th>Tokens (in/out)</th><th>Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td><Link to={`/runs/${run.id}`}>{run.id}</Link></td>
              <td>{run.workflow_name}</td>
              <td className="muted">{(run.input.task ?? "").slice(0, 60)}</td>
              <td><span className={`badge ${run.status}`}>{run.status}</span></td>
              <td className="muted">
                {run.total_input_tokens} / {run.total_output_tokens}
              </td>
              <td className="muted">{new Date(run.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
    </div>
  );
}
