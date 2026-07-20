import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { TimeSavedEditor, formatTimeSaved } from "../components/TimeSaved";
import type { Run, RunStatus } from "../types";

const TERMINAL: RunStatus[] = ["succeeded", "failed", "rejected", "cancelled"];

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [datadogConfigured, setDatadogConfigured] = useState(false);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.meta().then((m) => setDatadogConfigured(m.datadog_configured)).catch(() => undefined);
    api.listRuns().then(setRuns).catch((e) => setError(e.message));
    const timer = setInterval(() => {
      api.listRuns().then(setRuns).catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  const retrySync = (runId: number) => {
    setSyncingId(runId);
    api
      .retryDatadogSync(runId)
      .then((updated) => {
        setRuns((current) =>
          current.map((r) => (r.id === updated.id ? { ...r, ...updated } : r)),
        );
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setSyncingId(null));
  };

  const saveTimeSaved = (runId: number, minutes: number | null) => {
    setSaving(true);
    api
      .setTimeSaved(runId, minutes)
      .then((updated) => {
        setRuns((current) =>
          current.map((r) => (r.id === updated.id ? { ...r, ...updated } : r)),
        );
        setEditingId(null);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setSaving(false));
  };

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
            <th>Tokens (in/out)</th><th>Time saved</th>
            {datadogConfigured && <th>Datadog</th>}
            <th>Started</th>
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
              <td>
                {editingId === run.id ? (
                  <TimeSavedEditor
                    initial={run.time_saved_minutes}
                    busy={saving}
                    dismissLabel="Cancel"
                    allowClear
                    onSave={(minutes) => saveTimeSaved(run.id, minutes)}
                    onDismiss={() => setEditingId(null)}
                  />
                ) : (
                  <span className="time-saved-cell">
                    {formatTimeSaved(run.time_saved_minutes)}
                    {TERMINAL.includes(run.status) && (
                      <button
                        className="link-btn"
                        title="Edit estimated time saved"
                        onClick={() => setEditingId(run.id)}
                      >
                        edit
                      </button>
                    )}
                  </span>
                )}
              </td>
              {datadogConfigured && (
                <td>
                  {run.synced_to_datadog ? (
                    <span title="Metrics synced to Datadog">✓ synced</span>
                  ) : TERMINAL.includes(run.status) ? (
                    <button
                      className="link-btn"
                      title="Metrics not synced — retry Datadog submission"
                      disabled={syncingId === run.id}
                      onClick={() => retrySync(run.id)}
                    >
                      {syncingId === run.id ? "syncing…" : "not synced — retry"}
                    </button>
                  ) : (
                    <span className="muted">–</span>
                  )}
                </td>
              )}
              <td className="muted">{new Date(run.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
    </div>
  );
}
