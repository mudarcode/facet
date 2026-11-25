"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Chart } from "@/lib/types";
import { SavedChartBody } from "./chart-card";

export function ChartList() {
  const qc = useQueryClient();
  const charts = useQuery({ queryKey: ["charts"], queryFn: api.charts });
  const [toDelete, setToDelete] = useState<Chart | null>(null);
  const [busy, setBusy] = useState(false);

  const remove = async () => {
    if (!toDelete) return;
    setBusy(true);
    try {
      await api.deleteChart(toDelete.id);
      qc.invalidateQueries({ queryKey: ["charts"] });
      qc.invalidateQueries({ queryKey: ["dashboards"] });
      toast.success(`Deleted “${toDelete.name}”`);
      setToDelete(null);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Charts"
        description="Saved visualizations, aggregated in DuckDB"
        actions={
          <Link href="/charts/new" className={buttonClasses({ variant: "primary" })} data-testid="new-chart">
            <Plus /> New chart
          </Link>
        }
      />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl p-5">
          {charts.error ? <ErrorBanner message={(charts.error as Error).message} /> : null}
          {charts.isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-64" />
              ))}
            </div>
          ) : charts.data?.length === 0 ? (
            <Card>
              <EmptyState
                icon={<BarChart3 />}
                title="No charts yet"
                description="Build a bar, line, area, scatter, histogram or stat chart from any dataset or saved query."
                action={
                  <Link href="/charts/new" className={buttonClasses({ variant: "primary" })}>
                    <Plus /> New chart
                  </Link>
                }
              />
            </Card>
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="chart-list">
              {charts.data?.map((c) => (
                <li key={c.id}>
                  <Card className="flex h-72 flex-col overflow-hidden">
                    <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-2.5">
                      <div className="min-w-0">
                        <Link href={`/charts/${c.id}`} className="block truncate text-sm font-medium hover:text-accent">
                          {c.name}
                        </Link>
                        <p className="truncate text-xs text-subtle">
                          {c.spec.type} · {c.source_name ?? "unknown source"} · {formatRelative(c.updated_at)}
                        </p>
                      </div>
                      <Menu>
                        <MenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${c.name}`}>
                            <MoreHorizontal />
                          </Button>
                        </MenuTrigger>
                        <MenuContent>
                          <MenuItem asChild>
                            <Link href={`/charts/${c.id}`}>
                              <Pencil /> Edit
                            </Link>
                          </MenuItem>
                          <MenuItem danger onSelect={() => setToDelete(c)}>
                            <Trash2 /> Delete
                          </MenuItem>
                        </MenuContent>
                      </Menu>
                    </div>
                    <div className="min-h-0 flex-1 p-3">
                      <SavedChartBody chart={c} />
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Delete chart?"
        description={`“${toDelete?.name}” will be removed from every dashboard that uses it.`}
        confirmLabel="Delete"
        onConfirm={remove}
        loading={busy}
      />
    </>
  );
}
