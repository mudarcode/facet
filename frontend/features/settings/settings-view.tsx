"use client";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, Gauge, Keyboard, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/shell/page-header";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { API_URL, api } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/format";

interface Limits {
  max_upload_bytes: number;
  query_timeout_s: number;
  query_memory_limit: string;
  query_max_rows: number;
  query_page_size_max: number;
  max_concurrent_queries: number;
  export_max_rows: number;
  export_link_ttl_s?: number;
  profile_sample_threshold: number;
  supported_formats: string[];
  supported_encodings: string[];
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border py-2 last:border-0">
      <div>
        <div className="text-[13px]">{label}</div>
        {hint ? <div className="text-xs text-subtle">{hint}</div> : null}
      </div>
      <div className="shrink-0 font-mono text-xs text-fg tabular-nums">{value}</div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [
  ["Ctrl/⌘ + Enter", "Run the SQL in the editor"],
  ["Ctrl/⌘ + Space", "Autocomplete tables and columns"],
  ["Ctrl/⌘ + /", "Toggle line comment"],
  ["Tab / Shift + Tab", "Move between controls"],
];

export function SettingsView() {
  const s = useQuery({ queryKey: ["settings"], queryFn: () => api.settings() as Promise<unknown> as Promise<Limits> });
  const l = s.data;
  return (
    <>
      <PageHeader title="Settings & help" description="Workspace limits, security model and how-tos" />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-5xl gap-4 p-5 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Gauge className="size-4 text-muted" /> Limits
              </CardTitle>
            </CardHeader>
            <div className="px-4 pb-3" data-testid="limits">
              {s.error ? <ErrorBanner message={(s.error as Error).message} /> : null}
              {!l ? (
                <Skeleton className="h-56" />
              ) : (
                <>
                  <Row label="Maximum upload size" value={formatBytes(l.max_upload_bytes)} hint={`Formats: ${l.supported_formats.join(", ")}`} />
                  <Row label="Query timeout" value={`${l.query_timeout_s} s`} hint="Queries are interrupted, then their sandbox process is replaced" />
                  <Row label="Query memory" value={l.query_memory_limit} hint="Per query, enforced by DuckDB" />
                  <Row label="Rows kept per result" value={formatNumber(l.query_max_rows)} hint={`Paged ${formatNumber(l.query_page_size_max)} at a time`} />
                  <Row label="Concurrent queries" value={String(l.max_concurrent_queries)} hint="Extra queries wait briefly, then get a 'busy' error" />
                  <Row label="Export row cap" value={formatNumber(l.export_max_rows)} />
                  {l.export_link_ttl_s ? <Row label="Download link lifetime" value={`${Math.round(l.export_link_ttl_s / 60)} min`} /> : null}
                  <Row label="Profiling sample above" value={`${formatNumber(l.profile_sample_threshold)} rows`} hint="Larger datasets are profiled on a seeded reservoir sample" />
                  <Row label="CSV encodings" value={l.supported_encodings.join(", ")} />
                </>
              )}
              <p className="pt-2 text-xs text-subtle">Set with FACET_* environment variables on the API and worker.</p>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-muted" /> How queries are kept safe
              </CardTitle>
            </CardHeader>
            <ul className="list-disc space-y-2 px-8 pb-4 text-[13px] text-muted marker:text-subtle">
              <li>SQL is parsed into a syntax tree (sqlglot). Only a single read-only SELECT is accepted; DDL, DML, COPY, ATTACH, PRAGMA, SET and file-reading functions are rejected before anything runs.</li>
              <li>Tables must be your own datasets or CTEs. The query is re-rendered from the parsed tree, so the engine runs exactly what was checked.</li>
              <li>Each query runs in a separate process with a fresh in-memory DuckDB that can see only the Parquet files it needs, with external access, extension loading and configuration changes switched off.</li>
              <li>Time, memory, row and concurrency limits apply to every query.</li>
              <li>CSV exports prefix cells starting with = + - @ so spreadsheets don&apos;t run them as formulas.</li>
            </ul>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpen className="size-4 text-muted" /> Getting started
              </CardTitle>
            </CardHeader>
            <ol className="list-decimal space-y-2 px-8 pb-4 text-[13px] text-muted marker:text-subtle">
              <li>Import a CSV or Parquet file from Datasets. It is validated, typed and stored as Parquet in the background.</li>
              <li>Open the dataset to check its schema, preview rows and read the column profile. Fix a column&apos;s type from the Schema tab.</li>
              <li>Query it in SQL by its SQL name, for example <code className="rounded bg-surface-2 px-1 font-mono text-xs">SELECT * FROM sales LIMIT 10</code>. Save useful queries.</li>
              <li>Clean data visually in the Transform tab and apply the result as a new dataset.</li>
              <li>Build charts from a dataset or saved query, then arrange them on a dashboard with shared filters.</li>
            </ol>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Keyboard className="size-4 text-muted" /> Keyboard shortcuts
              </CardTitle>
            </CardHeader>
            <dl className="px-4 pb-3">
              {SHORTCUTS.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-b border-border py-2 text-[13px] last:border-0">
                  <dt className="text-muted">{v}</dt>
                  <dd>
                    <kbd className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px]">{k}</kbd>
                  </dd>
                </div>
              ))}
            </dl>
            <div className="border-t border-border px-4 py-3">
              <a href={`${API_URL}/docs`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-[13px] text-accent hover:underline">
                API reference (OpenAPI) <ExternalLink className="size-3.5" />
              </a>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
