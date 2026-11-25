"use client";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatBytes, formatNumber, formatRelative } from "@/lib/format";
import type { Dataset } from "@/lib/types";

export function OverviewTab({ dataset: ds }: { dataset: Dataset }) {
  const v = ds.current_version;
  const versions = useQuery({ queryKey: ["datasets", ds.id, "versions"], queryFn: () => api.versions(ds.id) });
  const report = v?.ingest_report;
  const compression = v?.raw_bytes && v.processed_bytes ? v.raw_bytes / v.processed_bytes : null;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="Rows" value={formatNumber(ds.row_count)} />
          <Metric label="Columns" value={formatNumber(ds.column_count)} />
          <Metric label="Original size" value={formatBytes(v?.raw_bytes)} />
          <Metric label="Parquet size" value={formatBytes(v?.processed_bytes)} hint={compression ? `${compression.toFixed(1)}× smaller` : undefined} />
        </div>
        {ds.description ? (
          <Card className="p-4 text-[13px] whitespace-pre-wrap text-muted">{ds.description}</Card>
        ) : null}
        {report && (report.warnings?.length || report.rejected_rows) ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="size-3.5 text-warning" /> Import report
              </CardTitle>
            </CardHeader>
            <div className="space-y-3 p-4 text-[13px]">
              <ul className="list-disc space-y-1 pl-4">
                {report.warnings?.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
              {report.reject_samples?.length ? (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted">Skipped rows (first {report.reject_samples.length})</p>
                  <div className="overflow-hidden rounded-md border border-border">
                    <table className="w-full text-xs">
                      <tbody>
                        {report.reject_samples.map((r, i) => (
                          <tr key={i} className="border-b border-border last:border-0">
                            <td className="tabular w-20 bg-surface-2 px-2 py-1.5 font-mono text-muted">line {r.line}</td>
                            <td className="px-2 py-1.5">
                              <Badge tone="warning">{r.type}</Badge> <span className="text-muted">{r.message}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </div>
          </Card>
        ) : null}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <dl className="divide-y divide-border text-[13px]">
          <Row k="Source file" v={v?.original_filename ?? "—"} />
          <Row k="Format" v={v?.source_format?.toUpperCase() ?? "—"} />
          <Row k="Encoding" v={report?.encoding ?? "—"} />
          <Row k="Version" v={v ? `v${v.version}` : "—"} />
          <Row k="Import time" v={report?.duration_s !== undefined ? `${report.duration_s.toFixed(2)} s` : "—"} />
          <Row k="Created" v={formatRelative(ds.created_at)} />
          <Row k="SQL name" v={<code className="font-mono text-xs">{ds.sql_name}</code>} />
        </dl>
        {versions.data && versions.data.length > 1 ? (
          <div className="border-t border-border p-4">
            <p className="mb-2 text-xs font-medium text-muted">Versions</p>
            <ul className="space-y-1.5 text-xs">
              {versions.data.map((ver) => (
                <li key={ver.id} className="flex items-center justify-between">
                  <span>
                    v{ver.version} {ver.id === v?.id ? <Badge tone="accent">current</Badge> : null}
                  </span>
                  <span className="text-muted">
                    {ver.status === "ready" ? `${formatNumber(ver.row_count)} rows` : ver.status} · {formatRelative(ver.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="tabular mt-1 text-lg font-semibold tracking-tight">{value}</p>
      {hint ? <p className="text-[11px] text-success">{hint}</p> : null}
    </Card>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2">
      <dt className="text-muted">{k}</dt>
      <dd className="truncate text-right">{v}</dd>
    </div>
  );
}
