"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { ErrorBanner } from "@/components/ui/feedback";
import { TypeIcon } from "@/components/type-icon";
import { api, ApiError } from "@/lib/api";
import type { Dataset } from "@/lib/types";

const TYPES = ["BOOLEAN", "BIGINT", "INTEGER", "DOUBLE", "DECIMAL(18,4)", "VARCHAR", "DATE", "TIMESTAMP"];

export function SchemaTab({ dataset }: { dataset: Dataset }) {
  const qc = useQueryClient();
  const v = dataset.current_version;
  const columns = v?.columns ?? [];
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = Object.entries(overrides).filter(([n, t]) => columns.find((c) => c.name === n)?.type !== t);
  const castFailures = v?.ingest_report.cast_failures ?? {};

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const previous = v?.ingest_options.type_overrides ?? {};
      await api.reprocess(dataset.id, {
        ...v?.ingest_options,
        type_overrides: { ...previous, ...Object.fromEntries(changed) },
      });
      toast.success("Re-importing with corrected types");
      setOverrides({});
      qc.invalidateQueries({ queryKey: ["datasets"] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to start re-import");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {columns.length} columns <span className="font-normal text-muted">· types inferred by DuckDB&apos;s CSV sniffer</span>
        </CardTitle>
        <div className="flex gap-2">
          {changed.length ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setOverrides({})}>
                <RotateCcw /> Reset
              </Button>
              <Button size="sm" variant="primary" onClick={apply} loading={busy}>
                <Wand2 /> Re-import with {changed.length} change{changed.length > 1 ? "s" : ""}
              </Button>
            </>
          ) : null}
        </div>
      </CardHeader>
      {error ? <ErrorBanner className="m-4" message={error} /> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]" aria-label="Schema">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="w-12 px-4 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Column</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="w-56 px-3 py-2 font-medium">Correct type</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((c, i) => {
              const val = overrides[c.name] ?? c.type;
              const failed = castFailures[c.name];
              return (
                <tr key={c.name} className="border-b border-border last:border-0">
                  <td className="tabular px-4 py-2 text-subtle">{i + 1}</td>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2 font-medium">
                      <TypeIcon type={c.type} /> {c.name}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs">{c.type}</code>
                    {v?.ingest_report.type_overrides?.[c.name] ? (
                      <Badge tone="accent" className="ml-2">
                        corrected
                      </Badge>
                    ) : null}
                    {failed ? (
                      <Badge tone="warning" className="ml-2">
                        {failed} value{failed > 1 ? "s" : ""} not convertible → NULL
                      </Badge>
                    ) : null}
                  </td>
                  <td className="px-3 py-1.5">
                    <NativeSelect
                      aria-label={`Type for ${c.name}`}
                      value={TYPES.includes(val) ? val : ""}
                      onChange={(e) => setOverrides({ ...overrides, [c.name]: e.target.value || c.type })}
                      className="h-7 text-xs"
                    >
                      {!TYPES.includes(c.type) ? <option value="">{c.type} (keep)</option> : null}
                      {TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </NativeSelect>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
