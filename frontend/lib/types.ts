export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ColumnSchema {
  name: string;
  type: string;
  nullable?: boolean;
}

export interface IngestReport {
  warnings?: string[];
  rejected_rows?: number;
  reject_samples?: { line: number; type: string; message: string }[];
  encoding?: string;
  possible_duplicate_headers?: string[];
  type_overrides?: Record<string, string>;
  cast_failures?: Record<string, number>;
  duration_s?: number;
}

export interface IngestOptions {
  delimiter?: string | null;
  header?: boolean | null;
  encoding?: "auto" | "utf-8" | "utf-16" | "latin-1";
  quote?: string | null;
  skip_rows?: number;
  max_reject_ratio?: number;
  type_overrides?: Record<string, string>;
}

export interface DatasetVersion {
  id: string;
  version: number;
  status: string;
  source_format: string;
  original_filename: string;
  raw_bytes: number | null;
  processed_bytes: number | null;
  row_count: number | null;
  column_count: number | null;
  columns: ColumnSchema[] | null;
  ingest_options: IngestOptions;
  ingest_report: IngestReport;
  error: string | null;
  created_at: string;
}

export type DatasetStatus = "pending" | "processing" | "ready" | "failed" | "deleting";

export interface Dataset {
  id: string;
  name: string;
  sql_name: string;
  description: string;
  status: DatasetStatus;
  created_at: string;
  updated_at: string;
  row_count: number | null;
  column_count: number | null;
  processed_bytes: number | null;
  source_format: string | null;
  current_version: DatasetVersion | null;
  latest_job_id: string | null;
  error: string | null;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string;
  error: string | null;
  attempts: number;
  result: Record<string, unknown> | null;
  payload: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ResultColumn {
  name: string;
  type: string;
}

export interface QueryResult {
  columns: ResultColumn[];
  rows: unknown[][];
  total_rows: number;
  truncated: boolean;
  max_rows: number;
  offset: number;
  limit: number;
  engine_ms: number;
  total_ms: number;
  datasets: string[];
  run_id: string | null;
}

export interface Preview {
  columns: ResultColumn[];
  rows: unknown[][];
  total_rows: number;
  offset: number;
  limit: number;
}
