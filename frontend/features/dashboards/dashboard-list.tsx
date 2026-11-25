"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { Input, Label } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { formatRelative } from "@/lib/format";

export function DashboardList() {
  const router = useRouter();
  const dashboards = useQuery({ queryKey: ["dashboards"], queryFn: api.dashboards });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const d = await api.createDashboard({ name: name.trim(), description: description.trim() });
      router.push(`/dashboards/${d.id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not create dashboard");
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Dashboards"
        description="Arrange saved charts on a grid with shared filters"
        actions={
          <Button variant="primary" onClick={() => setOpen(true)} data-testid="new-dashboard">
            <Plus /> New dashboard
          </Button>
        }
      />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl p-5">
          {dashboards.error ? <ErrorBanner message={(dashboards.error as Error).message} /> : null}
          {dashboards.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-28" />
              ))}
            </div>
          ) : dashboards.data?.items.length === 0 ? (
            <Card>
              <EmptyState
                icon={<LayoutDashboard />}
                title="No dashboards yet"
                description="Combine charts into a dashboard with a persistent layout, shared filters and one-click refresh."
                action={
                  <Button variant="primary" onClick={() => setOpen(true)}>
                    <Plus /> New dashboard
                  </Button>
                }
              />
            </Card>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="dashboard-list">
              {dashboards.data?.items.map((d) => (
                <li key={d.id}>
                  <Link href={`/dashboards/${d.id}`} className="block h-full">
                    <Card className="h-full p-4 transition-colors hover:border-border-strong">
                      <div className="flex items-center gap-2">
                        <LayoutDashboard className="size-4 text-accent" />
                        <span className="truncate text-sm font-medium">{d.name}</span>
                      </div>
                      {d.description ? <p className="mt-1 line-clamp-2 text-xs text-muted">{d.description}</p> : null}
                      <p className="mt-3 text-xs text-subtle">
                        {d.layout.length} {d.layout.length === 1 ? "chart" : "charts"}
                        {d.filters.length ? ` · ${d.filters.length} filter${d.filters.length === 1 ? "" : "s"}` : ""} · updated {formatRelative(d.updated_at)}
                      </p>
                    </Card>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="New dashboard"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={create} loading={busy} disabled={!name.trim()} data-testid="create-dashboard">
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="new-dash-name">Name</Label>
            <Input id="new-dash-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus data-testid="dashboard-name" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-dash-desc">Description (optional)</Label>
            <Input id="new-dash-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
        </div>
      </Dialog>
    </>
  );
}
