"use client";
import type { QueryResult } from "@/lib/types";

// Saving and exporting arrive with saved queries and exports.
export function SqlToolbarExtras(_: { sql: string; savedQueryId: string | null; onSaved: (id: string) => void; lastResult: QueryResult | null; lastSql: string }) {
  return null;
}
