"use client";
import Link from "next/link";
import { useState } from "react";
import { Database, FileSpreadsheet, MoreHorizontal, Pencil, SquareTerminal, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { formatBytes, formatCompact, formatRelative } from "@/lib/format";
import type { Dataset } from "@/lib/types";
import { useDatasets, useDeleteDataset } from "./hooks";
import { StatusBadge } from "./status-badge";
import { RenameDialog } from "./rename-dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";

export function DatasetList({ onUpload, limit, filter = "" }: { onUpload: () => void; limit?: number; filter?: string }) {
  const { data, isLoading, error } = useDatasets();
  const del = useDeleteDataset();
  const [renaming, setRenaming] = useState<Dataset | null>(null);
  const [deleting, setDeleting] = useState<Dataset | null>(null);

  if (isLoading)
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  if (error) return <ErrorBanner className="m-4" message={(error as Error).message} />;

  const f = filter.trim().toLowerCase();
  let items = data?.items ?? [];
  if (f) items = items.filter((d) => d.name.toLowerCase().includes(f) || d.sql_name.includes(f));
  if (limit) items = items.slice(0, limit);

  if (!items.length)
    return (
      <EmptyState
        icon={<Database />}
        title={f ? "No datasets match" : "No datasets yet"}
        description={f ? "Try a different search." : "Import a CSV or Parquet file to start exploring it with SQL."}
        action={
          f ? null : (
            <Button variant="primary" onClick={onUpload}>
              <Upload /> Import dataset
            </Button>
          )
        }
      />
    );

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]" aria-label="Datasets">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Rows</th>
              <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Columns</th>
              <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Size</th>
              <th className="hidden px-3 py-2 font-medium lg:table-cell">Created</th>
              <th className="w-10 px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.id} className="group border-b border-border last:border-0 hover:bg-surface-2/60">
                <td className="px-4 py-2.5">
                  <Link href={`/datasets/${d.id}`} className="flex items-center gap-2.5 outline-none">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-muted">
                      <FileSpreadsheet className="size-3.5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-medium group-hover:text-accent">{d.name}</span>
                      <span className="block truncate font-mono text-[11px] text-subtle">{d.sql_name}</span>
                    </span>
                  </Link>
                </td>
                <td className="px-3 py-2.5">
                  <StatusBadge status={d.status} />
                </td>
                <td className="tabular px-3 py-2.5 text-right">{formatCompact(d.row_count)}</td>
                <td className="tabular hidden px-3 py-2.5 text-right sm:table-cell">{d.column_count ?? "—"}</td>
                <td className="tabular hidden px-3 py-2.5 text-right text-muted md:table-cell">{formatBytes(d.processed_bytes)}</td>
                <td className="hidden px-3 py-2.5 text-muted lg:table-cell">{formatRelative(d.created_at)}</td>
                <td className="px-2 py-2.5">
                  <Menu>
                    <MenuTrigger asChild>
                      <Button size="icon-sm" variant="ghost" aria-label={`Actions for ${d.name}`}>
                        <MoreHorizontal />
                      </Button>
                    </MenuTrigger>
                    <MenuContent>
                      <MenuItem asChild disabled={d.status !== "ready"}>
                        <Link href={`/sql?dataset=${d.sql_name}`}>
                          <SquareTerminal /> Query in SQL
                        </Link>
                      </MenuItem>
                      <MenuItem onSelect={() => setRenaming(d)}>
                        <Pencil /> Rename
                      </MenuItem>
                      <MenuSeparator />
                      <MenuItem danger onSelect={() => setDeleting(d)}>
                        <Trash2 /> Delete
                      </MenuItem>
                    </MenuContent>
                  </Menu>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <RenameDialog dataset={renaming} onClose={() => setRenaming(null)} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "dataset"}?`}
        description="The original file, processed data and any charts built on it will be permanently removed."
        confirmLabel="Delete dataset"
        loading={del.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await del.mutateAsync(deleting.id);
            toast.success(`Deleted ${deleting.name}`);
          } catch (e) {
            toast.error((e as Error).message);
          }
          setDeleting(null);
        }}
      />
    </>
  );
}
