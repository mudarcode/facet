"use client";
import { CheckCircle2, Clock, Database, ShieldAlert, Timer, X, XCircle } from "lucide-react";
import { DataTable, Pager } from "@/components/data-table";
import { EmptyState, ProgressBar } from "@/components/ui/feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import type { ApiError } from "@/lib/api";
import type { QueryResult } from "@/lib/types";
import { formatMs, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

export type RunState =
  | { status: "idle" }
  | { status: "running"; previous?: QueryResult }
  | { status: "success"; result: QueryResult; roundTripMs: number }
  | { status: "error"; error: ApiError; roundTripMs?: number };

export function ResultsPanel({
  state,
  plan,
  onPage,
  pageSize,
  onClosePlan,
}: {
  state: RunState;
  plan: string | null;
  onPage: (offset: number) => void;
  pageSize: number;
  onClosePlan: () => void;
}) {
  if (plan) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-9 items-center justify-between border-b border-border px-3 text-xs">
          <span className="font-medium">Query plan</span>
          <Button size="icon-sm" variant="ghost" onClick={onClosePlan} aria-label="Close plan">
            <X />
          </Button>
        </div>
        <pre className="scroll-thin flex-1 overflow-auto bg-surface p-4 font-mono text-[11.5px] leading-snug text-muted">{plan}</pre>
      </div>
    );
  }

  const result = state.status === "success" ? state.result : state.status === "running" ? state.previous : undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col" aria-live="polite">
      <StatusBar state={state} onPage={onPage} pageSize={pageSize} />
      {state.status === "running" ? <ProgressBar indeterminate className="h-0.5 rounded-none" /> : null}
      <div className={cn("min-h-0 flex-1", state.status === "running" && "opacity-60")}>
        {state.status === "error" ? (
          <QueryErrorView error={state.error} />
        ) : result ? (
          result.columns.length ? (
            <DataTable columns={result.columns} rows={result.rows} rowOffset={result.offset} className="h-full" aria-label="Query results" />
          ) : (
            <EmptyState title="Query returned no columns" />
          )
        ) : state.status === "idle" ? (
          <EmptyState icon={<Database />} title="Run a query to see results" description="Results are paginated server-side; the full result is capped to keep the browser responsive." />
        ) : null}
      </div>
    </div>
  );
}

function StatusBar({ state, onPage, pageSize }: { state: RunState; onPage: (o: number) => void; pageSize: number }) {
  return (
    <div className="flex h-9 shrink-0 items-center gap-3 border-b border-border bg-surface px-3 text-xs">
      {state.status === "idle" ? <span className="text-muted">Ready</span> : null}
      {state.status === "running" ? (
        <span className="flex items-center gap-1.5 text-muted">
          <Clock className="size-3.5 animate-pulse" /> Running…
        </span>
      ) : null}
      {state.status === "error" ? (
        <span className="flex items-center gap-1.5 font-medium text-danger">
          <XCircle className="size-3.5" /> {labelFor(state.error.code)}
        </span>
      ) : null}
      {state.status === "success" ? (
        <>
          <span className="flex items-center gap-1.5 font-medium text-success" data-testid="query-status">
            <CheckCircle2 className="size-3.5" /> {formatNumber(state.result.total_rows)}
            {state.result.truncated ? "+" : ""} row{state.result.total_rows === 1 ? "" : "s"}
          </span>
          <Timing result={state.result} roundTrip={state.roundTripMs} />
          {state.result.truncated ? (
            <Tooltip content={`Interactive results are capped at ${formatNumber(state.result.max_rows)} rows. Use export for the full result.`}>
              <Badge tone="warning">capped at {formatNumber(state.result.max_rows)}</Badge>
            </Tooltip>
          ) : null}
          <div className="ml-auto">
            <Pager offset={state.result.offset} limit={pageSize} total={state.result.total_rows} truncated={state.result.truncated} onChange={onPage} />
          </div>
        </>
      ) : null}
    </div>
  );
}

function Timing({ result, roundTrip }: { result: QueryResult; roundTrip: number }) {
  return (
    <Tooltip
      content={
        <div className="space-y-0.5 py-0.5 tabular">
          <div>DuckDB execution: {formatMs(result.engine_ms)}</div>
          <div>Server total (validate + sandbox IPC): {formatMs(result.total_ms)}</div>
          <div>Browser round trip: {formatMs(roundTrip)}</div>
        </div>
      }
    >
      <span className="flex cursor-default items-center gap-1.5 text-muted tabular" data-testid="query-timing">
        <Timer className="size-3.5" /> {formatMs(result.engine_ms)} engine · {formatMs(roundTrip)} total
      </span>
    </Tooltip>
  );
}

function labelFor(code: string) {
  switch (code) {
    case "query_rejected":
      return "Rejected by SQL policy";
    case "query_failed":
      return "Query error";
    case "query_timeout":
      return "Timed out";
    case "busy":
      return "Workers busy";
    case "network":
      return "API unreachable";
    default:
      return "Error";
  }
}

function QueryErrorView({ error }: { error: ApiError }) {
  const rejected = error.code === "query_rejected";
  const details = error.details as { available?: string[] } | undefined;
  return (
    <div className="p-4">
      <div role="alert" className={cn("rounded-lg border px-4 py-3", rejected ? "border-warning/30 bg-warning-soft" : "border-danger/25 bg-danger-soft")}>
        <p className={cn("flex items-center gap-2 text-[13px] font-semibold", rejected ? "text-warning" : "text-danger")}>
          {rejected ? <ShieldAlert className="size-4" /> : <XCircle className="size-4" />}
          {labelFor(error.code)}
        </p>
        <pre className="mt-1.5 font-mono text-[12px] whitespace-pre-wrap text-fg" data-testid="query-error">
          {error.message}
        </pre>
        {details?.available?.length ? (
          <p className="mt-2 text-xs text-muted">
            Available datasets: {details.available.map((d) => <code key={d} className="mr-1.5 font-mono">{d}</code>)}
          </p>
        ) : null}
        {rejected ? <p className="mt-2 text-xs text-muted">Facet only runs single read-only SELECT statements over your own datasets.</p> : null}
      </div>
    </div>
  );
}
