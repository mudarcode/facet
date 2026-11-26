"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { AreaChart as AreaIcon, BarChart3, ChartLine, ChartScatter, Code2, Hash, Plus, Save, Table2, X, ChartColumnBig } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorBanner, Spinner } from "@/components/ui/feedback";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { formatMs, formatNumber, typeKind } from "@/lib/format";
import type { Agg, Chart, ChartSource, ChartSpec, ChartType, ColumnSchema, Grain, Measure } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ExportMenu } from "@/features/exports/export-menu";
import { ChartTable, ChartView } from "./chart-view";
import { completeConditions, ConditionsEditor } from "./conditions-editor";

const TYPES: { type: ChartType; label: string; icon: typeof BarChart3 }[] = [
  { type: "bar", label: "Bar", icon: BarChart3 },
  { type: "line", label: "Line", icon: ChartLine },
  { type: "area", label: "Area", icon: AreaIcon },
  { type: "scatter", label: "Scatter", icon: ChartScatter },
  { type: "histogram", label: "Histogram", icon: ChartColumnBig },
  { type: "stat", label: "Stat", icon: Hash },
];

const AGGS: { agg: Agg; label: string; numericOnly?: boolean }[] = [
  { agg: "count", label: "Count rows" },
  { agg: "count_distinct", label: "Count distinct" },
  { agg: "sum", label: "Sum", numericOnly: true },
  { agg: "avg", label: "Average", numericOnly: true },
  { agg: "median", label: "Median", numericOnly: true },
  { agg: "min", label: "Min" },
  { agg: "max", label: "Max" },
];

const GRAINS: Grain[] = ["none", "day", "week", "month", "quarter", "year"];

type Kind = ReturnType<typeof typeKind>;
const X_KINDS: Record<ChartType, Kind[] | null> = {
  bar: ["text", "temporal", "boolean", "number", "other"],
  line: ["temporal", "number"],
  area: ["temporal", "number"],
  scatter: ["number", "temporal"],
  histogram: ["number"],
  stat: null,
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function sourceKey(s: ChartSource): string {
  return s.dataset_id ? `d:${s.dataset_id}` : s.saved_query_id ? `q:${s.saved_query_id}` : "";
}

function parseSource(k: string): ChartSource {
  if (k.startsWith("d:")) return { dataset_id: k.slice(2) };
  if (k.startsWith("q:")) return { saved_query_id: k.slice(2) };
  return {};
}

/** Adapt a spec to a new chart type, keeping whatever still makes sense. */
function retype(spec: ChartSpec, type: ChartType, cols: ColumnSchema[]): ChartSpec {
  const kindOf = (n?: string | null) => typeKind(cols.find((c) => c.name === n)?.type ?? "");
  // Prefer kinds in the listed order and skip identifier-looking columns when there is a choice.
  const idLike = (n: string) => /(^id$|_id$|^id_)/i.test(n);
  const firstOf = (kinds: Kind[], not?: string | null) => {
    for (const k of kinds) {
      const of = cols.filter((c) => typeKind(c.type) === k && c.name !== not);
      const pick = of.find((c) => !idLike(c.name)) ?? of[0];
      if (pick) return pick.name;
    }
    return null;
  };
  const allowed = X_KINDS[type];
  let x = spec.x ?? null;
  if (allowed && (!x || !allowed.includes(kindOf(x)))) x = firstOf(allowed);
  if (!allowed) x = null;
  const numeric = firstOf(["number"], x);
  let y = spec.y;
  if (type === "scatter") {
    const f = y.find((m) => m.field && kindOf(m.field) === "number")?.field ?? numeric;
    y = f ? [{ field: f, agg: "min" }] : [];
  } else if (type === "histogram") {
    y = [];
  } else if (!y.length || spec.type === "scatter") {
    y = [{ field: null, agg: "count" }];
  }
  const grain = x && kindOf(x) === "temporal" && type !== "scatter" ? (spec.grain ?? "none") : "none";
  const series = type === "histogram" || type === "stat" ? null : (spec.series ?? null);
  return { ...spec, type, x, y, grain, series };
}

function specReady(s: ChartSpec): string | null {
  if (s.type === "stat") return s.y.length ? null : "Add a measure to show a number.";
  if (!s.x) return s.type === "histogram" ? "Choose a numeric field to bin." : "Choose a field for the x-axis.";
  if (s.type === "scatter" && !s.y[0]?.field) return "Choose a numeric field for the y-axis.";
  if (["bar", "line", "area"].includes(s.type) && !s.y.length) return "Add at least one measure.";
  return null;
}

const DEFAULT_SPEC: ChartSpec = { type: "bar", x: null, y: [{ field: null, agg: "count" }], grain: "none", filters: [], options: {} };

export function ChartBuilder({ chart, initialSource }: { chart?: Chart; initialSource?: ChartSource }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState(chart?.name ?? "");
  const [source, setSource] = useState<ChartSource>(
    chart ? { dataset_id: chart.dataset_id, saved_query_id: chart.saved_query_id } : (initialSource ?? {}),
  );
  const [spec, setSpec] = useState<ChartSpec>(chart?.spec ?? DEFAULT_SPEC);
  const [saving, setSaving] = useState(false);
  const [initFor, setInitFor] = useState<string | null>(chart ? sourceKey(source) : null);

  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => api.listDatasets() });
  const saved = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.savedQueries() });
  const srcKey = sourceKey(source);
  const cols = useQuery({
    queryKey: ["source-columns", srcKey],
    queryFn: () => api.sourceColumns(source),
    enabled: !!srcKey,
    staleTime: 60_000,
  });
  const columns = useMemo(() => cols.data?.columns ?? [], [cols.data]);

  // When a new source's columns arrive, seed sensible defaults (derived-state pattern, no effect).
  if (cols.data && initFor !== srcKey) {
    setInitFor(srcKey);
    setSpec((s) => retype({ ...s, x: null, series: null, filters: [], y: [] }, s.type, cols.data.columns));
  }

  const kindOf = (n?: string | null) => typeKind(columns.find((c) => c.name === n)?.type ?? "");
  const xKinds = X_KINDS[spec.type];
  const xCols = xKinds ? columns.filter((c) => xKinds.includes(typeKind(c.type))) : [];
  const numericCols = columns.filter((c) => typeKind(c.type) === "number");
  const seriesCols = columns.filter((c) => ["text", "boolean", "temporal", "number"].includes(typeKind(c.type)));
  const update = (patch: Partial<ChartSpec>) => setSpec((s) => ({ ...s, ...patch }));
  const opts = spec.options ?? {};
  const setOpt = (patch: Partial<NonNullable<ChartSpec["options"]>>) => update({ options: { ...opts, ...patch } });
  const setMeasure = (i: number, patch: Partial<Measure>) => update({ y: spec.y.map((m, j) => (j === i ? { ...m, ...patch } : m)) });

  const sendSpec = useMemo<ChartSpec>(() => ({ ...spec, filters: completeConditions(spec.filters ?? []) }), [spec]);
  const debounced = useDebounced(sendSpec, 250);
  const notReady = specReady(debounced);
  const preview = useQuery({
    queryKey: ["chart-preview", srcKey, debounced],
    queryFn: () => api.chartPreview(source, debounced),
    enabled: !!srcKey && !!cols.data && !notReady,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const err = preview.error as ApiError | null;

  const save = async () => {
    setSaving(true);
    try {
      const finalName = name.trim() || opts.title || "Untitled chart";
      if (chart) {
        await api.updateChart(chart.id, { name: finalName, spec: sendSpec });
        toast.success("Chart saved");
      } else {
        const c = await api.createChart({ ...source, name: finalName, spec: sendSpec });
        toast.success(`Saved “${c.name}”`);
        router.replace(`/charts/${c.id}`);
      }
      qc.invalidateQueries({ queryKey: ["charts"] });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not save chart");
    } finally {
      setSaving(false);
    }
  };

  const readyDatasets = datasets.data?.items.filter((d) => d.status === "ready") ?? [];

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link href="/charts" className="hover:text-fg">
            Charts
          </Link>
        }
        title={chart ? chart.name : "New chart"}
        actions={
          <>
            {chart ? <ExportMenu source={{ kind: "chart", chart_id: chart.id }} /> : null}
            <Button variant="primary" onClick={save} loading={saving} disabled={!srcKey || !!specReady(sendSpec)} data-testid="save-chart">
              <Save /> Save chart
            </Button>
          </>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside className="scroll-thin w-full shrink-0 space-y-5 overflow-y-auto border-b border-border bg-surface p-4 lg:w-80 lg:border-r lg:border-b-0">
          <section className="space-y-1.5">
            <Label htmlFor="chart-name">Name</Label>
            <Input id="chart-name" value={name} placeholder="Untitled chart" onChange={(e) => setName(e.target.value)} data-testid="chart-name" />
          </section>

          <section className="space-y-1.5">
            <Label htmlFor="chart-source">Data source</Label>
            <NativeSelect
              id="chart-source"
              value={srcKey}
              disabled={!!chart}
              onChange={(e) => setSource(parseSource(e.target.value))}
              data-testid="chart-source"
            >
              <option value="">Choose a dataset or saved query…</option>
              {readyDatasets.length ? (
                <optgroup label="Datasets">
                  {readyDatasets.map((d) => (
                    <option key={d.id} value={`d:${d.id}`}>
                      {d.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {saved.data?.items.length ? (
                <optgroup label="Saved queries">
                  {saved.data.items.map((q) => (
                    <option key={q.id} value={`q:${q.id}`}>
                      {q.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </NativeSelect>
            {chart ? <p className="text-[11px] text-subtle">A saved chart keeps its source. Create a new chart to use different data.</p> : null}
          </section>

          {cols.error ? <ErrorBanner message={(cols.error as Error).message} /> : null}

          {cols.data ? (
            <>
              <section className="space-y-1.5">
                <Label>Chart type</Label>
                <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Chart type">
                  {TYPES.map(({ type, label, icon: Icon }) => (
                    <button
                      key={type}
                      role="radio"
                      aria-checked={spec.type === type}
                      onClick={() => setSpec((s) => retype(s, type, columns))}
                      data-testid={`chart-type-${type}`}
                      className={cn(
                        "flex flex-col items-center gap-1 rounded-md border px-2 py-2 text-[11px] font-medium transition-colors",
                        spec.type === type ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:bg-surface-2 hover:text-fg",
                      )}
                    >
                      <Icon className="size-4" />
                      {label}
                    </button>
                  ))}
                </div>
              </section>

              {xKinds ? (
                <section className="space-y-1.5">
                  <Label htmlFor="chart-x">{spec.type === "histogram" ? "Value" : "X-axis"}</Label>
                  <NativeSelect
                    id="chart-x"
                    value={spec.x ?? ""}
                    onChange={(e) => {
                      const x = e.target.value || null;
                      update({ x, grain: kindOf(x) === "temporal" && spec.type !== "scatter" ? (spec.grain ?? "none") : "none" });
                    }}
                    data-testid="chart-x"
                  >
                    <option value="">Choose a field…</option>
                    {xCols.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name}
                      </option>
                    ))}
                  </NativeSelect>
                  {!xCols.length ? <p className="text-[11px] text-warning">This source has no {xKinds.join(" or ")} fields.</p> : null}
                  {kindOf(spec.x) === "temporal" && spec.type !== "scatter" ? (
                    <div className="flex items-center gap-2 pt-1">
                      <Label htmlFor="chart-grain" className="shrink-0">
                        Group by
                      </Label>
                      <NativeSelect id="chart-grain" className="h-7 text-xs" value={spec.grain ?? "none"} onChange={(e) => update({ grain: e.target.value as Grain })} data-testid="chart-grain">
                        {GRAINS.map((g) => (
                          <option key={g} value={g}>
                            {g === "none" ? "exact value" : g}
                          </option>
                        ))}
                      </NativeSelect>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {spec.type === "scatter" ? (
                <section className="space-y-1.5">
                  <Label htmlFor="chart-y">Y-axis</Label>
                  <NativeSelect id="chart-y" value={spec.y[0]?.field ?? ""} onChange={(e) => update({ y: e.target.value ? [{ field: e.target.value, agg: "min" }] : [] })}>
                    <option value="">Choose a numeric field…</option>
                    {numericCols.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name}
                      </option>
                    ))}
                  </NativeSelect>
                  <p className="text-[11px] text-subtle">Up to 5,000 points, sampled reproducibly when there are more.</p>
                </section>
              ) : spec.type !== "histogram" ? (
                <section className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>{spec.type === "stat" ? "Numbers" : "Measures"}</Label>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={spec.y.length >= 4 || (!!spec.series && spec.type !== "stat")}
                      onClick={() => update({ y: [...spec.y, { field: numericCols[0]?.name ?? null, agg: numericCols[0] ? "sum" : "count" }] })}
                      data-testid="add-measure"
                    >
                      <Plus /> Add
                    </Button>
                  </div>
                  {spec.y.map((m, i) => {
                    const numeric = kindOf(m.field) === "number";
                    return (
                      <div key={i} className="space-y-1.5 rounded-md border border-border bg-surface-2/40 p-2" data-testid="measure-row">
                        <div className="flex items-center gap-1.5">
                          <NativeSelect
                            aria-label="Aggregation"
                            className="h-7 text-xs"
                            value={m.agg}
                            onChange={(e) => {
                              const agg = e.target.value as Agg;
                              const needsField = agg !== "count";
                              const field = needsField ? (m.field ?? (AGGS.find((a) => a.agg === agg)?.numericOnly ? numericCols[0]?.name : columns[0]?.name) ?? null) : null;
                              setMeasure(i, { agg, field });
                            }}
                          >
                            {AGGS.map((a) => (
                              <option key={a.agg} value={a.agg} disabled={a.numericOnly && !!m.field && !numeric}>
                                {a.label}
                              </option>
                            ))}
                          </NativeSelect>
                          <Button variant="ghost" size="icon-sm" aria-label="Remove measure" onClick={() => update({ y: spec.y.filter((_, j) => j !== i) })}>
                            <X />
                          </Button>
                        </div>
                        {m.agg !== "count" ? (
                          <NativeSelect aria-label="Measure field" className="h-7 text-xs" value={m.field ?? ""} onChange={(e) => setMeasure(i, { field: e.target.value })}>
                            {(AGGS.find((a) => a.agg === m.agg)?.numericOnly ? numericCols : columns).map((c) => (
                              <option key={c.name} value={c.name}>
                                {c.name}
                              </option>
                            ))}
                          </NativeSelect>
                        ) : null}
                        <Input aria-label="Measure label" className="h-7 text-xs" placeholder="Label (optional)" value={m.label ?? ""} onChange={(e) => setMeasure(i, { label: e.target.value || null })} />
                      </div>
                    );
                  })}
                </section>
              ) : null}

              {["bar", "line", "area", "scatter"].includes(spec.type) ? (
                <section className="space-y-1.5">
                  <Label htmlFor="chart-series">Split by (series)</Label>
                  <NativeSelect
                    id="chart-series"
                    value={spec.series ?? ""}
                    disabled={spec.y.length > 1 && spec.type !== "scatter"}
                    onChange={(e) => update({ series: e.target.value || null })}
                    data-testid="chart-series"
                  >
                    <option value="">None</option>
                    {seriesCols
                      .filter((c) => c.name !== spec.x)
                      .map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                  </NativeSelect>
                  <p className="text-[11px] text-subtle">
                    {spec.y.length > 1 && spec.type !== "scatter"
                      ? "Use one measure to split into series."
                      : spec.type === "scatter"
                        ? "The 3 largest groups get their own colour; the rest are grouped as Other."
                        : "The 7 largest groups get their own colour; the rest are grouped as Other."}
                  </p>
                </section>
              ) : null}

              <section className="space-y-2">
                <Label>Filters</Label>
                <ConditionsEditor columns={columns} value={spec.filters ?? []} onChange={(filters) => update({ filters })} />
              </section>

              {spec.type !== "stat" ? (
                <section className="space-y-2">
                  <Label>Display</Label>
                  <div className="grid grid-cols-2 gap-1.5">
                    <Input aria-label="X-axis title" className="h-7 text-xs" placeholder="X-axis title" value={opts.x_label ?? ""} onChange={(e) => setOpt({ x_label: e.target.value || null })} />
                    <Input aria-label="Y-axis title" className="h-7 text-xs" placeholder="Y-axis title" value={opts.y_label ?? ""} onChange={(e) => setOpt({ y_label: e.target.value || null })} />
                  </div>
                  {spec.type === "bar" ? (
                    <div className="grid grid-cols-2 gap-1.5">
                      <NativeSelect aria-label="Sort" className="h-7 text-xs" value={opts.sort ?? "x"} onChange={(e) => setOpt({ sort: e.target.value as "x" })}>
                        <option value="x">Sort by label</option>
                        <option value="y_desc">Largest first</option>
                        <option value="y_asc">Smallest first</option>
                      </NativeSelect>
                      <NativeSelect aria-label="Orientation" className="h-7 text-xs" value={opts.orientation ?? "vertical"} onChange={(e) => setOpt({ orientation: e.target.value as "vertical" })}>
                        <option value="vertical">Vertical</option>
                        <option value="horizontal">Horizontal</option>
                      </NativeSelect>
                      <label className="col-span-2 flex items-center justify-between gap-2 text-xs text-muted">
                        Max bars
                        <Input type="number" min={1} max={5000} className="h-7 w-24 text-xs" value={opts.limit ?? 50} onChange={(e) => setOpt({ limit: Math.max(1, Math.min(5000, Number(e.target.value) || 1)) })} />
                      </label>
                    </div>
                  ) : null}
                  {spec.type === "histogram" ? (
                    <label className="flex items-center justify-between gap-2 text-xs text-muted">
                      Bins
                      <Input type="number" min={2} max={100} className="h-7 w-24 text-xs" value={opts.bins ?? 20} onChange={(e) => setOpt({ bins: Math.max(2, Math.min(100, Number(e.target.value) || 2)) })} data-testid="chart-bins" />
                    </label>
                  ) : null}
                  {(spec.type === "bar" || spec.type === "area") && (spec.series || spec.y.length > 1) ? (
                    <label className="flex items-center gap-2 text-xs text-muted">
                      <input type="checkbox" className="accent-[var(--accent)]" checked={!!opts.stacked} onChange={(e) => setOpt({ stacked: e.target.checked })} /> Stack series
                    </label>
                  ) : null}
                  {spec.type === "bar" ? (
                    <label className="flex items-center gap-2 text-xs text-muted">
                      <input type="checkbox" className="accent-[var(--accent)]" checked={!!opts.show_values} onChange={(e) => setOpt({ show_values: e.target.checked })} /> Show values on bars
                    </label>
                  ) : null}
                </section>
              ) : null}
            </>
          ) : srcKey && cols.isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted">
              <Spinner /> Reading fields…
            </div>
          ) : null}
        </aside>

        <section aria-label="Chart preview" className="flex min-h-[420px] min-w-0 flex-1 flex-col p-4">
          {!srcKey ? (
            <Card className="flex flex-1 items-center justify-center">
              <EmptyState
                icon={<BarChart3 />}
                title="Pick a data source"
                description="Charts aggregate inside DuckDB, so only the summarised points reach your browser."
              />
            </Card>
          ) : (
            <Tabs defaultValue="chart" className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-center justify-between gap-2">
                <TabsList className="border-b-0">
                  <TabsTrigger value="chart">
                    <BarChart3 /> Chart
                  </TabsTrigger>
                  <TabsTrigger value="table">
                    <Table2 /> Data
                  </TabsTrigger>
                  <TabsTrigger value="sql">
                    <Code2 /> SQL
                  </TabsTrigger>
                </TabsList>
                <div className="flex items-center gap-2 text-xs text-subtle" aria-live="polite">
                  {preview.isFetching ? <Spinner className="size-3" /> : null}
                  {preview.data ? (
                    <span data-testid="chart-stats">
                      {formatNumber(preview.data.rows.length)} points · {formatMs(preview.data.engine_ms)} in DuckDB
                      {preview.data.meta.truncated ? " · truncated" : ""}
                    </span>
                  ) : null}
                </div>
              </div>
              <Card className="mt-2 flex min-h-0 flex-1 flex-col p-4">
                {opts.title ? <h2 className="mb-2 text-sm font-semibold">{opts.title}</h2> : null}
                {notReady ? (
                  <div className="flex flex-1 items-center justify-center text-sm text-muted">{notReady}</div>
                ) : err ? (
                  <ErrorBanner title="Can't draw this chart" message={err.message} />
                ) : preview.data ? (
                  <>
                    <TabsContent value="chart" className="min-h-0 flex-1" data-testid="chart-canvas">
                      <ChartView data={preview.data} spec={debounced} />
                    </TabsContent>
                    <TabsContent value="table" className="min-h-0 flex-1">
                      <ChartTable data={preview.data} />
                    </TabsContent>
                    <TabsContent value="sql" className="min-h-0 flex-1">
                      <pre tabIndex={0} aria-label="Generated SQL" className="scroll-thin h-full overflow-auto rounded-md bg-surface-2 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{preview.data.sql}</pre>
                    </TabsContent>
                  </>
                ) : (
                  <div className="flex flex-1 items-center justify-center">
                    <Spinner />
                  </div>
                )}
              </Card>
            </Tabs>
          )}
        </section>
      </div>
    </>
  );
}

