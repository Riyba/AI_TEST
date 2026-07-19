import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { TimeSavedEditor, formatTimeSaved } from "../components/TimeSaved";
import type { ApprovalPayload, RunDetail, RunEvent, RunStatus } from "../types";

const TERMINAL: RunStatus[] = ["succeeded", "failed", "rejected", "cancelled"];

export default function RunDetailPage() {
  const { id } = useParams();
  const runId = Number(id);

  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [approval, setApproval] = useState<ApprovalPayload | null>(null);
  const [error, setError] = useState("");
  const [timeSavedPrompt, setTimeSavedPrompt] = useState(false);
  const [savingTime, setSavingTime] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  // Only prompt for an estimate when the run finished while being watched;
  // already-finished runs are edited from Run history instead.
  const sawActiveRef = useRef(false);
  const promptDismissedRef = useRef(false);

  useEffect(() => {
    if (!run) return;
    if (!TERMINAL.includes(run.status)) {
      sawActiveRef.current = true;
      return;
    }
    if (
      sawActiveRef.current &&
      !promptDismissedRef.current &&
      run.time_saved_minutes == null
    ) {
      setTimeSavedPrompt(true);
    }
  }, [run?.status, run?.time_saved_minutes]);

  const submitTimeSaved = (minutes: number | null) => {
    setSavingTime(true);
    api
      .setTimeSaved(runId, minutes)
      .then(() => {
        promptDismissedRef.current = true;
        setTimeSavedPrompt(false);
        refetch();
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setSavingTime(false));
  };

  const refetch = useCallback(() => {
    api.getRun(runId).then(setRun).catch((e) => setError((e as Error).message));
  }, [runId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  useEffect(() => {
    if (!run || sourceRef.current) return;
    if (TERMINAL.includes(run.status) && events.length === 0) return; // pure replay from DB
    const source = new EventSource(`/api/runs/${runId}/events`);
    sourceRef.current = source;
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent;
      setEvents((current) =>
        current.some((e) => e.seq === event.seq) ? current : [...current, event],
      );
      if (event.type === "approval_requested") {
        setApproval(event.payload as ApprovalPayload);
      }
      if (event.type === "run_status") {
        setRun((current) =>
          current ? { ...current, status: event.status as RunStatus } : current,
        );
        if (event.status !== "waiting_approval") setApproval(null);
      }
      if (event.type === "node_finished" || event.type === "run_finished") {
        refetch();
      }
    };
    source.addEventListener("done", () => {
      source.close();
      sourceRef.current = null;
      refetch();
    });
    source.onerror = () => {
      // Server gone or stream ended; final state comes from the DB.
      source.close();
      sourceRef.current = null;
    };
    return () => {
      source.close();
      sourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run === null, runId]);

  if (!run) return <p className="muted">{error || "Loading…"}</p>;

  const active = !TERMINAL.includes(run.status);

  return (
    <div>
      <div className="toolbar">
        <h2>
          Run #{run.id} · {run.workflow_name}
        </h2>
        <span className={`badge ${run.status}`}>{run.status}</span>
        <div className="spacer" />
        {active && (
          <button
            className="danger"
            onClick={() => api.cancelRun(runId).then(refetch).catch((e) => setError(e.message))}
          >
            Cancel run
          </button>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
      {run.error && <div className="error-box">{run.error}</div>}
      <p className="muted small">
        repo: {run.input.repo_path} · task: {run.input.task || "(none)"} · tokens:{" "}
        {run.total_input_tokens} in / {run.total_output_tokens} out · time saved:{" "}
        {formatTimeSaved(run.time_saved_minutes)}
      </p>

      {timeSavedPrompt && (
        <div className="time-saved-prompt">
          <h3>How much time did this run save you?</h3>
          <p className="muted small">
            Your estimate feeds the time-savings metrics. Click Done to skip —
            you can add it later from <Link to="/runs">Run history</Link>.
          </p>
          <TimeSavedEditor
            initial={null}
            busy={savingTime}
            dismissLabel="Done"
            onSave={submitTimeSaved}
            onDismiss={() => {
              promptDismissedRef.current = true;
              setTimeSavedPrompt(false);
            }}
          />
        </div>
      )}

      {approval && run.status === "waiting_approval" && (
        <ApprovalForm
          payload={approval}
          onSubmit={(decision, note, edited) => {
            setError("");
            api
              .submitApproval(runId, { decision, note, edited_output: edited })
              .then(() => setApproval(null))
              .catch((e) => setError((e as Error).message));
          }}
        />
      )}
      {run.status === "waiting_approval" && !approval && (
        <div className="warn" style={{ marginBottom: 12 }}>
          This run is waiting for approval, but the approval prompt was lost (server
          restart). Re-open it from the live stream is not possible — cancel and re-run.
        </div>
      )}

      <div className="split">
        <div className="main-col">
          <h3>Live trace</h3>
          {events.length === 0 && (
            <p className="muted small">
              {active ? "Waiting for events…" : "No live events (finished run) — see steps below."}
            </p>
          )}
          <div className="trace">
            {events.map((event) => (
              <TraceEvent key={event.seq} event={event} />
            ))}
          </div>

          <h3>Steps</h3>
          <table className="step-table">
            <thead>
              <tr>
                <th>Node</th><th>Type</th><th>Status</th><th>Tokens</th><th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {run.steps.map((step) => (
                <tr key={step.id}>
                  <td>{step.name}</td>
                  <td className="muted">{step.node_type}</td>
                  <td><span className={`badge ${step.status}`}>{step.status}</span></td>
                  <td className="muted">
                    {step.input_tokens + step.output_tokens > 0
                      ? `${step.input_tokens}/${step.output_tokens}`
                      : "–"}
                  </td>
                  <td>
                    <details className="raw">
                      <summary>in / out / tool calls</summary>
                      <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                        {JSON.stringify(
                          { input: step.input, output: step.output, tool_calls: step.tool_calls },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="side-col">
          <h3>Artifacts</h3>
          {run.artifacts.length === 0 && <p className="muted small">None yet.</p>}
          {run.artifacts.map((artifact) => (
            <div className="panel" key={artifact.id} style={{ marginBottom: 10 }}>
              <b>{artifact.name}</b> <span className="badge">{artifact.kind}</span>
              {artifact.path && <p className="muted small">{artifact.path}</p>}
              <pre
                style={{
                  whiteSpace: "pre-wrap", fontSize: 12, maxHeight: 300,
                  overflow: "auto", background: "var(--bg)", padding: 8, borderRadius: 4,
                }}
              >
                {artifact.content}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TraceEvent({ event }: { event: RunEvent }) {
  const time = new Date(event.ts * 1000).toLocaleTimeString();
  let title = event.type;
  let body: string | null = null;

  switch (event.type) {
    case "run_status":
      title = `run → ${event.status as string}`;
      if (event.error) body = String(event.error);
      break;
    case "node_started":
      title = `▶ ${event.name as string} (${event.node_type as string})`;
      break;
    case "node_finished":
      title = `✓ ${event.name as string} — ${event.status as string}`;
      body =
        typeof (event.output as Record<string, unknown> | undefined)?.text === "string"
          ? String((event.output as Record<string, unknown>).text).slice(0, 2000)
          : null;
      break;
    case "tool_call":
      title = `tool call: ${event.tool as string}`;
      body = JSON.stringify(event.params, null, 2);
      break;
    case "tool_result":
      title = `tool result: ${event.tool as string} — ${event.success ? "ok" : "error"}`;
      body = String(event.output ?? "").slice(0, 2000);
      break;
    case "llm_usage":
      title = `LLM ${event.model as string}: ${event.input_tokens as number} in / ${event.output_tokens as number} out`;
      break;
    case "approval_requested":
      title = "⏸ approval requested";
      body = (event.payload as ApprovalPayload | undefined)?.message ?? null;
      break;
    case "artifact":
      title = `artifact saved: ${event.name as string}`;
      break;
    case "run_finished":
      title = `run finished: ${event.status as string}`;
      break;
  }

  return (
    <div className={`trace-event ${event.type}`}>
      <div className="ev-head">
        <span className="ev-type">{time}</span>
        <span>{title}</span>
      </div>
      {body && <pre>{body}</pre>}
    </div>
  );
}

function ApprovalForm({
  payload,
  onSubmit,
}: {
  payload: ApprovalPayload;
  onSubmit: (decision: "approve" | "reject", note: string, edited: string | null) => void;
}) {
  const [note, setNote] = useState("");
  const [edited, setEdited] = useState(payload.last_output ?? "");
  const editable = payload.kind === "approval";

  return (
    <div className="approval-panel">
      <h3>⏸ Approval required — {payload.node_name}</h3>
      <p>{payload.message}</p>
      {payload.kind === "tool_approval" && (
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
          {payload.tool}({JSON.stringify(payload.params, null, 2)})
        </pre>
      )}
      {editable && (
        <>
          <label>Current output (edit before approving if needed)</label>
          <textarea rows={10} value={edited} onChange={(e) => setEdited(e.target.value)} />
        </>
      )}
      <label>Note (optional, recorded on rejection)</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
        <button
          className="primary"
          onClick={() =>
            onSubmit(
              "approve",
              note,
              editable && edited !== (payload.last_output ?? "") ? edited : null,
            )
          }
        >
          Approve
        </button>
        <button className="danger" onClick={() => onSubmit("reject", note, null)}>
          Reject
        </button>
      </div>
    </div>
  );
}
