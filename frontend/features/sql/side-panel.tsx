"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileSpreadsheet, History, Bookmark, Trash2, Database } from "lucide-react";
import { toast } from "sonner";
import { TypeIcon } from "@/components/type-icon";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import type { Dataset, QueryRun } from "@/lib/types";
import { formatMs, formatNumber, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

export function SidePanel({
  datasets,
  onInsert,
  onOpen,
  activeSavedId,
}: {
  datasets: Dataset[];
  onInsert: (text: string) => void;
  onOpen: (sql: string, savedId?: string) => void;
  activeSavedId: string | null;
}) {
  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-border bg-surface lg:flex" aria-label="SQL side panel">
      <Tabs defaultValue="schema" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="px-2">
          <TabsTrigger value="schema" className="h-9 px-2 text-xs">
            <Database /> Schema
          </TabsTrigger>
          <TabsTrigger value="saved" className="h-9 px-2 text-xs">
            <Bookmark /> Saved
          </TabsTrigger>
          <TabsTrigger value="history" className="h-9 px-2 text-xs">
            <History /> History
          </TabsTrigger>
        </TabsList>
        <TabsContent value="schema" className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1">
          <SchemaTree datasets={datasets} onInsert={onInsert} />
        </TabsContent>
        <TabsContent value="saved" className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          <SavedList onOpen={onOpen} activeId={activeSavedId} />
        </TabsContent>
        <TabsContent value="history" className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          <HistoryList onOpen={(q) => onOpen(q)} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}

function SavedList({ onOpen, activeId }: { onOpen: (sql: string, id: string) => void; activeId: string | null }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["saved-queries"], queryFn: api.savedQueries });
  const del = useMutation({
    mutationFn: api.deleteSavedQuery,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Saved query deleted");
    },
  });
  if (q.isLoading) return <Skeleton className="m-3 h-20" />;
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="px-3 py-4 text-xs text-muted">No saved queries yet. Use Save in the toolbar to keep a query.</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((s) => (
        <li key={s.id} className={cn("group relative", activeId === s.id && "bg-accent-soft")}>
          <button className="block w-full px-3 py-2 text-left hover:bg-surface-2" onClick={() => onOpen(s.sql, s.id)}>
            <p className="truncate text-[12.5px] font-medium">{s.name}</p>
            <p className="truncate font-mono text-[11px] text-subtle">{s.sql.replace(/\s+/g, " ")}</p>
            <p className="mt-0.5 text-[10.5px] text-subtle">updated {formatRelative(s.updated_at)}</p>
          </button>
          <button
            className="absolute top-2 right-2 hidden rounded p-1 text-subtle group-hover:block hover:bg-danger-soft hover:text-danger"
            aria-label={`Delete ${s.name}`}
            onClick={() => del.mutate(s.id)}
          >
            <Trash2 className="size-3.5" />
          </button>
        </li>
      ))}
    </ul>
  );
}

function HistoryList({ onOpen }: { onOpen: (sql: string) => void }) {
  const q = useQuery({ queryKey: ["query-history"], queryFn: () => api.history(), refetchInterval: 5000 });
  if (q.isLoading) return <Skeleton className="m-3 h-20" />;
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="px-3 py-4 text-xs text-muted">Queries you run appear here.</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((r) => (
        <li key={r.id}>
          <button className="block w-full px-3 py-2 text-left hover:bg-surface-2" onClick={() => onOpen(r.sql)} title={r.error ?? undefined}>
            <div className="mb-0.5 flex items-center gap-1.5">
              <RunBadge status={r.status} />
              <span className="tabular text-[10.5px] text-subtle">
                {r.status === "succeeded" ? `${formatNumber(r.row_count)} rows · ${formatMs(r.engine_ms)}` : ""} · {formatRelative(r.created_at)}
              </span>
            </div>
            <p className="line-clamp-2 font-mono text-[11px] text-muted">{r.sql}</p>
          </button>
        </li>
      ))}
    </ul>
  );
}

function RunBadge({ status }: { status: QueryRun["status"] }) {
  const tone = status === "succeeded" ? "success" : status === "rejected" ? "warning" : "danger";
  return <Badge tone={tone}>{status}</Badge>;
}

export function SchemaTree({ datasets, onInsert }: { datasets: Dataset[]; onInsert: (t: string) => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!datasets.length) return <p className="px-3 py-4 text-xs text-muted">No ready datasets. Import one from the Datasets page.</p>;
  return (
    <ul>
      {datasets.map((d) => (
        <li key={d.id}>
          <div className="group flex items-center gap-1 px-1.5">
            <button
              className="rounded p-0.5 text-subtle hover:text-fg"
              aria-label={open[d.id] ? `Collapse ${d.sql_name}` : `Expand ${d.sql_name}`}
              aria-expanded={!!open[d.id]}
              onClick={() => setOpen((o) => ({ ...o, [d.id]: !o[d.id] }))}
            >
              <ChevronRight className={cn("size-3.5 transition-transform", open[d.id] && "rotate-90")} />
            </button>
            <button
              className="flex min-w-0 flex-1 items-center gap-1.5 rounded px-1 py-1 text-left text-[12.5px] hover:bg-surface-2"
              onClick={() => onInsert(d.sql_name)}
              title={`Insert ${d.sql_name}`}
            >
              <FileSpreadsheet className="size-3.5 shrink-0 text-muted" />
              <span className="truncate font-mono">{d.sql_name}</span>
              <span className="tabular ml-auto text-[10.5px] text-subtle">{formatNumber(d.row_count)}</span>
            </button>
          </div>
          {open[d.id] ? (
            <ul className="mb-1 ml-6 border-l border-border pl-1">
              {(d.current_version?.columns ?? []).map((c) => (
                <li key={c.name}>
                  <button
                    className="flex w-full items-center gap-1.5 rounded px-1.5 py-0.5 text-left text-xs hover:bg-surface-2"
                    onClick={() => onInsert(/^[a-z_][a-z0-9_]*$/.test(c.name) ? c.name : `"${c.name.replace(/"/g, '""')}"`)}
                  >
                    <TypeIcon type={c.type} />
                    <span className="truncate">{c.name}</span>
                    <span className="ml-auto font-mono text-[10px] text-subtle">{c.type.toLowerCase().slice(0, 9)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
