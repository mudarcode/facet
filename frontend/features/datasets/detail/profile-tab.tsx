"use client";
import type { Dataset } from "@/lib/types";

export function ProfileTab({ dataset }: { dataset: Dataset }) {
  return <p className="text-[13px] text-muted">Profile for {dataset.name} is not implemented yet.</p>;
}
