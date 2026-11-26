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

export interface ProfileColumn {
  name: string;
  type: string;
  kind: "numeric" | "temporal" | "text" | "boolean" | "other";
  count: number;
  nulls: number;
  null_pct: number;
  distinct: number;
  distinct_method: string;
  min?: unknown;
  max?: unknown;
  mean?: number | null;
  stddev?: number | null;
  min_length?: number | null;
  max_length?: number | null;
  avg_length?: number | null;
  quantiles?: { p05: number | null; p25: number | null; p50: number | null; p75: number | null; p95: number | null; method: string };
  histogram?: { start: number | string; end?: number; unit?: string; count: number }[];
  top_values?: { value: unknown; count: number }[];
  numeric_like_pct?: number;
  quality: { level: "info" | "warning" | "suggestion"; code: string; message: string }[];
}

export interface Profile {
  row_count: number;
  column_count: number;
  sampled: boolean;
  sample_rows: number | null;
  sample_method: string | null;
  detail_columns: number;
  columns: ProfileColumn[];
  duration_s: number;
}

export interface ProfileResponse {
  status: "ready" | "pending" | "failed";
  version_id: string;
  job_id: string | null;
  error: string | null;
  profile: Profile | null;
}

export interface SavedQuery {
  id: string;
  name: string;
  description: string;
  sql: string;
  created_at: string;
  updated_at: string;
}

export interface QueryRun {
  id: string;
  sql: string;
  status: "succeeded" | "failed" | "rejected" | "timeout";
  row_count: number | null;
  engine_ms: number | null;
  total_ms: number | null;
  error: string | null;
  saved_query_id: string | null;
  created_at: string;
}

export type TransformStep =
  | { op: "select"; columns: string[] }
  | { op: "rename"; mapping: Record<string, string> }
  | { op: "filter"; conditions: { column: string; op: string; value?: unknown }[]; combine?: "and" | "or" }
  | { op: "drop_nulls"; columns: string[] }
  | { op: "sort"; keys: { column: string; desc: boolean }[] }
  | { op: "cast"; column: string; to: string }
  | { op: "derive"; name: string; expression: string }
  | { op: "group"; by: string[]; aggregations: { column: string | null; func: string; alias?: string }[] }
  | { op: "distinct"; columns: string[] }
  | { op: "limit"; count: number };

export interface Transformation {
  id: string;
  dataset_id: string;
  name: string;
  steps: TransformStep[];
  created_at: string;
  updated_at: string;
  sql: string | null;
  output_dataset_id: string | null;
}

export interface TransformPreview {
  sql: string;
  columns: ResultColumn[];
  rows: unknown[][];
  total_rows: number;
  truncated: boolean;
  engine_ms: number;
}

export type FilterOp =
  | "=" | "!=" | ">" | ">=" | "<" | "<="
  | "contains" | "not_contains" | "starts_with" | "ends_with"
  | "is_null" | "is_not_null" | "in" | "not_in";

export interface Condition {
  column: string;
  op: FilterOp;
  value?: unknown;
}

export type ChartType = "bar" | "line" | "area" | "scatter" | "histogram" | "stat";
export type Agg = "count" | "count_distinct" | "sum" | "avg" | "min" | "max" | "median";
export type Grain = "none" | "day" | "week" | "month" | "quarter" | "year";

export interface Measure {
  field: string | null;
  agg: Agg;
  label?: string | null;
}

export interface ChartOptions {
  title?: string | null;
  x_label?: string | null;
  y_label?: string | null;
  stacked?: boolean;
  bins?: number;
  sort?: "x" | "y_desc" | "y_asc";
  limit?: number;
  show_values?: boolean;
  orientation?: "vertical" | "horizontal";
}

export interface ChartSpec {
  type: ChartType;
  x?: string | null;
  y: Measure[];
  series?: string | null;
  grain?: Grain;
  filters?: Condition[];
  options?: ChartOptions;
}

export interface ChartSource {
  dataset_id?: string | null;
  saved_query_id?: string | null;
}

export interface Chart extends ChartSource {
  id: string;
  name: string;
  spec: ChartSpec;
  created_at: string;
  updated_at: string;
  source_name: string | null;
}

export interface ChartMeta {
  type: ChartType;
  x: string | null;
  measures: string[];
  measure_labels?: string[];
  series: string | null;
  truncated: boolean;
}

export interface ChartData {
  columns: ResultColumn[];
  rows: unknown[][];
  meta: ChartMeta;
  sql: string;
  engine_ms: number;
  total_ms: number;
}

export interface LayoutItem {
  i: string;
  chart_id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Dashboard {
  id: string;
  name: string;
  description: string;
  layout: LayoutItem[];
  filters: Condition[];
  created_at: string;
  updated_at: string;
}

export type ExportSource =
  | { kind: "query"; sql: string }
  | { kind: "dataset"; dataset_id: string }
  | { kind: "chart"; chart_id: string };

export interface ExportRecord {
  id: string;
  job_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "expired";
  format: "csv" | "parquet";
  filename: string;
  row_count: number | null;
  bytes: number | null;
  error: string | null;
  created_at: string;
  download_url: string | null;
}

export interface ActivityEvent {
  id: string;
  kind: string;
  subject_type: string;
  subject_id: string | null;
  summary: string;
  created_at: string;
}
