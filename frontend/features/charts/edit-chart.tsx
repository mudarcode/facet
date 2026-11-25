"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/page-header";
import { ErrorBanner, Spinner } from "@/components/ui/feedback";
import { buttonClasses } from "@/components/ui/button";
import { api } from "@/lib/api";
import { ChartBuilder } from "./chart-builder";

export function EditChart({ id }: { id: string }) {
  const chart = useQuery({ queryKey: ["charts", id], queryFn: () => api.chart(id) });
  if (chart.error)
    return (
      <>
        <PageHeader title="Chart" />
        <div className="p-5">
          <ErrorBanner
            message={(chart.error as Error).message}
            action={
              <Link href="/charts" className={buttonClasses({ size: "sm" })}>
                All charts
              </Link>
            }
          />
        </div>
      </>
    );
  if (!chart.data)
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  // Keyed so that a refetch of a different chart remounts the builder with fresh state.
  return <ChartBuilder key={chart.data.id} chart={chart.data} />;
}
