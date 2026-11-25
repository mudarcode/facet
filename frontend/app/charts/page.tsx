import type { Metadata } from "next";
import { ChartList } from "@/features/charts/chart-list";

export const metadata: Metadata = { title: "Charts" };

export default function Page() {
  return <ChartList />;
}
