"use client";
import { useMemo, useRef } from "react";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ResultColumn } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatCell, formatNumber, typeKind } from "@/lib/format";
import { TypeIcon } from "@/components/type-icon";
import { Button } from "@/components/ui/button";

type Row = unknown[];

/**
 * Dense, virtualised result grid. Rendering is O(visible rows), so 1,000-row pages
 * scroll smoothly. Paging itself happens on the server.
 */
export function DataTable({
  columns,
  rows,
  rowOffset = 0,
  className,
  "aria-label": ariaLabel = "Results",
}: {
  columns: ResultColumn[];
  rows: Row[];
  rowOffset?: number;
  className?: string;
  "aria-label"?: string;
}) {
  const defs = useMemo<ColumnDef<Row>[]>(
    () =>
      columns.map((c, i) => ({
        id: `${i}`,
        header: () => (
          <div className="flex min-w-0 items-center gap-1.5">
            <TypeIcon type={c.type} />
            <span className="truncate font-medium text-fg">{c.name}</span>
            <span className="ml-auto pl-2 font-mono text-[10px] font-normal text-subtle uppercase">{shortType(c.type)}</span>
          </div>
        ),
        accessorFn: (r) => r[i],
        size: Math.min(320, Math.max(110, c.name.length * 8 + 70)),
        meta: { kind: typeKind(c.type) },
      })),
    [columns],
  );

  // TanStack Table returns fresh functions each render, so the compiler skips this component (expected).
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({ data: rows, columns: defs, getCoreRowModel: getCoreRowModel(), columnResizeMode: "onChange" });
  const parentRef = useRef<HTMLDivElement>(null);
  const tableRows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 30,
    overscan: 12,
  });
  const totalWidth = table.getTotalSize() + 56;
  const items = virtualizer.getVirtualItems();
  const padTop = items.length ? items[0]!.start : 0;
  const padBottom = items.length ? virtualizer.getTotalSize() - items[items.length - 1]!.end : 0;

  return (
    <div ref={parentRef} tabIndex={0} role="region" aria-label={ariaLabel} className={cn("scroll-thin relative overflow-auto focus-visible:outline-2 focus-visible:outline-[var(--ring)]", className)}>
      <table role="grid" aria-label={ariaLabel} aria-rowcount={rows.length} className="tabular border-separate border-spacing-0 text-[12.5px]" style={{ width: totalWidth, minWidth: "100%" }}>
        <thead className="sticky top-0 z-10">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              <th className="sticky left-0 z-20 w-14 border-r border-b border-border bg-surface-2 px-2 text-right text-[11px] font-normal text-subtle">#</th>
              {hg.headers.map((h) => (
                <th
                  key={h.id}
                  scope="col"
                  className="relative h-8 border-r border-b border-border bg-surface-2 px-2.5 text-left text-xs font-normal"
                  style={{ width: h.getSize() }}
                >
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  <div
                    onMouseDown={h.getResizeHandler()}
                    onTouchStart={h.getResizeHandler()}
                    className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-accent/40"
                    aria-hidden
                  />
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {padTop > 0 ? <tr style={{ height: padTop }} /> : null}
          {items.map((vi) => {
            const row = tableRows[vi.index]!;
            return (
              <tr key={row.id} className="group h-[30px]">
                <td className="sticky left-0 z-[1] border-r border-b border-border bg-surface px-2 text-right font-mono text-[11px] text-subtle group-hover:bg-surface-2">
                  {formatNumber(rowOffset + vi.index + 1)}
                </td>
                {row.getVisibleCells().map((cell) => {
                  const v = cell.getValue();
                  const kind = (cell.column.columnDef.meta as { kind: string } | undefined)?.kind;
                  return (
                    <td
                      key={cell.id}
                      className={cn(
                        "max-w-0 truncate border-r border-b border-border px-2.5 group-hover:bg-surface-2",
                        kind === "number" && "text-right font-mono text-[12px]",
                        kind === "temporal" && "font-mono text-[12px]",
                      )}
                      title={formatCell(v)}
                    >
                      {v === null || v === undefined ? <span className="text-subtle italic">null</span> : formatCell(v)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {padBottom > 0 ? <tr style={{ height: padBottom }} /> : null}
        </tbody>
      </table>
    </div>
  );
}

function shortType(t: string): string {
  return t.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ").replace(/\(.*\)/, "").slice(0, 12);
}

export function Pager({
  offset,
  limit,
  total,
  truncated,
  onChange,
  disabled,
}: {
  offset: number;
  limit: number;
  total: number;
  truncated?: boolean;
  onChange: (offset: number) => void;
  disabled?: boolean;
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="tabular">
        {formatNumber(from)}–{formatNumber(to)} of {formatNumber(total)}
        {truncated ? "+" : ""}
      </span>
      <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        <ChevronLeft />
      </Button>
      <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={disabled || offset + limit >= total} onClick={() => onChange(offset + limit)}>
        <ChevronRight />
      </Button>
    </div>
  );
}
