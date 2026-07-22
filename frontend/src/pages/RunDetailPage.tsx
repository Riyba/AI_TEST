import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { TimeSavedEditor, formatTimeSaved } from "../components/TimeSaved";
import type { ApprovalPayload, RunDetail, RunEvent, RunStatus } from "../types";

const TERMINAL: RunStatus[] = ["succeeded", "failed", "rejected", "cancelled"];

function formatDuration(ms: number): string {
  const s = Math.floor(Math.max(0, ms) / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export default function RunDetailPage() {
  const { id } = useParams();
  const runId = Number(id);

  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [approval, setApproval] = useState<ApprovalPayload | null>(null);
  const [error, setError] = useState("");
  const [timeSavedPrompt, setTimeSavedPrompt] = useState(false);
  const [savingTime, setSavingTime] = useState(false);
  const [datadogConfigured, setDatadogConfigured] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    api.meta().then((m) => setDatadogConfigured(m.datadog_configured)).catch(() => undefined);
  }, []);
  const sourceRef = useRef<EventSource | null>(null);
  const traceRef = useRef<HTMLDivElement | null>(null);
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

  // Tick a clock once a second while the run is active so elapsed time stays live.
  useEffect(() => {
    if (!run || TERMINAL.includes(run.status)) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [run?.status]);

  // Keep the live trace pinned to the newest event while the run is active.
  useEffect(() => {
    const el = traceRef.current;
    if (el && run && !TERMINAL.includes(run.status)) el.scrollTop = el.scrollHeight;
  }, [events.length, run?.status]);

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
  const doneSteps = run.steps.filter((s) => s.finished_at).length;
  const totalSteps = run.steps.length;
  const progressPct = totalSteps ? Math.round((doneSteps / totalSteps) * 100) : 0;
  const startMs = Date.parse(run.created_at);
  const endMs = run.finished_at ? Date.parse(run.finished_at) : now;
  const elapsed = Number.isNaN(startMs) ? null : formatDuration(endMs - startMs);
  const failed = ["failed", "rejected", "cancelled"].includes(run.status);

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

      <div className="run-status-bar">
        <div className="stat">
          <span className="label">Status</span>
          <span className={`badge ${run.status}`}>{run.status}</span>
        </div>
        {elapsed && (
          <div className="stat">
            <span className="label">{active ? "Elapsed" : "Duration"}</span>
            <span className="value">{elapsed}</span>
          </div>
        )}
        <div className="stat grow">
          <span className="label">
            Steps · {doneSteps}/{totalSteps} done
          </span>
          <div className="progress-track">
            <div
              className={`progress-fill${failed ? " failed" : ""}`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      <div className="stat-tiles">
        <div className="stat-tile">
          <div className="label">Repo</div>
          <div className="value">{run.input.repo_path || "—"}</div>
        </div>
        <div className="stat-tile">
          <div className="label">Task</div>
          <div className="value">{run.input.task || "(none)"}</div>
        </div>
        <div className="stat-tile">
          <div className="label">Tokens</div>
          <div className="value">
            {run.total_input_tokens.toLocaleString()} in /{" "}
            {run.total_output_tokens.toLocaleString()} out
          </div>
        </div>
        <div className="stat-tile">
          <div className="label">Time saved</div>
          <div className="value">{formatTimeSaved(run.time_saved_minutes)}</div>
        </div>
        {datadogConfigured && !active && (
          <div className="stat-tile">
            <div className="label">Datadog</div>
            <div className="value">{run.synced_to_datadog ? "synced ✓" : "not synced"}</div>
          </div>
        )}
        {run.attachments && run.attachments.length > 0 && (
          <div className="stat-tile">
            <div className="label">Attachments</div>
            <div className="value">{run.attachments.map((a) => a.filename).join(", ")}</div>
          </div>
        )}
      </div>

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
          This run is waiting for approval, but the approval prompt was lost (likely a
          server restart). It can't be reopened from the live stream — cancel and re-run.
        </div>
      )}

      <div className="split">
        <div className="main-col">
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
                  <td className="muted num">
                    {step.input_tokens + step.output_tokens > 0
                      ? `${step.input_tokens.toLocaleString()}/${step.output_tokens.toLocaleString()}`
                      : "–"}
                  </td>
                  <td>
                    <details className="raw">
                      <summary>in / out / tool calls</summary>
                      <pre
                        style={{
                          whiteSpace: "pre-wrap", fontSize: 12, maxHeight: 260,
                          overflow: "auto", background: "var(--bg)", padding: 8, borderRadius: 4,
                        }}
                      >
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

      <h3>Live trace</h3>
      {events.length === 0 && (
        <p className="muted small">
          {active ? "Waiting for events…" : "No live events (finished run) — see steps above."}
        </p>
      )}
      <div className="trace" ref={traceRef}>
        {events.map((event) => (
          <TraceEvent key={event.seq} event={event} />
        ))}
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
