"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Lightbulb, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorBanner, ProgressBar, Skeleton } from "@/components/ui/feedback";
import { TypeIcon } from "@/components/type-icon";
import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { formatCell, formatCompact, formatNumber } from "@/lib/format";
import type { Dataset, ProfileColumn } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ProfileTab({ dataset }: { dataset: Dataset }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["datasets", dataset.id, "profile", dataset.current_version?.id],
    queryFn: () => api.profile(dataset.id),
    refetchInterval: (s) => (s.state.data?.status === "pending" ? 1000 : false),
  });
  const refresh = async () => {
    await api.refreshProfile(dataset.id);
    qc.invalidateQueries({ queryKey: ["datasets", dataset.id, "profile"] });
  };

  if (q.isLoading) return <Skeleton className="h-64" />;
  if (q.error) return <ErrorBanner message={(q.error as Error).message} />;
  const r = q.data!;
  if (r.status === "pending")
    return (
      <Card className="space-y-2 p-5" aria-live="polite">
        <p className="text-[13px] font-medium">Profiling columns…</p>
        <p className="text-xs text-muted">Statistics are computed by DuckDB in a background job.</p>
        <ProgressBar indeterminate />
      </Card>
    );
  if (r.status === "failed" || !r.profile)
    return <ErrorBanner title="Profiling failed" message={r.error ?? "Unknown error"} action={<Button size="sm" variant="outline" onClick={refresh}>Retry</Button>} />;

  const p = r.profile;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <div className="flex flex-wrap items-center gap-2">
          <span>
            {formatNumber(p.row_count)} rows · {p.column_count} columns · computed in {p.duration_s.toFixed(2)} s
          </span>
          {p.sampled ? (
            <Tooltip content={`Counts, nulls, min/max, mean and stddev are exact. Quantiles, histograms and top values use a ${p.sample_method} sample of ${formatNumber(p.sample_rows)} rows.`}>
              <Badge tone="warning">sampled: {formatCompact(p.sample_rows)} rows</Badge>
            </Tooltip>
          ) : (
            <Badge tone="success">exact</Badge>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={refresh}>
          <RefreshCw /> Recompute
        </Button>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {p.columns.map((c) => (
          <ColumnCard key={c.name} c={c} />
        ))}
      </div>
    </div>
  );
}

function ColumnCard({ c }: { c: ProfileColumn }) {
  const nonNull = c.count - c.nulls;
  return (
    <Card className="flex flex-col p-4" data-testid={`profile-${c.name}`}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 truncate text-[13px] font-semibold">
            <TypeIcon type={c.type} /> {c.name}
          </p>
          <p className="font-mono text-[11px] text-subtle">{c.type}</p>
        </div>
        <NullMeter pct={c.null_pct} />
      </div>
      <dl className="tabular grid grid-cols-3 gap-x-3 gap-y-2 text-xs">
        <Stat k="Non-null" v={formatCompact(nonNull)} />
        <Stat k={c.distinct_method.startsWith("exact") ? "Distinct" : "Distinct ≈"} v={formatCompact(c.distinct)} hint={c.distinct_method} />
        <Stat k="Nulls" v={formatCompact(c.nulls)} />
        {c.kind === "numeric" ? (
          <>
            <Stat k="Min" v={fmt(c.min)} />
            <Stat k="Mean" v={fmt(c.mean)} />
            <Stat k="Max" v={fmt(c.max)} />
            <Stat k="Std dev" v={fmt(c.stddev)} />
            <Stat k="Median" v={fmt(c.quantiles?.p50)} hint={c.quantiles?.method} />
            <Stat k="IQR" v={c.quantiles ? `${fmt(c.quantiles.p25)} – ${fmt(c.quantiles.p75)}` : "—"} />
          </>
        ) : null}
        {c.kind === "temporal" ? (
          <>
            <Stat k="Earliest" v={String(c.min ?? "—").slice(0, 10)} />
            <Stat k="Latest" v={String(c.max ?? "—").slice(0, 10)} />
          </>
        ) : null}
        {c.kind === "text" ? (
          <>
            <Stat k="Min length" v={fmt(c.min_length)} />
            <Stat k="Avg length" v={fmt(c.avg_length)} />
            <Stat k="Max length" v={fmt(c.max_length)} />
          </>
        ) : null}
      </dl>
      <div className="mt-3 flex-1">
        {c.top_values?.length ? <TopValues values={c.top_values} total={c.count} /> : c.histogram?.length ? <MiniHistogram c={c} /> : null}
      </div>
      {c.quality.length ? (
        <ul className="mt-3 space-y-1 border-t border-border pt-2.5">
          {c.quality.map((f) => (
            <li key={f.code} className="flex items-start gap-1.5 text-[11.5px] text-muted">
              {f.level === "warning" ? <AlertTriangle className="mt-px size-3.5 shrink-0 text-warning" /> : f.level === "suggestion" ? <Lightbulb className="mt-px size-3.5 shrink-0 text-accent" /> : <Info className="mt-px size-3.5 shrink-0 text-subtle" />}
              {f.message}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Math.abs(v) >= 1e6 ? formatCompact(v) : Number.isInteger(v) ? formatNumber(v) : v.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return formatCell(v);
}

function Stat({ k, v, hint }: { k: string; v: string; hint?: string }) {
  const body = (
    <div className="min-w-0">
      <dt className="text-[11px] text-subtle">{k}</dt>
      <dd className="truncate font-medium" title={v}>
        {v}
      </dd>
    </div>
  );
  return hint ? <Tooltip content={hint}>{body}</Tooltip> : body;
}

function NullMeter({ pct }: { pct: number }) {
  const tone = pct === 0 ? "text-success" : pct >= 50 ? "text-warning" : "text-muted";
  return (
    <div className="w-20 shrink-0 text-right">
      <p className={cn("tabular text-xs font-semibold", tone)}>{pct === 0 ? "0" : pct < 0.1 ? "<0.1" : pct.toFixed(1)}% null</p>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-[var(--fg-subtle)]" style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

/** Single-series distribution: thin bars, 2px gaps, rounded data-ends, hover tooltip per bar. */
function MiniHistogram({ c }: { c: ProfileColumn }) {
  const bins = c.histogram ?? [];
  const max = Math.max(1, ...bins.map((b) => b.count));
  const label = (b: (typeof bins)[number]) =>
    typeof b.start === "number" && b.end !== undefined ? `${fmt(b.start)} – ${fmt(b.end)}` : String(b.start).slice(0, b.unit === "day" ? 10 : b.unit === "month" ? 7 : 4);
  return (
    <figure aria-label={`Distribution of ${c.name}`}>
      <div className="flex h-16 items-end gap-[2px]" role="list">
        {bins.map((b, i) => (
          <Tooltip
            key={i}
            content={
              <span className="tabular">
                {label(b)}: {formatNumber(b.count)}
              </span>
            }
          >
            <div role="listitem" aria-label={`${label(b)}: ${b.count}`} className="group flex h-full min-w-0 flex-1 items-end">
              <div className="w-full rounded-t-[3px] bg-[var(--chart-1)] opacity-85 transition-opacity group-hover:opacity-100" style={{ height: `${Math.max(b.count ? 3 : 0, (b.count / max) * 100)}%` }} />
            </div>
          </Tooltip>
        ))}
      </div>
      <figcaption className="mt-1 flex justify-between font-mono text-[10px] text-subtle">
        <span>{bins.length ? label(bins[0]!).split(" – ")[0] : ""}</span>
        <span>{bins.length ? (bins.at(-1)!.end !== undefined ? fmt(bins.at(-1)!.end) : label(bins.at(-1)!)) : ""}</span>
      </figcaption>
    </figure>
  );
}

function TopValues({ values, total }: { values: { value: unknown; count: number }[]; total: number }) {
  const max = Math.max(1, ...values.map((v) => v.count));
  return (
    <ul className="space-y-1" aria-label="Most frequent values">
      {values.slice(0, 6).map((v, i) => (
        <li key={i} className="relative flex items-center justify-between gap-2 overflow-hidden rounded px-1.5 py-0.5 text-[11.5px]">
          <div className="absolute inset-y-0 left-0 rounded bg-[var(--chart-1)] opacity-15" style={{ width: `${(v.count / max) * 100}%` }} />
          <span className="relative truncate">{v.value === null ? <span className="text-subtle italic">null</span> : formatCell(v.value)}</span>
          <span className="tabular relative shrink-0 text-muted">
            {formatCompact(v.count)} · {((v.count / total) * 100).toFixed(1)}%
          </span>
        </li>
      ))}
    </ul>
  );
}
