"use client";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { DataTable, Pager } from "@/components/data-table";
import { ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import type { Dataset } from "@/lib/types";

const PAGE = 100;

export function PreviewTab({ dataset }: { dataset: Dataset }) {
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["datasets", dataset.id, "preview", dataset.current_version?.id, offset],
    queryFn: () => api.preview(dataset.id, offset, PAGE),
    placeholderData: keepPreviousData,
  });
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-xs text-muted">Rows in stored order</span>
        {q.data ? <Pager offset={offset} limit={PAGE} total={q.data.total_rows} onChange={setOffset} disabled={q.isFetching} /> : null}
      </div>
      {q.error ? <ErrorBanner className="m-4" message={(q.error as Error).message} /> : null}
      {q.isLoading ? (
        <div className="space-y-1.5 p-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-6" />
          ))}
        </div>
      ) : q.data ? (
        <DataTable columns={q.data.columns} rows={q.data.rows} rowOffset={offset} className="h-[560px]" aria-label="Dataset preview" />
      ) : null}
    </Card>
  );
}
