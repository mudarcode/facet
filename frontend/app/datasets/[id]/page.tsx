import { Suspense } from "react";
import { DatasetDetail } from "@/features/datasets/detail/dataset-detail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <DatasetDetail id={id} />
    </Suspense>
  );
}
