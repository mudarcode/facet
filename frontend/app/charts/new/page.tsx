import type { Metadata } from "next";
import { ChartBuilder } from "@/features/charts/chart-builder";

export const metadata: Metadata = { title: "New chart" };

export default async function Page({ searchParams }: { searchParams: Promise<{ dataset?: string; query?: string }> }) {
  const sp = await searchParams;
  const initial = sp.dataset ? { dataset_id: sp.dataset } : sp.query ? { saved_query_id: sp.query } : undefined;
  return <ChartBuilder initialSource={initial} />;
}
