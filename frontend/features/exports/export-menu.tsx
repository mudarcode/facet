"use client";
import { useState } from "react";
import { ChevronDown, Download, FileSpreadsheet, FileArchive } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { absoluteUrl, api } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/format";
import type { ExportRecord, ExportSource } from "@/lib/types";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Queue an export job, wait for it, then hand the signed link to the browser's downloader. */
export async function runExport(source: ExportSource, format: "csv" | "parquet"): Promise<ExportRecord> {
  let rec = await api.createExport(source, format);
  const started = Date.now();
  while (rec.status === "queued" || rec.status === "running") {
    if (Date.now() - started > 15 * 60_000) throw new Error("Export is taking too long; check back later.");
    await sleep(Date.now() - started < 5000 ? 500 : 1500);
    rec = await api.getExport(rec.id);
  }
  if (rec.status === "failed" || !rec.download_url) throw new Error(rec.error ?? "Export failed.");
  const a = document.createElement("a");
  a.href = absoluteUrl(rec.download_url);
  a.download = rec.filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  return rec;
}

export function ExportMenu({ source, size = "md", label = "Export" }: { source: ExportSource; size?: "sm" | "md"; label?: string }) {
  const [busy, setBusy] = useState(false);

  const go = async (format: "csv" | "parquet") => {
    setBusy(true);
    const id = toast.loading(`Preparing ${format.toUpperCase()} export…`);
    try {
      const rec = await runExport(source, format);
      toast.success(`Exported ${formatNumber(rec.row_count)} rows`, {
        id,
        description: `${rec.filename} · ${formatBytes(rec.bytes)}`,
      });
    } catch (e) {
      toast.error((e as Error).message, { id });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Menu>
      <MenuTrigger asChild>
        <Button variant="outline" size={size} loading={busy} data-testid="export-menu">
          {busy ? null : <Download />} {label} <ChevronDown className="opacity-60" />
        </Button>
      </MenuTrigger>
      <MenuContent>
        <MenuItem onSelect={() => go("csv")} data-testid="export-csv">
          <FileSpreadsheet /> CSV
          <span className="ml-auto pl-4 text-[11px] text-subtle">spreadsheet-safe</span>
        </MenuItem>
        <MenuItem onSelect={() => go("parquet")} data-testid="export-parquet">
          <FileArchive /> Parquet
          <span className="ml-auto pl-4 text-[11px] text-subtle">typed, compressed</span>
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
