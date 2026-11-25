"use client";
import { useState } from "react";
import { Search, Upload } from "lucide-react";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { DatasetList } from "@/features/datasets/dataset-list";
import { UploadDialog } from "@/features/datasets/upload-dialog";

export default function DatasetsPage() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  return (
    <>
      <PageHeader
        title="Datasets"
        description="Imported files, stored as Parquet and queryable with SQL"
        actions={
          <Button variant="primary" onClick={() => setOpen(true)} data-testid="open-upload">
            <Upload /> Import dataset
          </Button>
        }
      />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-3 p-5">
          <div className="relative max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-subtle" />
            <Input className="pl-8" placeholder="Search datasets" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search datasets" />
          </div>
          <Card>
            <DatasetList onUpload={() => setOpen(true)} filter={q} />
          </Card>
        </div>
      </div>
      <UploadDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
