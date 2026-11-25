"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { BarChart3, Columns3, Gauge, Info, Pencil, SquareTerminal, Table2, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorBanner, ProgressBar, Skeleton } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useDataset, useDeleteDataset, useJob } from "../hooks";
import { StatusBadge } from "../status-badge";
import { RenameDialog } from "../rename-dialog";
import { OverviewTab } from "./overview-tab";
import { SchemaTab } from "./schema-tab";
import { PreviewTab } from "./preview-tab";
import { ProfileTab } from "./profile-tab";
import { TransformTab } from "./transform-tab";

const TABS = ["overview", "schema", "preview", "profile", "transform"] as const;
type Tab = (typeof TABS)[number];

export function DatasetDetail({ id }: { id: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "overview") as Tab;
  const { data: ds, isLoading, error } = useDataset(id);
  const inFlight = ds?.status === "pending" || ds?.status === "processing";
  const job = useJob(ds?.latest_job_id, inFlight);
  const del = useDeleteDataset();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const setTab = (t: string) => router.replace(`/datasets/${id}?tab=${t}`, { scroll: false });

  if (isLoading)
    return (
      <div className="space-y-3 p-5">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40" />
      </div>
    );
  if (error || !ds)
    return (
      <EmptyState
        className="flex-1"
        title="Dataset not found"
        description={(error as Error | null)?.message ?? "It may have been deleted."}
        action={
          <Link href="/datasets" className={buttonClasses({ variant: "outline" })}>
            Back to datasets
          </Link>
        }
      />
    );

  const ready = ds.status === "ready";

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link href="/datasets" className="hover:text-fg">
            Datasets
          </Link>
        }
        title={
          <span className="flex items-center gap-2">
            {ds.name} <StatusBadge status={ds.status} />
          </span>
        }
        description={<span className="font-mono">{ds.sql_name}</span>}
        actions={
          <>
            <Button variant="ghost" size="icon" aria-label="Edit dataset" onClick={() => setRenaming(true)}>
              <Pencil />
            </Button>
            <Button variant="ghost" size="icon" aria-label="Delete dataset" onClick={() => setDeleting(true)}>
              <Trash2 />
            </Button>
            {ready ? (
              <>
                <Link href={`/charts/new?dataset=${ds.id}`} className={buttonClasses({ variant: "outline" })}>
                  <BarChart3 /> Chart
                </Link>
                <Link href={`/sql?dataset=${ds.sql_name}`} className={buttonClasses({ variant: "primary" })}>
                  <SquareTerminal /> Query
                </Link>
              </>
            ) : null}
          </>
        }
      />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl p-5">
          {inFlight ? (
            <Card className="mb-4 space-y-2 p-4" aria-live="polite">
              <div className="flex justify-between text-[13px]">
                <span className="font-medium">{job.data?.message || "Queued for processing"}</span>
                <span className="tabular text-muted">{Math.round((job.data?.progress ?? 0) * 100)}%</span>
              </div>
              <ProgressBar value={job.data?.progress ?? 0} indeterminate={!job.data || job.data.progress < 0.05} />
            </Card>
          ) : null}
          {ds.status === "failed" ? <ErrorBanner className="mb-4" title="Import failed" message={ds.error ?? "Unknown error"} /> : null}
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="overview">
                <Info /> Overview
              </TabsTrigger>
              <TabsTrigger value="schema" disabled={!ready}>
                <Columns3 /> Schema
              </TabsTrigger>
              <TabsTrigger value="preview" disabled={!ready}>
                <Table2 /> Preview
              </TabsTrigger>
              <TabsTrigger value="profile" disabled={!ready}>
                <Gauge /> Profile
              </TabsTrigger>
              <TabsTrigger value="transform" disabled={!ready}>
                <Wand2 /> Transform
              </TabsTrigger>
            </TabsList>
            <div className="pt-4">
              <TabsContent value="overview">
                <OverviewTab dataset={ds} />
              </TabsContent>
              {ready ? (
                <>
                  <TabsContent value="schema">
                    <SchemaTab dataset={ds} />
                  </TabsContent>
                  <TabsContent value="preview">
                    <PreviewTab dataset={ds} />
                  </TabsContent>
                  <TabsContent value="profile">
                    <ProfileTab dataset={ds} />
                  </TabsContent>
                  <TabsContent value="transform">
                    <TransformTab dataset={ds} />
                  </TabsContent>
                </>
              ) : null}
            </div>
          </Tabs>
        </div>
      </div>
      <RenameDialog dataset={renaming ? ds : null} onClose={() => setRenaming(false)} />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${ds.name}?`}
        description="The original file, processed data and any charts or transformations built on it will be permanently removed."
        confirmLabel="Delete dataset"
        loading={del.isPending}
        onConfirm={async () => {
          await del.mutateAsync(ds.id);
          toast.success(`Deleted ${ds.name}`);
          router.push("/datasets");
        }}
      />
    </>
  );
}
