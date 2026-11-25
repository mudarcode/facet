import type { Metadata } from "next";
import { Suspense } from "react";
import { SqlWorkspace } from "@/features/sql/sql-workspace";

export const metadata: Metadata = { title: "SQL" };

export default function Page() {
  return (
    <Suspense>
      <SqlWorkspace />
    </Suspense>
  );
}
