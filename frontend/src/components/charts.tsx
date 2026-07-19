/**
 * Minimal hand-rolled SVG charts for the metrics page. Dataset sizes are tiny
 * (hundreds of points at most), so charts render synchronously from props —
 * no chart library needed.
 *
 * Visual rules (see the palette vars in styles.css): thin marks (≤24px) with a
 * 4px rounded data-end and square baseline, 2px surface gaps between stacked
 * segments, hairline solid gridlines, text in text tokens (never series
 * colors), a legend for ≥2 series, hover tooltips, and a table-view twin so no
 * value is reachable only by hover.
 */

import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

const M = { top: 12, right: 12, bottom: 26, left: 48 };

interface Tip {
  x: number;
  y: number;
  title: string;
  rows: string[];
}

/** Track the chart container's pixel width so SVG text renders at true size. */
function useContainerWidth(ref: React.RefObject<HTMLDivElement>): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** Clean axis max + tick step (1/2/2.5/5 × 10^k). */
function niceScale(maxValue: number, ticks = 4): { max: number; step: number } {
  if (maxValue <= 0) return { max: 1, step: 1 };
  const rough = maxValue / ticks;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s * ticks >= maxValue) ??
    10 * pow;
  return { max: step * ticks, step };
}

export function fmtCompact(n: number): string {
  if (n < 10_000) return n.toLocaleString();
  if (n < 1_000_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** Rounded top corners, square baseline. */
function columnPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

/** Rounded right end, square left baseline. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, h / 2, w);
  return `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} L${x},${y + h} Z`;
}

function useChartBox() {
  const [tip, setTip] = useState<Tip | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const width = Math.max(320, useContainerWidth(wrapRef) || 640);
  const show = (e: React.MouseEvent, title: string, rows: string[]) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, title, rows });
  };
  return { tip, setTip, show, wrapRef, width };
}

function TipBox({ tip }: { tip: Tip }) {
  return (
    <div
      className="chart-tip"
      style={{ left: tip.x + 12, top: Math.max(0, tip.y - 10) }}
    >
      <div className="tip-title">{tip.title}</div>
      {tip.rows.map((row) => (
        <div key={row}>{row}</div>
      ))}
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  legend,
  table,
  children,
}: {
  title: string;
  subtitle?: string;
  legend?: { name: string; color: string }[];
  table: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="panel chart-card">
      <div className="chart-head">
        <div>
          <h4>{title}</h4>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
        {legend && legend.length > 1 && (
          <div className="chart-legend">
            {legend.map((s) => (
              <span key={s.name}>
                <i style={{ background: s.color }} /> {s.name}
              </span>
            ))}
          </div>
        )}
      </div>
      {children}
      <details className="raw">
        <summary>View data as table</summary>
        {table}
      </details>
    </div>
  );
}

/** Vertical columns; 1 series plain, 2 series stacked with a 2px surface gap. */
export function ColumnChart({
  title,
  subtitle,
  data,
  series,
  format = fmtCompact,
  height = 220,
}: {
  title: string;
  subtitle?: string;
  data: { label: string; values: number[] }[];
  series: { name: string; color: string }[];
  format?: (n: number) => string;
  height?: number;
}) {
  const { tip, setTip, show, wrapRef, width } = useChartBox();
  const plotW = width - M.left - M.right;
  const plotH = height - M.top - M.bottom;

  const totals = data.map((d) => d.values.reduce((a, b) => a + b, 0));
  const { max, step } = niceScale(Math.max(0, ...totals));
  const yFor = (v: number) => M.top + plotH - (v / max) * plotH;

  const band = data.length > 0 ? plotW / data.length : plotW;
  const barW = Math.min(24, Math.max(3, band * 0.6));
  // Label every column when few; thin ticks out as columns grow.
  const labelEvery = Math.max(1, Math.ceil(data.length / 8));

  const gridValues: number[] = [];
  for (let v = step; v <= max; v += step) gridValues.push(v);

  const table = (
    <table className="step-table">
      <thead>
        <tr>
          <th></th>
          {series.map((s) => (
            <th key={s.name}>{s.name}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((d) => (
          <tr key={d.label}>
            <td className="muted">{d.label}</td>
            {d.values.map((v, i) => (
              <td key={series[i].name} className="num">{format(v)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartCard title={title} subtitle={subtitle} legend={series} table={table}>
      <div className="chart-wrap" ref={wrapRef} onMouseLeave={() => setTip(null)}>
        {data.length === 0 ? (
          <p className="muted small">No data yet.</p>
        ) : (
          <svg width={width} height={height} role="img" aria-label={title}>
            {gridValues.map((v) => (
              <g key={v}>
                <line
                  className="gridline"
                  x1={M.left} x2={width - M.right} y1={yFor(v)} y2={yFor(v)}
                />
                <text className="tick" x={M.left - 6} y={yFor(v) + 3} textAnchor="end">
                  {format(v)}
                </text>
              </g>
            ))}
            <line
              className="axisline"
              x1={M.left} x2={width - M.right}
              y1={M.top + plotH} y2={M.top + plotH}
            />
            {data.map((d, i) => {
              const x = M.left + band * i + (band - barW) / 2;
              let cursor = M.top + plotH;
              const segments = d.values.map((v, si) => {
                const h = (v / max) * plotH;
                cursor -= h;
                return { v, si, y: cursor, h };
              });
              return (
                <g key={d.label}>
                  {segments.map((seg, order) => {
                    if (seg.h <= 0) return null;
                    const isTop = order === segments.length - 1 ||
                      segments.slice(order + 1).every((s) => s.h <= 0);
                    // 2px surface gap between stacked segments.
                    const gap = order > 0 ? 2 : 0;
                    const y = seg.y + gap;
                    const h = Math.max(0, seg.h - gap);
                    if (h <= 0) return null;
                    return isTop ? (
                      <path
                        key={seg.si}
                        d={columnPath(x, y, barW, h)}
                        fill={series[seg.si].color}
                      />
                    ) : (
                      <rect
                        key={seg.si}
                        x={x} y={y} width={barW} height={h}
                        fill={series[seg.si].color}
                      />
                    );
                  })}
                  <rect
                    className="hit"
                    x={M.left + band * i} y={M.top}
                    width={band} height={plotH}
                    onMouseMove={(e) =>
                      show(
                        e,
                        d.label,
                        series.length > 1
                          ? [
                              ...series.map((s, si) => `${s.name}: ${format(d.values[si])}`),
                              `total: ${format(totals[i])}`,
                            ]
                          : [`${series[0].name}: ${format(d.values[0])}`],
                      )
                    }
                    onMouseLeave={() => setTip(null)}
                  />
                  {i % labelEvery === 0 && (
                    <text
                      className="tick"
                      x={M.left + band * i + band / 2}
                      y={height - 8}
                      textAnchor="middle"
                    >
                      {d.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
        {tip && <TipBox tip={tip} />}
      </div>
    </ChartCard>
  );
}

/** Horizontal single-series bars with the value at the bar tip. */
export function HBarChart({
  title,
  subtitle,
  data,
  color,
  format = fmtCompact,
  seriesName,
}: {
  title: string;
  subtitle?: string;
  data: { label: string; value: number; detail?: string[] }[];
  color: string;
  format?: (n: number) => string;
  seriesName: string;
}) {
  const { tip, setTip, show, wrapRef, width } = useChartBox();
  const row = 30;
  const labelW = 150;
  const valueW = 56;
  const height = M.top + data.length * row + 8;
  const plotW = width - labelW - valueW - 16;
  const max = niceScale(Math.max(0, ...data.map((d) => d.value))).max;

  const table = (
    <table className="step-table">
      <thead>
        <tr>
          <th></th>
          <th>{seriesName}</th>
        </tr>
      </thead>
      <tbody>
        {data.map((d) => (
          <tr key={d.label}>
            <td className="muted">{d.label}</td>
            <td className="num">{format(d.value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartCard title={title} subtitle={subtitle} table={table}>
      <div className="chart-wrap" ref={wrapRef} onMouseLeave={() => setTip(null)}>
        {data.length === 0 ? (
          <p className="muted small">No data yet.</p>
        ) : (
          <svg width={width} height={height} role="img" aria-label={title}>
            {data.map((d, i) => {
              const y = M.top + i * row;
              const barH = Math.min(24, row - 8);
              const w = max > 0 ? (d.value / max) * plotW : 0;
              return (
                <g key={d.label}>
                  <text
                    className="cat-label"
                    x={labelW} y={y + barH / 2 + 4}
                    textAnchor="end"
                  >
                    {d.label.length > 22 ? `${d.label.slice(0, 21)}…` : d.label}
                  </text>
                  {w > 0 && (
                    <path d={barPath(labelW + 8, y, w, barH)} fill={color} />
                  )}
                  <text className="tick" x={labelW + 8 + w + 6} y={y + barH / 2 + 4}>
                    {format(d.value)}
                  </text>
                  <rect
                    className="hit"
                    x={0} y={y - 2} width={width} height={row}
                    onMouseMove={(e) =>
                      show(e, d.label, [
                        `${seriesName}: ${format(d.value)}`,
                        ...(d.detail ?? []),
                      ])
                    }
                    onMouseLeave={() => setTip(null)}
                  />
                </g>
              );
            })}
          </svg>
        )}
        {tip && <TipBox tip={tip} />}
      </div>
    </ChartCard>
  );
}

export function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="panel stat-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}
