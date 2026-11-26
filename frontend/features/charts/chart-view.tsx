"use client";
/**
 * Renders aggregated chart data from the API with Recharts.
 *
 * Dataviz rules applied here (see docs/decisions): categorical colours come from the
 * validated palette in fixed order and follow the entity (series name), never its rank;
 * one y-axis only; a legend whenever there are two or more series; hover tooltips on every
 * mark; thin marks with 4px rounded data ends; recessive grid; text never wears series colour.
 */
import { useMemo, useSyncExternalStore, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { formatCompact, formatNumber } from "@/lib/format";
import type { ChartData, ChartSpec } from "@/lib/types";

const TOKENS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6", "--chart-7", "--chart-8", "--border", "--fg-subtle", "--fg-muted", "--surface", "--fg"] as const;
const FALLBACK = "#257de0|#f47230|#00b894|#f2a600|#ee7fac|#008a17|#6a4ce2|#ec4647|#e3e6ec|#646c7e|#5b6475|#ffffff|#121722";

function subscribe(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => obs.disconnect();
}

function snapshot() {
  const cs = getComputedStyle(document.documentElement);
  return TOKENS.map((t) => cs.getPropertyValue(t).trim()).join("|");
}

/** Resolved palette + chrome colours; re-reads when the theme toggles. */
export function useChartTheme() {
  const raw = useSyncExternalStore(subscribe, snapshot, () => FALLBACK);
  return useMemo(() => {
    const v = raw.split("|");
    return { series: v.slice(0, 8), grid: v[8]!, axis: v[9]!, muted: v[10]!, surface: v[11]!, fg: v[12]! };
  }, [raw]);
}

type Row = Record<string, unknown> & { __x: unknown };
interface Shaped {
  rows: Row[];
  keys: string[];
  labels: Record<string, string>;
}

const OTHER = "Other";

function isoDate(v: unknown): Date | null {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(v)) return null;
  const d = new Date(v.length === 10 ? `${v}T00:00:00Z` : v);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Axis tick: compact for big numbers, few decimals for small ones. */
export function formatTick(v: number): string {
  const a = Math.abs(v);
  if (a >= 10_000) return formatCompact(v);
  const digits = a >= 100 ? 0 : a >= 1 ? 1 : 2;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(v);
}

export function formatX(v: unknown, grain?: string): string {
  if (v === null || v === undefined) return "(null)";
  const d = isoDate(v);
  if (d) {
    const opts: Intl.DateTimeFormatOptions =
      grain === "year"
        ? { year: "numeric", timeZone: "UTC" }
        : grain === "month" || grain === "quarter"
          ? { month: "short", year: "numeric", timeZone: "UTC" }
          : { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
    if (grain === "quarter") return `Q${Math.floor(d.getUTCMonth() / 3) + 1} ${d.getUTCFullYear()}`;
    return d.toLocaleDateString("en-US", opts);
  }
  if (typeof v === "number") return formatTick(v);
  return String(v);
}

function fmtValue(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? formatNumber(v) : formatNumber(Math.round(v * 100) / 100);
  if (v === null || v === undefined) return "—";
  return String(v);
}

export function shape(data: ChartData): Shaped {
  const { meta, rows } = data;
  if (meta.series) {
    // rows: [x, series, y] -> one object per x with a key per series.
    const byX = new Map<string, Row>();
    const totals = new Map<string, number>();
    for (const [x, s, y] of rows) {
      const key = String(x);
      const name = s === null || s === undefined ? "(null)" : String(s);
      const row = byX.get(key) ?? { __x: x };
      row[name] = y;
      byX.set(key, row);
      totals.set(name, (totals.get(name) ?? 0) + (typeof y === "number" ? y : 0));
    }
    const keys = [...totals.keys()].sort((a, b) =>
      a === OTHER ? 1 : b === OTHER ? -1 : (totals.get(b) ?? 0) - (totals.get(a) ?? 0) || a.localeCompare(b),
    );
    return { rows: [...byX.values()], keys, labels: Object.fromEntries(keys.map((k) => [k, k])) };
  }
  const keys = meta.measures;
  return {
    rows: rows.map((r) => {
      const o: Row = { __x: r[0] };
      keys.forEach((k, i) => (o[k] = r[i + 1]));
      return o;
    }),
    keys,
    labels: Object.fromEntries(keys.map((k) => [k, k])),
  };
}

function ChartTooltip({
  active,
  payload,
  label,
  grain,
  title,
}: {
  active?: boolean;
  payload?: { name?: string; value?: unknown; color?: string; dataKey?: unknown }[];
  label?: unknown;
  grain?: string;
  title?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-36 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-medium text-fg">{title ?? formatX(label, grain)}</div>
      <ul className="space-y-0.5">
        {payload.map((p, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="size-2 shrink-0 rounded-full" style={{ background: p.color }} aria-hidden />
            <span className="text-muted">{p.name}</span>
            <span className="ml-auto pl-3 font-medium text-fg tabular-nums">{fmtValue(p.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Legend({ items }: { items: { name: string; color: string }[] }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 px-1 pb-2 text-xs text-muted" aria-label="Legend">
      {items.map((it) => (
        <li key={it.name} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: it.color }} aria-hidden />
          {it.name}
        </li>
      ))}
    </ul>
  );
}

export function StatCards({ data }: { data: ChartData }) {
  const row = data.rows[0] ?? [];
  return (
    <div className="grid h-full auto-rows-fr grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3 p-1">
      {data.meta.measures.map((m, i) => (
        <div key={m} className="flex flex-col justify-center rounded-lg border border-border bg-surface-2/40 px-4 py-3">
          <div className="truncate text-xs text-muted">{m}</div>
          <div className="mt-1 truncate text-2xl font-semibold tracking-tight tabular-nums" data-testid="stat-value">
            {fmtValue(row[i])}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChartView({ data, spec, height = "100%" }: { data: ChartData; spec: ChartSpec; height?: number | `${number}%` }) {
  const theme = useChartTheme();
  const shaped = useMemo(() => shape(data), [data]);
  const o = spec.options ?? {};
  const grain = spec.grain ?? "none";

  if (data.meta.type === "stat") return <StatCards data={data} />;
  if (data.rows.length === 0) {
    return <div className="flex h-full items-center justify-center text-sm text-muted">No rows match this chart.</div>;
  }

  const color = (i: number) => theme.series[i % 8]!;
  // "Other" is a fold, not an entity: it gets a neutral grey rather than a palette hue.
  const colorFor = (key: string, i: number) => (key === OTHER ? theme.axis : color(i));
  const axisProps = {
    stroke: theme.grid,
    tick: { fill: theme.axis, fontSize: 11 },
    tickLine: false,
    axisLine: { stroke: theme.grid },
  } as const;
  const grid = <CartesianGrid stroke={theme.grid} strokeDasharray="0" vertical={false} />;
  const yAxis = (
    <YAxis
      {...axisProps}
      axisLine={false}
      width={56}
      tickFormatter={(v: number) => formatCompact(v)}
      label={o.y_label ? { value: o.y_label, angle: -90, position: "insideLeft", fill: theme.axis, fontSize: 11, dx: -2 } : undefined}
    />
  );
  const xLabel = o.x_label ? { value: o.x_label, position: "insideBottom" as const, fill: theme.axis, fontSize: 11, dy: 10 } : undefined;
  const legendItems = shaped.keys.map((k, i) => ({ name: shaped.labels[k] ?? k, color: colorFor(k, i) }));
  const wrap = (chart: ReactNode, legend = legendItems) => (
    <div className="flex h-full min-h-0 flex-col" style={{ height }}>
      <Legend items={legend} />
      <div className="min-h-0 flex-1" role="img" aria-label={`${spec.type} chart${o.title ? `: ${o.title}` : ""}`}>
        <ResponsiveContainer width="100%" height="100%" minHeight={120}>
          {chart as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
  const tooltip = (title?: (p: unknown) => string) => (
    <Tooltip
      cursor={{ fill: theme.grid, fillOpacity: 0.5, stroke: theme.axis, strokeWidth: 1 }}
      content={(p) => <ChartTooltip {...(p as object)} grain={grain} title={title?.(p)} />}
      isAnimationActive={false}
    />
  );
  const margin = { top: 8, right: 12, bottom: o.x_label ? 18 : 4, left: 0 };

  if (data.meta.type === "histogram") {
    const rows = data.rows.map(([a, b, c]) => ({ __x: a, end: b, count: c }));
    return wrap(
      <BarChart data={rows} margin={margin} barCategoryGap={1}>
        {grid}
        <XAxis {...axisProps} dataKey="__x" tickFormatter={(v) => formatTick(Number(v))} label={xLabel} minTickGap={16} />
        {yAxis}
        {tooltip((p) => {
          const pl = (p as { payload?: { payload?: { __x: number; end: number } }[] }).payload?.[0]?.payload;
          return pl ? `${formatTick(pl.__x)} – ${formatTick(pl.end)}` : "";
        })}
        <Bar dataKey="count" name="Rows" fill={color(0)} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>,
      [],
    );
  }

  if (data.meta.type === "scatter") {
    const groups = new Map<string, { x: unknown; y: unknown }[]>();
    for (const [x, y, s] of data.rows) {
      const k = data.meta.series ? String(s ?? "(null)") : spec.y[0]?.field ?? "y";
      (groups.get(k) ?? groups.set(k, []).get(k)!).push({ x: typeof x === "string" ? Date.parse(x) : x, y });
    }
    const names = [...groups.keys()].sort((a, b) => (a === OTHER ? 1 : b === OTHER ? -1 : (groups.get(b)!.length - groups.get(a)!.length) || a.localeCompare(b)));
    const temporalX = typeof data.rows[0]?.[0] === "string";
    return wrap(
      <ScatterChart margin={margin}>
        <CartesianGrid stroke={theme.grid} />
        <XAxis
          {...axisProps}
          type="number"
          dataKey="x"
          name={spec.x ?? "x"}
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => (temporalX ? formatX(new Date(v).toISOString(), "day") : formatTick(v))}
          label={xLabel}
        />
        <YAxis {...axisProps} axisLine={false} type="number" dataKey="y" name={spec.y[0]?.field ?? "y"} width={56} tickFormatter={(v: number) => formatCompact(v)} domain={["auto", "auto"]} />
        <ZAxis range={[64, 64]} />
        <Tooltip
          isAnimationActive={false}
          cursor={{ stroke: theme.axis, strokeDasharray: "3 3" }}
          content={(p) => {
            const pl = (p as unknown as { payload?: { payload?: { x: number; y: unknown } }[] }).payload?.[0]?.payload;
            if (!p.active || !pl) return null;
            return (
              <ChartTooltip
                active
                title={`${spec.x}: ${temporalX ? formatX(new Date(pl.x).toISOString()) : fmtValue(pl.x)}`}
                payload={[{ name: spec.y[0]?.field ?? "y", value: pl.y, color: theme.axis }]}
              />
            );
          }}
        />
        {[...names.entries()]
          .sort(([, a], [, b]) => (a === OTHER ? -1 : b === OTHER ? 1 : 0))
          .map(([i, n]) => (
            <Scatter key={n} name={n} data={groups.get(n)} fill={colorFor(n, i)} stroke={theme.surface} strokeWidth={1} fillOpacity={0.8} isAnimationActive={false} />
          ))}
      </ScatterChart>,
      names.map((n, i) => ({ name: n, color: colorFor(n, i) })),
    );
  }

  const xAxis = (
    <XAxis {...axisProps} dataKey="__x" tickFormatter={(v) => formatX(v, grain)} label={xLabel} minTickGap={12} interval="preserveStartEnd" />
  );
  const stacked = !!o.stacked && shaped.keys.length > 1;

  if (data.meta.type === "line") {
    return wrap(
      <LineChart data={shaped.rows} margin={margin}>
        {grid}
        {xAxis}
        {yAxis}
        {tooltip()}
        {shaped.keys.map((k, i) => (
          <Line
            key={k}
            type="linear"
            dataKey={k}
            name={shaped.labels[k]}
            stroke={colorFor(k, i)}
            strokeWidth={2}
            dot={shaped.rows.length <= 2 ? { r: 4, fill: colorFor(k, i), stroke: theme.surface, strokeWidth: 2 } : false}
            activeDot={{ r: 4, stroke: theme.surface, strokeWidth: 2 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>,
    );
  }

  if (data.meta.type === "area") {
    return wrap(
      <AreaChart data={shaped.rows} margin={margin}>
        {grid}
        {xAxis}
        {yAxis}
        {tooltip()}
        {shaped.keys.map((k, i) => (
          <Area
            key={k}
            type="linear"
            dataKey={k}
            name={shaped.labels[k]}
            stroke={colorFor(k, i)}
            strokeWidth={2}
            fill={colorFor(k, i)}
            fillOpacity={stacked ? 0.55 : 0.14}
            stackId={stacked ? "s" : undefined}
            activeDot={{ r: 4, stroke: theme.surface, strokeWidth: 2 }}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>,
    );
  }

  // bar
  const horizontal = o.orientation === "horizontal";
  const n = shaped.keys.length;
  return wrap(
    <BarChart data={shaped.rows} margin={margin} layout={horizontal ? "vertical" : "horizontal"} barGap={2} barCategoryGap="22%">
      <CartesianGrid stroke={theme.grid} vertical={horizontal} horizontal={!horizontal} />
      {horizontal ? (
        <>
          <XAxis {...axisProps} type="number" tickFormatter={(v: number) => formatCompact(v)} />
          <YAxis {...axisProps} type="category" dataKey="__x" width={96} tickFormatter={(v) => formatX(v, grain)} interval={0} />
        </>
      ) : (
        <>
          {xAxis}
          {yAxis}
        </>
      )}
      {tooltip()}
      {shaped.keys.map((k, i) => {
        const top = !stacked || i === n - 1;
        const r: [number, number, number, number] = top ? (horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) : [0, 0, 0, 0];
        return (
          <Bar
            key={k}
            dataKey={k}
            name={shaped.labels[k]}
            fill={colorFor(k, i)}
            stackId={stacked ? "s" : undefined}
            radius={r}
            maxBarSize={56}
            stroke={stacked ? theme.surface : undefined}
            strokeWidth={stacked ? 1 : 0}
            isAnimationActive={false}
            label={
              o.show_values
                ? { position: horizontal ? "right" : "top", fill: theme.muted, fontSize: 11, formatter: (v: unknown) => formatCompact(Number(v)) }
                : undefined
            }
          />
        );
      })}
    </BarChart>,
  );
}

/** Accessible table view of the same data (identity never relies on colour alone). */
export function ChartTable({ data }: { data: ChartData }) {
  return (
    <div tabIndex={0} role="region" aria-label="Chart data" className="scroll-thin h-full overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-border text-left text-muted">
            {data.columns.map((c) => (
              <th key={c.name} className="px-2 py-1.5 font-medium">
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.slice(0, 500).map((r, i) => (
            <tr key={i} className="border-b border-border/60">
              {r.map((v, j) => (
                <td key={j} className="px-2 py-1 tabular-nums">
                  {typeof v === "number" ? fmtValue(v) : String(v ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.rows.length > 500 ? <p className="p-2 text-xs text-subtle">Showing 500 of {formatNumber(data.rows.length)} rows.</p> : null}
    </div>
  );
}
