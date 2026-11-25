"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, SquareTerminal, Upload } from "lucide-react";
import { PageHeader } from "@/components/shell/page-header";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { DatasetList } from "@/features/datasets/dataset-list";
import { UploadDialog } from "@/features/datasets/upload-dialog";
import { useDatasets } from "@/features/datasets/hooks";
import { formatBytes, formatCompact } from "@/lib/format";

export function HomeView() {
  const [uploadOpen, setUploadOpen] = useState(false);
  const { data } = useDatasets();
  const ready = data?.items.filter((d) => d.status === "ready") ?? [];
  const rows = ready.reduce((a, d) => a + (d.row_count ?? 0), 0);
  const bytes = ready.reduce((a, d) => a + (d.processed_bytes ?? 0), 0);

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
            <Stat label="Datasets" value={formatCompact(data?.total ?? null)} />
            <Stat label="Rows stored" value={formatCompact(rows)} />
            <Stat label="Columnar storage" value={formatBytes(bytes)} />
            <Stat label="Engine" value="DuckDB" sub="in-process, vectorised" />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Dataset library</CardTitle>
              <Link href="/datasets" className="flex items-center gap-1 text-xs font-medium text-muted hover:text-accent">
                View all <ArrowRight className="size-3" />
              </Link>
            </CardHeader>
            <DatasetList onUpload={() => setUploadOpen(true)} limit={8} />
          </Card>
        </div>
      </div>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold tracking-tight">{value}</p>
      {sub ? <p className="text-[11px] text-subtle">{sub}</p> : null}
    </Card>
  );
}
