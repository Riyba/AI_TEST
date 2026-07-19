import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ColumnChart, HBarChart, StatTile, fmtCompact } from "../components/charts";
import { formatTimeSaved } from "../components/TimeSaved";
import type { Metrics } from "../types";

// Series colors (validated categorical slots 1 & 2, light+dark — styles.css).
const S1 = "var(--viz-s1)";
const S2 = "var(--viz-s2)";

const shortDate = (iso: string) => iso.slice(5); // "2026-07-19" → "07-19"

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    api
      .metrics()
      .then((m) => {
        setMetrics(m);
        setError("");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!metrics) return <p className="muted">{error || "Loading…"}</p>;

  const { totals } = metrics;
  const finished =
    (totals.runs_by_status.succeeded ?? 0) +
    (totals.runs_by_status.failed ?? 0) +
    (totals.runs_by_status.rejected ?? 0) +
    (totals.runs_by_status.cancelled ?? 0);
  const successRate =
    finished > 0
      ? `${Math.round(((totals.runs_by_status.succeeded ?? 0) / finished) * 100)}%`
      : "—";
  const captureNote = `captured on ${totals.runs_with_time_saved} of ${totals.runs} runs`;

  return (
    <div className={loading ? "refetching" : undefined}>
      <div className="toolbar">
        <h2>Metrics</h2>
        <div className="spacer" />
        <button onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <div className="error-box">{error}</div>}

      <div className="kpi-row">
        <StatTile
          label="Total runs"
          value={String(totals.runs)}
          sub={`${totals.runs_by_status.succeeded ?? 0} succeeded · ${
            totals.runs_by_status.failed ?? 0
          } failed`}
        />
        <StatTile
          label="Success rate"
          value={successRate}
          sub={`${finished} finished runs`}
        />
        <StatTile
          label="Tokens used"
          value={fmtCompact(totals.input_tokens + totals.output_tokens)}
          sub={`${fmtCompact(totals.input_tokens)} in · ${fmtCompact(
            totals.output_tokens,
          )} out`}
        />
        <StatTile
          label="Time saved"
          value={
            totals.runs_with_time_saved > 0
              ? formatTimeSaved(totals.time_saved_minutes)
              : "—"
          }
          sub={captureNote}
        />
      </div>

      {totals.runs === 0 ? (
        <p className="muted">No runs yet — launch a workflow to populate metrics.</p>
      ) : (
        <div className="chart-grid">
          <ColumnChart
            title="Runs per day"
            data={metrics.by_day.map((d) => ({
              label: shortDate(d.date),
              values: [d.runs],
            }))}
            series={[{ name: "runs", color: S1 }]}
            format={(n) => String(n)}
          />
          <ColumnChart
            title="Token consumption per day"
            data={metrics.by_day.map((d) => ({
              label: shortDate(d.date),
              values: [d.input_tokens, d.output_tokens],
            }))}
            series={[
              { name: "input", color: S1 },
              { name: "output", color: S2 },
            ]}
          />
          <HBarChart
            title="Token consumption by agent"
            subtitle="Input + output tokens across all agent steps"
            seriesName="tokens"
            color={S1}
            data={metrics.by_agent.map((a) => ({
              label: a.agent,
              value: a.input_tokens + a.output_tokens,
              detail: [
                `${fmtCompact(a.input_tokens)} in · ${fmtCompact(a.output_tokens)} out`,
                `${a.steps} steps in ${a.runs} runs`,
              ],
            }))}
          />
          <HBarChart
            title="Agent activity"
            subtitle="Executed agent steps"
            seriesName="steps"
            color={S1}
            format={(n) => String(n)}
            data={metrics.by_agent
              .slice()
              .sort((a, b) => b.steps - a.steps)
              .map((a) => ({
                label: a.agent,
                value: a.steps,
                detail: [`${a.runs} runs`],
              }))}
          />
          <HBarChart
            title="Time saved by workflow"
            subtitle={`Only runs with a captured estimate are included (${captureNote}).`}
            seriesName="time saved"
            color={S1}
            format={(n) => formatTimeSaved(n)}
            data={metrics.by_workflow
              .filter((w) => w.runs_with_time_saved > 0)
              .sort((a, b) => b.time_saved_minutes - a.time_saved_minutes)
              .map((w) => ({
                label: w.workflow_name,
                value: w.time_saved_minutes,
                detail: [`captured on ${w.runs_with_time_saved} of ${w.runs} runs`],
              }))}
          />
          <ColumnChart
            title="Time saved per day"
            subtitle="Only runs with a captured estimate are included."
            data={metrics.by_day
              .filter((d) => d.runs_with_time_saved > 0)
              .map((d) => ({
                label: shortDate(d.date),
                values: [d.time_saved_minutes],
              }))}
            series={[{ name: "time saved", color: S1 }]}
            format={(n) => formatTimeSaved(n)}
          />
        </div>
      )}

      {totals.runs > 0 && (
        <>
          <h3>Workflow summary</h3>
          <table className="step-table">
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Runs</th>
                <th>Succeeded</th>
                <th>Tokens (in/out)</th>
                <th>Time saved</th>
                <th>Estimates captured</th>
              </tr>
            </thead>
            <tbody>
              {metrics.by_workflow.map((w) => (
                <tr key={w.workflow_name}>
                  <td>{w.workflow_name}</td>
                  <td className="num">{w.runs}</td>
                  <td className="num">{w.succeeded}</td>
                  <td className="num muted">
                    {fmtCompact(w.input_tokens)} / {fmtCompact(w.output_tokens)}
                  </td>
                  <td className="num">
                    {w.runs_with_time_saved > 0
                      ? formatTimeSaved(w.time_saved_minutes)
                      : "—"}
                  </td>
                  <td className="num muted">
                    {w.runs_with_time_saved} / {w.runs}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
