"use client";
import type { Dataset } from "@/lib/types";

export function TransformTab({ dataset }: { dataset: Dataset }) {
  return <p className="text-[13px] text-muted">Transform for {dataset.name} is not implemented yet.</p>;
}
