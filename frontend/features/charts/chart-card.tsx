"use client";
import { useQuery } from "@tanstack/react-query";
import { ErrorBanner, Skeleton } from "@/components/ui/feedback";
import { api, ApiError } from "@/lib/api";
import type { Chart, Condition } from "@/lib/types";
import { ChartView } from "./chart-view";

/** Live rendering of a saved chart (data aggregated server-side), optionally narrowed by filters. */
export function SavedChartBody({ chart, filters = [], refreshKey = 0 }: { chart: Chart; filters?: Condition[]; refreshKey?: number }) {
  const data = useQuery({
    queryKey: ["chart-data", chart.id, chart.updated_at, filters, refreshKey],
    queryFn: () => api.chartData(chart.id, filters),
    retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
    staleTime: 30_000,
  });
  if (data.error) return <ErrorBanner message={(data.error as Error).message} className="m-1" />;
  if (!data.data) return <Skeleton className="h-full w-full" />;
  return <ChartView data={data.data} spec={chart.spec} />;
}
