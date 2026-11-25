"use client";
import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ChevronDown, FileUp, UploadCloud, X } from "lucide-react";
import { toast } from "sonner";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { ErrorBanner, ProgressBar } from "@/components/ui/feedback";
import { api, ApiError, uploadDataset, type UploadHandle } from "@/lib/api";
import type { IngestOptions, Job } from "@/lib/types";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

const ACCEPT = ".csv,.tsv,.txt,.parquet";

export function UploadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const handle = useRef<UploadHandle | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [drag, setDrag] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [opts, setOpts] = useState<IngestOptions>({ encoding: "auto" });
  const [phase, setPhase] = useState<"idle" | "uploading" | "processing">("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const cancelled = useRef(false);

  const reset = () => {
    setFile(null);
    setName("");
    setPhase("idle");
    setProgress(0);
    setError(null);
    setJob(null);
    setOpts({ encoding: "auto" });
  };

  const close = (o: boolean) => {
    if (!o) cancelled.current = true;
    if (!o && phase === "uploading") handle.current?.abort();
    if (!o) reset();
    onOpenChange(o);
  };

  const pick = useCallback((f: File | undefined) => {
    if (!f) return;
    setError(null);
    setFile(f);
    setName(f.name.replace(/\.[^.]+$/, ""));
  }, []);

  const isCsv = !!file && !file.name.toLowerCase().endsWith(".parquet");

  const start = async () => {
    if (!file) return;
    setError(null);
    cancelled.current = false;
    setPhase("uploading");
    const clean: IngestOptions = {};
    if (isCsv) {
      if (opts.delimiter) clean.delimiter = opts.delimiter === "\\t" ? "\t" : opts.delimiter;
      if (opts.header !== undefined && opts.header !== null) clean.header = opts.header;
      if (opts.encoding && opts.encoding !== "auto") clean.encoding = opts.encoding;
    }
    handle.current = uploadDataset(file, { name: name.trim() || undefined, options: clean }, setProgress);
    try {
      const res = await handle.current.promise;
      setPhase("processing");
      qc.invalidateQueries({ queryKey: ["datasets"] });
      const final = await pollJob(res.job_id, setJob, () => cancelled.current);
      if (final?.status === "succeeded") {
        toast.success(`${name.trim() || file.name} is ready`);
        qc.invalidateQueries({ queryKey: ["datasets"] });
        close(false);
        router.push(`/datasets/${res.dataset.id}`);
      }
    } catch (e) {
      setPhase("idle");
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    }
  };

  const j = job;
  const done = j?.status === "succeeded";
  const failed = j?.status === "failed";

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title="Import dataset"
      description="CSV, TSV or Parquet. Files are converted to columnar Parquet for fast queries."
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            {phase === "uploading" ? "Cancel upload" : "Close"}
          </Button>
          {phase === "idle" ? (
            <Button variant="primary" onClick={start} disabled={!file} data-testid="upload-submit">
              <UploadCloud /> Import
            </Button>
          ) : null}
        </>
      }
    >
      {phase === "idle" ? (
        <div className="space-y-4">
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              pick(e.dataTransfer.files[0]);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center transition-colors",
              drag ? "border-accent bg-accent-soft" : "border-border-strong hover:border-accent hover:bg-surface-2",
            )}
          >
            <FileUp className="mb-2 size-6 text-muted" />
            {file ? (
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium">{file.name}</span>
                <span className="text-xs text-muted">{formatBytes(file.size)}</span>
                <button
                  className="rounded p-0.5 text-subtle hover:text-fg"
                  aria-label="Remove file"
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                  }}
                >
                  <X className="size-3.5" />
                </button>
              </div>
            ) : (
              <>
                <p className="text-[13px] font-medium">Drop a file here or click to browse</p>
                <p className="mt-0.5 text-xs text-muted">.csv · .tsv · .parquet</p>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              data-testid="upload-input"
              aria-label="Choose file"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="ds-name">Dataset name</Label>
            <Input id="ds-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sales 2024" />
          </div>

          {isCsv ? (
            <div>
              <button className="flex items-center gap-1 text-xs font-medium text-muted hover:text-fg" onClick={() => setShowAdvanced((s) => !s)}>
                <ChevronDown className={cn("size-3.5 transition-transform", showAdvanced && "rotate-180")} /> CSV options
              </button>
              {showAdvanced ? (
                <div className="mt-3 grid grid-cols-3 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="opt-delim">Delimiter</Label>
                    <NativeSelect id="opt-delim" value={opts.delimiter ?? ""} onChange={(e) => setOpts({ ...opts, delimiter: e.target.value || null })}>
                      <option value="">Auto-detect</option>
                      <option value=",">Comma ,</option>
                      <option value=";">Semicolon ;</option>
                      <option value="\t">Tab</option>
                      <option value="|">Pipe |</option>
                    </NativeSelect>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="opt-header">Header row</Label>
                    <NativeSelect
                      id="opt-header"
                      value={opts.header === undefined || opts.header === null ? "" : String(opts.header)}
                      onChange={(e) => setOpts({ ...opts, header: e.target.value === "" ? null : e.target.value === "true" })}
                    >
                      <option value="">Auto-detect</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </NativeSelect>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="opt-enc">Encoding</Label>
                    <NativeSelect id="opt-enc" value={opts.encoding ?? "auto"} onChange={(e) => setOpts({ ...opts, encoding: e.target.value as IngestOptions["encoding"] })}>
                      <option value="auto">Auto (UTF-8 → Latin-1)</option>
                      <option value="utf-8">UTF-8</option>
                      <option value="utf-16">UTF-16</option>
                      <option value="latin-1">Latin-1</option>
                    </NativeSelect>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {error ? <ErrorBanner title="Import failed" message={error} /> : null}
        </div>
      ) : (
        <div className="space-y-4 py-2" aria-live="polite">
          <div className="flex items-center justify-between text-[13px]">
            <span className="font-medium">{file?.name}</span>
            <span className="text-muted">{formatBytes(file?.size)}</span>
          </div>
          <Step label="Upload" state={phase === "uploading" ? "active" : "done"} detail={phase === "uploading" ? `${Math.round(progress * 100)}%` : "Done"} />
          <ProgressBar value={phase === "uploading" ? progress : 1} />
          <Step
            label="Process"
            state={phase === "uploading" ? "waiting" : failed ? "failed" : done ? "done" : "active"}
            detail={phase === "uploading" ? "Waiting" : failed ? "Failed" : j ? `${j.message || j.status} · ${Math.round(j.progress * 100)}%` : "Queued"}
          />
          {phase === "processing" ? <ProgressBar value={j?.progress ?? 0} indeterminate={!j || (j.status === "running" && j.progress < 0.05)} /> : null}
          {failed ? (
            <ErrorBanner
              title="Processing failed"
              message={j?.error ?? "Unknown error"}
              action={
                <Button size="sm" variant="outline" onClick={reset}>
                  Try again
                </Button>
              }
            />
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

function Step({ label, state, detail }: { label: string; state: "waiting" | "active" | "done" | "failed"; detail: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="flex items-center gap-2 font-medium">
        <span
          className={cn(
            "size-2 rounded-full",
            state === "done" && "bg-success",
            state === "active" && "animate-pulse bg-accent",
            state === "waiting" && "bg-border-strong",
            state === "failed" && "bg-danger",
          )}
        />
        {label}
      </span>
      <span className="tabular text-muted">{detail}</span>
    </div>
  );
}

async function pollJob(id: string, onUpdate: (j: Job) => void, stop: () => boolean): Promise<Job | null> {
  for (;;) {
    if (stop()) return null;
    const j = await api.job(id);
    onUpdate(j);
    if (j.status === "succeeded" || j.status === "failed" || j.status === "cancelled") return j;
    await new Promise((r) => setTimeout(r, 600));
  }
}
