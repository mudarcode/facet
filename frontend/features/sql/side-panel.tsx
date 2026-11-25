"use client";
import { useState } from "react";
import { ChevronRight, FileSpreadsheet } from "lucide-react";
import { TypeIcon } from "@/components/type-icon";
import type { Dataset } from "@/lib/types";
import { cn } from "@/lib/utils";

export function SidePanel({
  datasets,
  onInsert,
}: {
  datasets: Dataset[];
  onInsert: (text: string) => void;
  onOpen?: (sql: string, savedId?: string) => void;
  activeSavedId?: string | null;
}) {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-surface lg:flex" aria-label="Schema browser">
      <div className="flex h-9 items-center border-b border-border px-3 text-xs font-medium">Datasets</div>
      <div className="scroll-thin flex-1 overflow-y-auto py-1">
        <SchemaTree datasets={datasets} onInsert={onInsert} />
      </div>
    </aside>
  );
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
