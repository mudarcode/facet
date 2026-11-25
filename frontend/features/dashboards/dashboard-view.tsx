"use client";
import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactGridLayout, { useContainerWidth, verticalCompactor, type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { BarChart3, Check, GripVertical, LayoutDashboard, MoreHorizontal, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorBanner, Spinner } from "@/components/ui/feedback";
import { Input, Label } from "@/components/ui/input";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { api, ApiError } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Chart, ColumnSchema, Condition, Dashboard, LayoutItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SavedChartBody } from "@/features/charts/chart-card";
import { completeConditions, ConditionsEditor } from "@/features/charts/conditions-editor";
import { ExportMenu } from "@/features/exports/export-menu";

const COLS = 12;
const ROW_H = 44;

function nextPosition(layout: LayoutItem[], w: number): { x: number; y: number } {
  const bottom = layout.reduce((m, i) => Math.max(m, i.y + i.h), 0);
  // Fill the last row if there's room, otherwise start a new one.
  const lastRow = layout.filter((i) => i.y + i.h === bottom);
  const used = lastRow.reduce((m, i) => Math.max(m, i.x + i.w), 0);
  if (lastRow.length && used + w <= COLS) return { x: used, y: Math.max(...lastRow.map((i) => i.y)) };
  return { x: 0, y: bottom };
}

export function DashboardView({ id }: { id: string }) {
  const dash = useQuery({ queryKey: ["dashboards", id], queryFn: () => api.dashboard(id) });
  if (dash.error)
    return (
      <>
        <PageHeader title="Dashboard" />
        <div className="p-5">
          <ErrorBanner
            message={(dash.error as Error).message}
            action={
              <Link href="/dashboards" className={buttonClasses({ size: "sm" })}>
                All dashboards
              </Link>
            }
          />
        </div>
      </>
    );
  if (!dash.data)
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  return <DashboardEditor key={dash.data.id} dashboard={dash.data} />;
}

function DashboardEditor({ dashboard }: { dashboard: Dashboard }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [layout, setLayout] = useState<LayoutItem[]>(dashboard.layout);
  const [filters, setFilters] = useState<Condition[]>(dashboard.filters);
  const [name, setName] = useState(dashboard.name);
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshedAt, setRefreshedAt] = useState(() => new Date().toISOString());
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { width, containerRef, mounted } = useContainerWidth({ initialWidth: 1200 });

  const charts = useQuery({ queryKey: ["charts"], queryFn: api.charts });
  const byId = useMemo(() => new Map((charts.data ?? []).map((c) => [c.id, c])), [charts.data]);

  // Filter columns: the union of the fields of every source used on the dashboard.
  const sources = useMemo(() => {
    const seen = new Map<string, { dataset_id?: string | null; saved_query_id?: string | null }>();
    for (const item of layout) {
      const c = byId.get(item.chart_id);
      if (c) seen.set(c.dataset_id ? `d:${c.dataset_id}` : `q:${c.saved_query_id}`, { dataset_id: c.dataset_id, saved_query_id: c.saved_query_id });
    }
    return [...seen.entries()];
  }, [layout, byId]);
  const colQueries = useQueries({
    queries: sources.map(([key, src]) => ({ queryKey: ["source-columns", key], queryFn: () => api.sourceColumns(src), staleTime: 60_000 })),
  });
  const filterColumns = useMemo(() => {
    const m = new Map<string, ColumnSchema>();
    for (const q of colQueries) for (const c of q.data?.columns ?? []) if (!m.has(c.name)) m.set(c.name, c);
    return [...m.values()];
  }, [colQueries]);

  const persist = (patch: Partial<Pick<Dashboard, "layout" | "filters" | "name">>) =>
    api
      .updateDashboard(dashboard.id, patch)
      .then((d) => qc.setQueryData(["dashboards", dashboard.id], d))
      .catch((e: unknown) => toast.error(e instanceof ApiError ? e.message : "Could not save dashboard"));

  const commitLayout = (next: LayoutItem[]) => {
    setLayout(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void persist({ layout: next }), 400);
  };

  const onLayoutChange = (l: Layout) => {
    if (!editing) return;
    const pos = new Map(l.map((g) => [g.i, g]));
    const next = layout.map((it) => {
      const g = pos.get(it.i);
      return g ? { ...it, x: g.x, y: g.y, w: g.w, h: g.h } : it;
    });
    const changed = next.some((n, idx) => {
      const o = layout[idx]!;
      return n.x !== o.x || n.y !== o.y || n.w !== o.w || n.h !== o.h;
    });
    if (changed) commitLayout(next);
  };

  const addChart = (c: Chart) => {
    const w = c.spec.type === "stat" ? 4 : 6;
    const h = c.spec.type === "stat" ? 3 : 7;
    const item: LayoutItem = { i: crypto.randomUUID().slice(0, 8), chart_id: c.id, w, h, ...nextPosition(layout, w) };
    commitLayout([...layout, item]);
    toast.success(`Added “${c.name}”`);
  };

  const applyFilters = (next: Condition[]) => {
    setFilters(next);
    void persist({ filters: completeConditions(next) });
  };

  const refresh = () => {
    setRefreshKey((k) => k + 1);
    setRefreshedAt(new Date().toISOString());
    qc.invalidateQueries({ queryKey: ["charts"] });
  };

  const activeFilters = useMemo(() => completeConditions(filters), [filters]);
  const narrow = mounted && width < 640;

  const items = layout.map((item) => {
    const c = byId.get(item.chart_id);
    return (
      <div key={item.i} className="h-full" data-testid="dashboard-tile">
        <Card className={cn("flex h-full flex-col overflow-hidden", editing && "ring-1 ring-accent/30")}>
          <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
            {editing ? (
              <span className="drag-handle -ml-1 cursor-grab text-subtle active:cursor-grabbing" aria-label="Drag to move">
                <GripVertical className="size-4" />
              </span>
            ) : null}
            {c ? (
              <Link href={`/charts/${c.id}`} className="min-w-0 flex-1 truncate text-[13px] font-medium hover:text-accent">
                {c.spec.options?.title || c.name}
              </Link>
            ) : (
              <span className="flex-1 text-[13px] text-muted">Loading…</span>
            )}
            {editing ? (
              <Button variant="ghost" size="icon-sm" aria-label="Remove from dashboard" onClick={() => commitLayout(layout.filter((x) => x.i !== item.i))}>
                <X />
              </Button>
            ) : c ? (
              <ExportMenu source={{ kind: "chart", chart_id: c.id }} size="sm" label="" />
            ) : null}
          </div>
          <div className="min-h-0 flex-1 p-3">{c ? <SavedChartBody chart={c} filters={activeFilters} refreshKey={refreshKey} /> : null}</div>
        </Card>
      </div>
    );
  });

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link href="/dashboards" className="hover:text-fg">
            Dashboards
          </Link>
        }
        title={name}
        description={dashboard.description || `Refreshed ${formatRelative(refreshedAt)}`}
        actions={
          <>
            <Button variant="outline" onClick={refresh} data-testid="refresh-dashboard">
              <RefreshCw /> Refresh
            </Button>
            <Button variant="outline" onClick={() => setAdding(true)} data-testid="add-tile">
              <Plus /> Add chart
            </Button>
            <Button variant={editing ? "primary" : "outline"} onClick={() => setEditing((e) => !e)} data-testid="edit-layout">
              {editing ? (
                <>
                  <Check /> Done
                </>
              ) : (
                <>
                  <Pencil /> Edit layout
                </>
              )}
            </Button>
            <Menu>
              <MenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Dashboard actions">
                  <MoreHorizontal />
                </Button>
              </MenuTrigger>
              <MenuContent>
                <MenuItem onSelect={() => setRenaming(true)}>
                  <Pencil /> Rename
                </MenuItem>
                <MenuItem danger onSelect={() => setDeleting(true)}>
                  <Trash2 /> Delete dashboard
                </MenuItem>
              </MenuContent>
            </Menu>
          </>
        }
      />
      <div className="border-b border-border bg-surface px-5 py-2" data-testid="dashboard-filters">
        <div className="flex flex-wrap items-start gap-3">
          <span className="pt-1.5 text-xs font-medium text-muted">Filters</span>
          <div className="min-w-0 flex-1">
            <ConditionsEditor compact columns={filterColumns} value={filters} onChange={applyFilters} addLabel="Add dashboard filter" />
          </div>
        </div>
        {activeFilters.length ? <p className="mt-1 text-[11px] text-subtle">Applied to every chart whose data has the filtered field.</p> : null}
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div ref={containerRef} className="mx-auto max-w-[1400px] p-3">
          {layout.length === 0 ? (
            <Card className="m-2">
              <EmptyState
                icon={<LayoutDashboard />}
                title="This dashboard is empty"
                description="Add saved charts, then drag and resize them. The layout is saved automatically."
                action={
                  <Button variant="primary" onClick={() => setAdding(true)}>
                    <Plus /> Add chart
                  </Button>
                }
              />
            </Card>
          ) : narrow ? (
            <div className="space-y-3">
              {[...layout]
                .sort((a, b) => a.y - b.y || a.x - b.x)
                .map((item) => (
                  <div key={item.i} style={{ height: Math.max(220, item.h * ROW_H) }}>
                    {items.find((el) => el.key === item.i)}
                  </div>
                ))}
            </div>
          ) : mounted ? (
            <ReactGridLayout
              width={width - 24}
              layout={layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h, minW: 2, minH: 3 }))}
              gridConfig={{ cols: COLS, rowHeight: ROW_H, margin: [12, 12] }}
              dragConfig={{ enabled: editing, handle: ".drag-handle" }}
              resizeConfig={{ enabled: editing }}
              compactor={verticalCompactor}
              onLayoutChange={onLayoutChange}
            >
              {items}
            </ReactGridLayout>
          ) : null}
        </div>
      </div>

      <AddChartDialog open={adding} onOpenChange={setAdding} charts={charts.data ?? []} loading={charts.isLoading} onAdd={addChart} />
      <RenameDialog
        open={renaming}
        onOpenChange={setRenaming}
        initial={name}
        onSave={(n) => {
          setName(n);
          void persist({ name: n });
          qc.invalidateQueries({ queryKey: ["dashboards"] });
        }}
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Delete dashboard?"
        description="The dashboard is removed. Its charts are kept."
        confirmLabel="Delete"
        onConfirm={async () => {
          await api.deleteDashboard(dashboard.id);
          qc.invalidateQueries({ queryKey: ["dashboards"] });
          router.push("/dashboards");
        }}
      />
    </>
  );
}

function AddChartDialog({
  open,
  onOpenChange,
  charts,
  loading,
  onAdd,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  charts: Chart[];
  loading: boolean;
  onAdd: (c: Chart) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add a chart" description="Charts keep their own filters; dashboard filters narrow them further.">
      {loading ? (
        <Spinner />
      ) : charts.length === 0 ? (
        <EmptyState
          icon={<BarChart3 />}
          title="No saved charts"
          action={
            <Link href="/charts/new" className={buttonClasses({ variant: "primary" })}>
              <Plus /> New chart
            </Link>
          }
        />
      ) : (
        <ul className="scroll-thin max-h-80 space-y-1 overflow-y-auto" data-testid="add-chart-list">
          {charts.map((c) => (
            <li key={c.id}>
              <button
                className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-[13px] hover:bg-surface-2"
                onClick={() => {
                  onAdd(c);
                  onOpenChange(false);
                }}
              >
                <BarChart3 className="size-4 text-muted" />
                <span className="min-w-0 flex-1 truncate font-medium">{c.name}</span>
                <span className="text-xs text-subtle">
                  {c.spec.type} · {c.source_name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

function RenameDialog({ open, onOpenChange, initial, onSave }: { open: boolean; onOpenChange: (o: boolean) => void; initial: string; onSave: (n: string) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Rename dashboard">
      {open ? <RenameForm initial={initial} onCancel={() => onOpenChange(false)} onSave={(n) => (onSave(n), onOpenChange(false))} /> : null}
    </Dialog>
  );
}

function RenameForm({ initial, onSave, onCancel }: { initial: string; onSave: (n: string) => void; onCancel: () => void }) {
  const [v, setV] = useState(initial);
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (v.trim()) onSave(v.trim());
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="dash-name">Name</Label>
        <Input id="dash-name" value={v} onChange={(e) => setV(e.target.value)} autoFocus />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!v.trim()}>
          Save
        </Button>
      </div>
    </form>
  );
}
