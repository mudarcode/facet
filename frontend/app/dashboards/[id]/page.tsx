import { DashboardView } from "@/features/dashboards/dashboard-view";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DashboardView id={id} />;
}
