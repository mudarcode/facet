"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Code2, Play, Plus, Save, Trash2, Wand2, X } from "lucide-react";
import { toast } from "sonner";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/data-table";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { api, ApiError } from "@/lib/api";
import type { Dataset, Transformation, TransformStep } from "@/lib/types";
import { formatMs, formatNumber } from "@/lib/format";

const STEP_LABELS: Record<TransformStep["op"], string> = {
  select: "Select columns",
  rename: "Rename column",
  filter: "Filter rows",
  drop_nulls: "Remove missing values",
  sort: "Sort",
  cast: "Change type",
  derive: "Derived column",
  group: "Group & aggregate",
  distinct: "Remove duplicates",
  limit: "Limit rows",
};

const OPS = ["=", "!=", ">", ">=", "<", "<=", "contains", "not_contains", "starts_with", "ends_with", "in", "is_null", "is_not_null"];
const AGGS = ["count", "count_distinct", "sum", "avg", "min", "max", "median", "stddev"];
const TYPES = ["BOOLEAN", "BIGINT", "INTEGER", "DOUBLE", "DECIMAL(18,4)", "VARCHAR", "DATE", "TIMESTAMP"];

function newStep(op: TransformStep["op"], cols: string[]): TransformStep {
  const c = cols[0] ?? "";
  switch (op) {
    case "select":
      return { op, columns: [...cols] };
    case "rename":
      return { op, mapping: { [c]: `${c}_renamed` } };
    case "filter":
      return { op, combine: "and", conditions: [{ column: c, op: "=", value: "" }] };
    case "drop_nulls":
      return { op, columns: [c] };
    case "sort":
      return { op, keys: [{ column: c, desc: false }] };
    case "cast":
      return { op, column: c, to: "VARCHAR" };
    case "derive":
      return { op, name: "new_column", expression: "" };
    case "group":
      return { op, by: [c], aggregations: [{ column: null, func: "count" }] };
    case "distinct":
      return { op, columns: [] };
    case "limit":
      return { op, count: 1000 };
  }
}

/** Columns available after applying steps[0..i). Mirrors the server compiler. */
function columnsAfter(steps: TransformStep[], base: string[], upto: number): string[] {
  let cols = [...base];
  for (const s of steps.slice(0, upto)) {
    if (s.op === "select") cols = s.columns.filter((c) => cols.includes(c));
    else if (s.op === "rename") cols = cols.map((c) => s.mapping[c] ?? c);
    else if (s.op === "derive" && s.name && !cols.includes(s.name)) cols = [...cols, s.name];
    else if (s.op === "group") cols = [...s.by, ...s.aggregations.map((a) => a.alias || (a.column ? `${a.func}_${a.column}` : "count"))];
  }
  return cols;
}

export function TransformTab({ dataset }: { dataset: Dataset }) {
  const qc = useQueryClient();
  const base = useMemo(() => (dataset.current_version?.columns ?? []).map((c) => c.name), [dataset]);
  const [steps, setSteps] = useState<TransformStep[]>([]);
  const [applied, setApplied] = useState<TransformStep[]>([]);
  const [current, setCurrent] = useState<Transformation | null>(null);
  const [name, setName] = useState("");
  const [showSql, setShowSql] = useState(false);
  const [busy, setBusy] = useState(false);
  const saved = useQuery({ queryKey: ["transformations", dataset.id], queryFn: () => api.transformations(dataset.id) });
  const preview = useQuery({
    queryKey: ["transform-preview", dataset.id, dataset.current_version?.id, JSON.stringify(applied)],
    queryFn: () => api.previewTransform(dataset.id, applied, 0, 200),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const dirty = JSON.stringify(steps) !== JSON.stringify(applied);

  const update = (i: number, s: TransformStep) => setSteps((all) => all.map((x, j) => (j === i ? s : x)));
  const move = (i: number, d: -1 | 1) =>
    setSteps((all) => {
      const next = [...all];
      const j = i + d;
      if (j < 0 || j >= next.length) return all;
      [next[i], next[j]] = [next[j]!, next[i]!];
      return next;
    });

  const load = (t: Transformation) => {
    setCurrent(t);
    setName(t.name);
    setSteps(t.steps);
    setApplied(t.steps);
  };

  const save = async () => {
    setBusy(true);
    try {
      const t = current
        ? await api.updateTransformation(current.id, { name: name.trim() || current.name, steps })
        : await api.createTransformation({ dataset_id: dataset.id, name: name.trim() || "Untitled transformation", steps });
      setCurrent(t);
      setName(t.name);
      setApplied(steps);
      qc.invalidateQueries({ queryKey: ["transformations", dataset.id] });
      toast.success(`Saved “${t.name}”`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const materialize = async () => {
    if (!current) return;
    setBusy(true);
    try {
      const r = await api.materialize(current.id);
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["transformations", dataset.id] });
      toast.success("Creating dataset from transformation…", {
        action: { label: "Open", onClick: () => (window.location.href = `/datasets/${r.dataset_id}`) },
      });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not apply");
    } finally {
      setBusy(false);
    }
  };

  const err = preview.error as ApiError | null;

  return (
    <div className="grid gap-4 xl:grid-cols-[400px_1fr]">
      <div className="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle>Pipeline</CardTitle>
            <div className="flex items-center gap-1.5">
              {saved.data?.length ? (
                <NativeSelect
                  aria-label="Open saved transformation"
                  className="h-7 w-40 text-xs"
                  value={current?.id ?? ""}
                  onChange={(e) => {
                    const t = saved.data?.find((x) => x.id === e.target.value);
                    if (t) load(t);
                    else {
                      setCurrent(null);
                      setName("");
                      setSteps([]);
                      setApplied([]);
                    }
                  }}
                >
                  <option value="">New transformation</option>
                  {saved.data.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </NativeSelect>
              ) : null}
            </div>
          </CardHeader>
          <div className="space-y-2 p-3">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Transformation name" aria-label="Transformation name" />
            {steps.length === 0 ? <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted">No steps yet. The preview shows the dataset as stored.</p> : null}
            <ol className="space-y-2">
              {steps.map((s, i) => (
                <li key={i} className="rounded-lg border border-border bg-surface-2/50">
                  <div className="flex items-center gap-1 border-b border-border px-2.5 py-1.5">
                    <span className="flex size-5 items-center justify-center rounded bg-accent-soft text-[10px] font-semibold text-accent">{i + 1}</span>
                    <span className="ml-1 text-xs font-medium">{STEP_LABELS[s.op]}</span>
                    <div className="ml-auto flex">
                      <Button size="icon-sm" variant="ghost" aria-label="Move step up" onClick={() => move(i, -1)} disabled={i === 0}>
                        <ArrowUp />
                      </Button>
                      <Button size="icon-sm" variant="ghost" aria-label="Move step down" onClick={() => move(i, 1)} disabled={i === steps.length - 1}>
                        <ArrowDown />
                      </Button>
                      <Button size="icon-sm" variant="ghost" aria-label="Remove step" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                        <X />
                      </Button>
                    </div>
                  </div>
                  <div className="p-2.5">
                    <StepEditor step={s} cols={columnsAfter(steps, base, i)} onChange={(n) => update(i, n)} />
                  </div>
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-2 pt-1">
              <Menu>
                <MenuTrigger asChild>
                  <Button size="sm" variant="outline" data-testid="add-step">
                    <Plus /> Add step
                  </Button>
                </MenuTrigger>
                <MenuContent align="start">
                  {(Object.keys(STEP_LABELS) as TransformStep["op"][]).map((op) => (
                    <MenuItem key={op} onSelect={() => setSteps([...steps, newStep(op, columnsAfter(steps, base, steps.length))])}>
                      {STEP_LABELS[op]}
                    </MenuItem>
                  ))}
                </MenuContent>
              </Menu>
              <Button size="sm" variant={dirty ? "primary" : "secondary"} onClick={() => setApplied(steps)} data-testid="preview-steps">
                <Play /> Preview
              </Button>
              <div className="ml-auto flex gap-2">
                <Button size="sm" variant="outline" onClick={save} loading={busy} disabled={!!err && !dirty}>
                  <Save /> Save
                </Button>
                <Button size="sm" variant="outline" onClick={materialize} disabled={!current || dirty || busy} title={!current ? "Save the transformation first" : dirty ? "Save changes first" : undefined}>
                  <Wand2 /> Create dataset
                </Button>
              </div>
            </div>
            {current?.output_dataset_id ? (
              <p className="text-xs text-muted">
                Output dataset:{" "}
                <Link className="text-accent hover:underline" href={`/datasets/${current.output_dataset_id}`}>
                  open
                </Link>{" "}
                · re-running adds a new version.
              </p>
            ) : null}
          </div>
        </Card>
      </div>
      <Card className="min-w-0 overflow-hidden">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Preview
            {preview.data ? (
              <span className="tabular text-xs font-normal text-muted">
                {formatNumber(preview.data.total_rows)}
                {preview.data.truncated ? "+" : ""} rows · {formatMs(preview.data.engine_ms)}
              </span>
            ) : null}
            {dirty ? <Badge tone="warning">unapplied changes</Badge> : null}
          </CardTitle>
          <Button size="sm" variant="ghost" onClick={() => setShowSql((s) => !s)}>
            <Code2 /> {showSql ? "Hide SQL" : "Show SQL"}
          </Button>
        </CardHeader>
        {showSql && preview.data ? <pre className="scroll-thin max-h-56 overflow-auto border-b border-border bg-surface-2 p-3 font-mono text-[11.5px] text-muted">{preview.data.sql}</pre> : null}
        {err ? <ErrorBanner className="m-3" title="Invalid pipeline" message={err.message} /> : null}
        {preview.isLoading ? (
          <Skeleton className="m-3 h-64" />
        ) : preview.data ? (
          <DataTable columns={preview.data.columns} rows={preview.data.rows} className="h-[520px]" aria-label="Transformation preview" />
        ) : null}
      </Card>
    </div>
  );
}

function ColumnSelect({ cols, value, onChange, label }: { cols: string[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <NativeSelect aria-label={label} className="h-7 text-xs" value={value} onChange={(e) => onChange(e.target.value)}>
      {!cols.includes(value) && value ? <option value={value}>{value} (missing)</option> : null}
      {cols.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </NativeSelect>
  );
}

function ColumnChips({ cols, selected, onChange }: { cols: string[]; selected: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1">
      {cols.map((c) => {
        const on = selected.includes(c);
        return (
          <button
            key={c}
            aria-pressed={on}
            onClick={() => onChange(on ? selected.filter((x) => x !== c) : [...selected, c])}
            className={on ? "rounded-md border border-accent bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent" : "rounded-md border border-border bg-surface px-1.5 py-0.5 text-[11px] text-muted hover:text-fg"}
          >
            {c}
          </button>
        );
      })}
    </div>
  );
}

function StepEditor({ step, cols, onChange }: { step: TransformStep; cols: string[]; onChange: (s: TransformStep) => void }) {
  switch (step.op) {
    case "select":
      return <ColumnChips cols={cols} selected={step.columns} onChange={(columns) => onChange({ ...step, columns })} />;
    case "drop_nulls":
      return (
        <div className="space-y-1">
          <p className="text-[11px] text-muted">Drop rows where any selected column is null</p>
          <ColumnChips cols={cols} selected={step.columns} onChange={(columns) => onChange({ ...step, columns })} />
        </div>
      );
    case "distinct":
      return (
        <div className="space-y-1">
          <p className="text-[11px] text-muted">Key columns (none = whole row)</p>
          <ColumnChips cols={cols} selected={step.columns} onChange={(columns) => onChange({ ...step, columns })} />
        </div>
      );
    case "rename": {
      const [from, to] = Object.entries(step.mapping)[0] ?? ["", ""];
      return (
        <div className="grid grid-cols-2 gap-2">
          <ColumnSelect label="Column to rename" cols={cols} value={from} onChange={(f) => onChange({ ...step, mapping: { [f]: to } })} />
          <Input className="h-7 text-xs" aria-label="New name" value={to} onChange={(e) => onChange({ ...step, mapping: { [from]: e.target.value } })} />
        </div>
      );
    }
    case "cast":
      return (
        <div className="grid grid-cols-2 gap-2">
          <ColumnSelect label="Column" cols={cols} value={step.column} onChange={(column) => onChange({ ...step, column })} />
          <NativeSelect aria-label="Target type" className="h-7 text-xs" value={step.to} onChange={(e) => onChange({ ...step, to: e.target.value })}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </NativeSelect>
        </div>
      );
    case "derive":
      return (
        <div className="space-y-1.5">
          <Input className="h-7 text-xs" aria-label="New column name" value={step.name} onChange={(e) => onChange({ ...step, name: e.target.value })} placeholder="column name" />
          <Input className="h-7 font-mono text-xs" aria-label="Expression" value={step.expression} onChange={(e) => onChange({ ...step, expression: e.target.value })} placeholder="e.g. qty * price" />
        </div>
      );
    case "limit":
      return <Input type="number" min={1} className="h-7 text-xs" aria-label="Row limit" value={step.count} onChange={(e) => onChange({ ...step, count: Math.max(1, Number(e.target.value) || 1) })} />;
    case "sort":
      return (
        <div className="space-y-1.5">
          {step.keys.map((k, i) => (
            <div key={i} className="flex gap-1.5">
              <ColumnSelect label="Sort column" cols={cols} value={k.column} onChange={(column) => onChange({ ...step, keys: step.keys.map((x, j) => (j === i ? { ...x, column } : x)) })} />
              <NativeSelect aria-label="Direction" className="h-7 w-24 text-xs" value={k.desc ? "desc" : "asc"} onChange={(e) => onChange({ ...step, keys: step.keys.map((x, j) => (j === i ? { ...x, desc: e.target.value === "desc" } : x)) })}>
                <option value="asc">Asc</option>
                <option value="desc">Desc</option>
              </NativeSelect>
              {step.keys.length > 1 ? (
                <Button size="icon-sm" variant="ghost" aria-label="Remove sort key" onClick={() => onChange({ ...step, keys: step.keys.filter((_, j) => j !== i) })}>
                  <Trash2 />
                </Button>
              ) : null}
            </div>
          ))}
          <button className="text-[11px] font-medium text-accent" onClick={() => onChange({ ...step, keys: [...step.keys, { column: cols[0] ?? "", desc: false }] })}>
            + Add key
          </button>
        </div>
      );
    case "filter":
      return (
        <div className="space-y-1.5">
          {step.conditions.map((c, i) => {
            const unary = c.op === "is_null" || c.op === "is_not_null";
            const set = (patch: Partial<typeof c>) => onChange({ ...step, conditions: step.conditions.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
            return (
              <div key={i} className="grid grid-cols-[1fr_92px_1fr_auto] gap-1.5">
                <ColumnSelect label="Filter column" cols={cols} value={c.column} onChange={(column) => set({ column })} />
                <NativeSelect aria-label="Operator" className="h-7 text-xs" value={c.op} onChange={(e) => set({ op: e.target.value })}>
                  {OPS.map((o) => (
                    <option key={o} value={o}>
                      {o.replace(/_/g, " ")}
                    </option>
                  ))}
                </NativeSelect>
                <Input
                  className="h-7 text-xs"
                  aria-label="Value"
                  disabled={unary}
                  placeholder={c.op === "in" ? "a, b, c" : "value"}
                  value={Array.isArray(c.value) ? c.value.join(", ") : String(c.value ?? "")}
                  onChange={(e) => {
                    const raw = e.target.value;
                    const coerce = (v: string) => (v.trim() !== "" && !Number.isNaN(Number(v)) ? Number(v) : v.trim());
                    set({ value: c.op === "in" ? raw.split(",").map(coerce) : coerce(raw) });
                  }}
                />
                <Button size="icon-sm" variant="ghost" aria-label="Remove condition" disabled={step.conditions.length === 1} onClick={() => onChange({ ...step, conditions: step.conditions.filter((_, j) => j !== i) })}>
                  <Trash2 />
                </Button>
              </div>
            );
          })}
          <div className="flex items-center gap-2">
            <button className="text-[11px] font-medium text-accent" onClick={() => onChange({ ...step, conditions: [...step.conditions, { column: cols[0] ?? "", op: "=", value: "" }] })}>
              + Add condition
            </button>
            {step.conditions.length > 1 ? (
              <NativeSelect aria-label="Combine conditions" className="h-6 w-20 text-[11px]" value={step.combine ?? "and"} onChange={(e) => onChange({ ...step, combine: e.target.value as "and" | "or" })}>
                <option value="and">AND</option>
                <option value="or">OR</option>
              </NativeSelect>
            ) : null}
          </div>
        </div>
      );
    case "group":
      return (
        <div className="space-y-2">
          <div>
            <p className="mb-1 text-[11px] text-muted">Group by</p>
            <ColumnChips cols={cols} selected={step.by} onChange={(by) => onChange({ ...step, by })} />
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] text-muted">Aggregations</p>
            {step.aggregations.map((a, i) => {
              const set = (patch: Partial<typeof a>) => onChange({ ...step, aggregations: step.aggregations.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
              return (
                <div key={i} className="grid grid-cols-[110px_1fr_1fr_auto] gap-1.5">
                  <NativeSelect aria-label="Aggregate function" className="h-7 text-xs" value={a.func} onChange={(e) => set({ func: e.target.value, column: e.target.value === "count" ? a.column : a.column ?? cols[0] ?? null })}>
                    {AGGS.map((f) => (
                      <option key={f} value={f}>
                        {f.replace("_", " ")}
                      </option>
                    ))}
                  </NativeSelect>
                  <NativeSelect aria-label="Aggregate column" className="h-7 text-xs" value={a.column ?? ""} onChange={(e) => set({ column: e.target.value || null })}>
                    {a.func === "count" ? <option value="">* (rows)</option> : null}
                    {cols.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </NativeSelect>
                  <Input className="h-7 text-xs" aria-label="Alias" placeholder="alias" value={a.alias ?? ""} onChange={(e) => set({ alias: e.target.value || undefined })} />
                  <Button size="icon-sm" variant="ghost" aria-label="Remove aggregation" disabled={step.aggregations.length === 1} onClick={() => onChange({ ...step, aggregations: step.aggregations.filter((_, j) => j !== i) })}>
                    <Trash2 />
                  </Button>
                </div>
              );
            })}
            <button className="text-[11px] font-medium text-accent" onClick={() => onChange({ ...step, aggregations: [...step.aggregations, { column: cols[0] ?? null, func: "sum" }] })}>
              + Add aggregation
            </button>
          </div>
        </div>
      );
  }
}
