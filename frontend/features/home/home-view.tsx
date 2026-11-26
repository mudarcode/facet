"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Database,
  FileCode2,
  LayoutDashboard,
  Plus,
  SquareTerminal,
  Upload,
  Wand2,
  Download,
  Trash2,
} from "lucide-react";
import { PageHeader } from "@/components/shell/page-header";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { DatasetList } from "@/features/datasets/dataset-list";
import { UploadDialog } from "@/features/datasets/upload-dialog";
import { useDatasets } from "@/features/datasets/hooks";
import { api } from "@/lib/api";
import { formatBytes, formatCompact, formatRelative } from "@/lib/format";
import type { ActivityEvent } from "@/lib/types";

const ICONS: Record<string, typeof Activity> = {
  dataset: Database,
  query: FileCode2,
  chart: BarChart3,
  dashboard: LayoutDashboard,
  transformation: Wand2,
  export: Download,
};

function eventHref(e: ActivityEvent): string | null {
  if (!e.subject_id || e.kind.endsWith(".deleted")) return null;
  switch (e.subject_type) {
    case "dataset":
      return `/datasets/${e.subject_id}`;
    case "chart":
      return `/charts/${e.subject_id}`;
    case "dashboard":
      return `/dashboards/${e.subject_id}`;
    case "query":
      return `/sql?saved=${e.subject_id}`;
    default:
      return null;
  }
}

export function HomeView() {
  const [uploadOpen, setUploadOpen] = useState(false);
  const { data } = useDatasets();
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const activity = useQuery({ queryKey: ["activity"], queryFn: () => api.activity(12), refetchInterval: 15_000 });
  const dashboards = useQuery({ queryKey: ["dashboards"], queryFn: api.dashboards });
  const saved = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.savedQueries() });
  const ready = data?.items.filter((d) => d.status === "ready") ?? [];
  const rows = ready.reduce((a, d) => a + (d.row_count ?? 0), 0);
  const bytes = ready.reduce((a, d) => a + (d.processed_bytes ?? 0), 0);
  const s = summary.data;

  return (
    <>
      <PageHeader
        title="Workspace"
        description="Your datasets, queries and dashboards"
        actions={
          <>
            <Link href="/sql" className={buttonClasses({ variant: "outline" })}>
              <SquareTerminal /> New query
            </Link>
            <Button variant="primary" onClick={() => setUploadOpen(true)} data-testid="open-upload">
              <Upload /> Import dataset
            </Button>
          </>
        }
      />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-5 p-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Datasets" value={formatCompact(s?.datasets ?? data?.total ?? null)} sub={`${formatCompact(rows)} rows · ${formatBytes(bytes)} Parquet`} />
            <Stat label="Saved queries" value={formatCompact(s?.saved_queries ?? null)} href="/sql" />
            <Stat label="Charts" value={formatCompact(s?.charts ?? null)} href="/charts" />
            <Stat label="Dashboards" value={formatCompact(s?.dashboards ?? null)} href="/dashboards" />
          </div>

          <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
            <Card>
              <CardHeader>
                <CardTitle>Dataset library</CardTitle>
                <Link href="/datasets" className="flex items-center gap-1 text-xs font-medium text-muted hover:text-accent">
                  View all <ArrowRight className="size-3" />
                </Link>
              </CardHeader>
              <DatasetList onUpload={() => setUploadOpen(true)} limit={8} />
            </Card>

            <Card className="self-start">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="size-4 text-muted" /> Recent activity
                </CardTitle>
              </CardHeader>
              <div className="px-2 pb-2" data-testid="activity-feed">
                {activity.isLoading ? (
                  <div className="space-y-2 p-2">
                    {[0, 1, 2, 3].map((i) => (
                      <Skeleton key={i} className="h-8" />
                    ))}
                  </div>
                ) : activity.data?.length ? (
                  <ul>
                    {activity.data.map((e) => {
                      const Icon = e.kind.endsWith(".deleted") ? Trash2 : (ICONS[e.subject_type] ?? Activity);
                      const href = eventHref(e);
                      const body = (
                        <>
                          <Icon className="mt-0.5 size-3.5 shrink-0 text-subtle" />
                          <span className="min-w-0 flex-1 text-[13px] leading-snug">{e.summary}</span>
                          <time className="shrink-0 text-[11px] text-subtle" dateTime={e.created_at}>
                            {formatRelative(e.created_at)}
                          </time>
                        </>
                      );
                      return (
                        <li key={e.id}>
                          {href ? (
                            <Link href={href} className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-surface-2">
                              {body}
                            </Link>
                          ) : (
                            <div className="flex items-start gap-2 px-2 py-1.5">{body}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="px-2 py-4 text-center text-xs text-subtle">Nothing yet. Import a file to get started.</p>
                )}
              </div>
            </Card>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <ShortList
              title="Dashboards"
              icon={LayoutDashboard}
              href="/dashboards"
              empty="No dashboards yet"
              newHref="/dashboards"
              items={dashboards.data?.items.slice(0, 5).map((d) => ({
                id: d.id,
                href: `/dashboards/${d.id}`,
                name: d.name,
                meta: `${d.layout.length} charts · ${formatRelative(d.updated_at)}`,
              }))}
            />
            <ShortList
              title="Saved queries"
              icon={FileCode2}
              href="/sql"
              empty="No saved queries yet"
              newHref="/sql"
              items={saved.data?.items.slice(0, 5).map((q) => ({
                id: q.id,
                href: `/sql?saved=${q.id}`,
                name: q.name,
                meta: formatRelative(q.updated_at),
              }))}
            />
          </div>
        </div>
      </div>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    </>
  );
}

function ShortList({
  title,
  icon: Icon,
  href,
  items,
  empty,
  newHref,
}: {
  title: string;
  icon: typeof Activity;
  href: string;
  items?: { id: string; href: string; name: string; meta: string }[];
  empty: string;
  newHref: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Icon className="size-4 text-muted" /> {title}
        </CardTitle>
        <Link href={href} className="flex items-center gap-1 text-xs font-medium text-muted hover:text-accent">
          View all <ArrowRight className="size-3" />
        </Link>
      </CardHeader>
      <div className="px-2 pb-2">
        {!items ? (
          <Skeleton className="m-2 h-20" />
        ) : items.length ? (
          <ul>
            {items.map((it) => (
              <li key={it.id}>
                <Link href={it.href} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-surface-2">
                  <span className="truncate text-[13px] font-medium">{it.name}</span>
                  <span className="shrink-0 text-[11px] text-subtle">{it.meta}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex items-center justify-between px-2 py-3 text-xs text-subtle">
            {empty}
            <Link href={newHref} className="flex items-center gap-1 font-medium text-accent hover:underline">
              <Plus className="size-3" /> Create
            </Link>
          </div>
        )}
      </div>
    </Card>
  );
}

function Stat({ label, value, sub, href }: { label: string; value: string; sub?: string; href?: string }) {
  const inner = (
    <>
      <p className="text-xs text-muted">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold tracking-tight">{value}</p>
      {sub ? <p className="truncate text-[11px] text-subtle">{sub}</p> : null}
    </>
  );
  return href ? (
    <Link href={href} className="block">
      <Card className="h-full px-4 py-3 transition-colors hover:border-border-strong">{inner}</Card>
    </Link>
  ) : (
    <Card className="h-full px-4 py-3">{inner}</Card>
  );
}
