import { EditChart } from "@/features/charts/edit-chart";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EditChart id={id} />;
}
