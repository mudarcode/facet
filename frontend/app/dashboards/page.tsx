import type { Metadata } from "next";
import { DashboardList } from "@/features/dashboards/dashboard-list";

export const metadata: Metadata = { title: "Dashboards" };

export default function Page() {
  return <DashboardList />;
}
